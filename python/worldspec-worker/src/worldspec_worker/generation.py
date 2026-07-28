"""Locked TRELLIS.2 and Nerfstudio generation adapters."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import io
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .cas import FileCas
from .runner import Handler, WorkerFailure


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _profile(job: dict[str, Any], cas: FileCas, backend: str) -> dict[str, Any]:
    profiles = job.get("profileDigests", [])
    if len(profiles) != 1:
        raise WorkerFailure(
            "WORKER_PROFILE_CARDINALITY_INVALID",
            "Generation requires exactly one GenerationProfile digest.",
            {"actual": len(profiles), "required": 1},
        )
    try:
        profile = json.loads(cas.read(profiles[0]))
    except json.JSONDecodeError as error:
        raise WorkerFailure(
            "WORKER_PROFILE_INVALID", "GenerationProfile is not valid JSON."
        ) from error
    if profile.get("backend") != backend:
        raise WorkerFailure(
            "WORKER_PROFILE_BACKEND_MISMATCH",
            f"The {backend} adapter cannot execute this GenerationProfile.",
            {"profileBackend": profile.get("backend")},
        )
    if profile.get("evidenceCeiling") not in {"generated", "estimated"}:
        raise WorkerFailure(
            "WORKER_PROFILE_INVALID",
            "GenerationProfile must cap evidence at generated or estimated.",
        )
    return profile


def _verify_container(profile: dict[str, Any]) -> None:
    expected = profile.get("containerDigest")
    actual = os.environ.get("WORLDSPEC_CONTAINER_DIGEST")
    if actual is None:
        raise WorkerFailure(
            "WORKER_CONTAINER_BINDING_MISSING",
            "A real generation run requires WORLDSPEC_CONTAINER_DIGEST.",
            {"expected": expected, "executionEvidence": "not_executed"},
        )
    if actual != expected:
        raise WorkerFailure(
            "WORKER_CONTAINER_BINDING_MISMATCH",
            "The running OCI digest does not match GenerationProfile.containerDigest.",
            {
                "expected": expected,
                "actual": actual,
                "executionEvidence": "not_executed",
            },
        )


def _require_module(module: str, distribution: str, version: str) -> Any:
    try:
        loaded = importlib.import_module(module)
    except ModuleNotFoundError as error:
        raise WorkerFailure(
            "WORKER_DEPENDENCY_UNAVAILABLE",
            f"{distribution} is required by this generation adapter.",
            {
                "module": module,
                "distribution": distribution,
                "requiredVersion": version,
                "executionEvidence": "not_executed",
            },
        ) from error
    if version != "locked-by-source-digest":
        try:
            actual = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as error:
            raise WorkerFailure(
                "WORKER_DEPENDENCY_VERSION_UNKNOWN",
                f"Cannot verify the installed {distribution} version.",
                {"requiredVersion": version, "executionEvidence": "not_executed"},
            ) from error
        if actual != version:
            raise WorkerFailure(
                "WORKER_DEPENDENCY_VERSION_MISMATCH",
                f"{distribution} version does not match the locked profile.",
                {
                    "requiredVersion": version,
                    "actualVersion": actual,
                    "executionEvidence": "not_executed",
                },
            )
    return loaded


def _gpu(torch: Any, job: dict[str, Any]) -> None:
    if int(job.get("limits", {}).get("gpuCount", 0)) < 1:
        raise WorkerFailure(
            "WORKER_GPU_NOT_REQUESTED",
            "A real generation job must request at least one GPU.",
            {"executionEvidence": "not_executed"},
        )
    if not torch.cuda.is_available():
        raise WorkerFailure(
            "WORKER_GPU_UNAVAILABLE",
            "CUDA is unavailable in the locked generation worker.",
            {"executionEvidence": "not_executed"},
        )


def _artifact(
    cas: FileCas,
    payload: bytes,
    backend: str,
    role: str,
    media_type: str,
    suffix: str,
) -> dict[str, Any]:
    digest = cas.put(payload)
    identity = digest.removeprefix("sha256:")
    return {
        "id": f"artifact://worker/{backend}/{role}/{identity}",
        "digest": digest,
        "mediaType": media_type,
        "path": f"generated/{backend}/{identity}.{suffix}",
        "sizeBytes": len(payload),
        "role": role,
    }


def _quality(
    cas: FileCas,
    backend: str,
    profile: dict[str, Any],
    source_digests: list[str],
    outputs: list[dict[str, Any]],
    runtime: dict[str, Any],
) -> dict[str, Any]:
    report = {
        "kind": "worldspec.generation.quality-report",
        "specVersion": "0.1.0",
        "backend": backend,
        "backendVersion": profile["backendVersion"],
        "containerDigest": profile["containerDigest"],
        "modelDigests": profile.get("modelDigests", []),
        "sourceDigests": source_digests,
        "outputDigests": [output["digest"] for output in outputs],
        "evidenceCeiling": profile["evidenceCeiling"],
        "runtime": runtime,
        "uncertainty": {
            "scale": "unknown",
            "hiddenGeometry": "generated_or_reconstructed",
            "mass": "unknown",
            "friction": "unknown",
            "articulation": "unknown",
        },
        "requiresStandardIngestionAndDoctor": True,
        "certificationIssued": False,
    }
    return _artifact(
        cas,
        _canonical(report),
        backend,
        "quality_report",
        "application/vnd.worldspec.generation-quality+json",
        "json",
    )


def _model_cache(profile: dict[str, Any], backend: str) -> Path:
    model_digests = profile.get("modelDigests", [])
    if len(model_digests) != 1:
        raise WorkerFailure(
            "MODEL_DIGEST_CARDINALITY_INVALID",
            f"{backend} requires exactly one immutable model bundle digest.",
        )
    root_value = os.environ.get("WORLDSPEC_MODEL_CACHE_ROOT")
    if not root_value:
        raise WorkerFailure(
            "MODEL_CACHE_UNCONFIGURED",
            "WORLDSPEC_MODEL_CACHE_ROOT is required for a real model run.",
            {"executionEvidence": "not_executed"},
        )
    root = Path(root_value).resolve()
    digest = model_digests[0]
    model = (root / digest.removeprefix("sha256:")).resolve()
    if root not in model.parents or not model.is_dir():
        raise WorkerFailure(
            "MODEL_BUNDLE_UNAVAILABLE",
            "The immutable model bundle is absent from the read-only cache.",
            {"modelDigest": digest, "executionEvidence": "not_executed"},
        )
    manifest_path = model / "worldspec-model.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as error:
        raise WorkerFailure(
            "MODEL_BUNDLE_MANIFEST_INVALID",
            "The model bundle requires a valid worldspec-model.json.",
            {"modelDigest": digest, "executionEvidence": "not_executed"},
        ) from error
    if manifest.get("digest") != digest or manifest.get("backend") != backend:
        raise WorkerFailure(
            "MODEL_BUNDLE_BINDING_MISMATCH",
            "The model bundle manifest does not match the profile.",
            {"modelDigest": digest, "executionEvidence": "not_executed"},
        )
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise WorkerFailure(
            "MODEL_BUNDLE_MANIFEST_INVALID",
            "The model bundle manifest must enumerate every immutable file.",
            {"modelDigest": digest, "executionEvidence": "not_executed"},
        )
    declared_paths: set[str] = set()
    normalized_files: list[dict[str, Any]] = []
    for item in files:
        if not isinstance(item, dict):
            raise WorkerFailure(
                "MODEL_BUNDLE_MANIFEST_INVALID",
                "Every model file entry must be an object.",
                {"modelDigest": digest, "executionEvidence": "not_executed"},
            )
        relative = Path(str(item.get("path", "")))
        expected_file_digest = item.get("digest")
        expected_size = item.get("sizeBytes")
        if (
            not relative.parts
            or relative.is_absolute()
            or ".." in relative.parts
            or relative.as_posix() == "worldspec-model.json"
            or not isinstance(expected_file_digest, str)
            or not expected_file_digest.startswith("sha256:")
            or len(expected_file_digest) != 71
            or not isinstance(expected_size, int)
            or expected_size < 0
        ):
            raise WorkerFailure(
                "MODEL_BUNDLE_MANIFEST_INVALID",
                "A model file entry has an unsafe path or invalid digest/size.",
                {"modelDigest": digest, "executionEvidence": "not_executed"},
            )
        logical_path = relative.as_posix()
        if logical_path in declared_paths:
            raise WorkerFailure(
                "MODEL_BUNDLE_MANIFEST_INVALID",
                "The model bundle manifest contains duplicate file paths.",
                {"path": logical_path, "executionEvidence": "not_executed"},
            )
        declared_paths.add(logical_path)
        candidate = (model / relative).resolve()
        if model not in candidate.parents or not candidate.is_file() or candidate.is_symlink():
            raise WorkerFailure(
                "MODEL_BUNDLE_FILE_INVALID",
                "A declared model file is missing, escapes the bundle, or is a symlink.",
                {"path": logical_path, "executionEvidence": "not_executed"},
            )
        hasher = hashlib.sha256()
        actual_size = 0
        with candidate.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                hasher.update(chunk)
                actual_size += len(chunk)
        actual_digest = f"sha256:{hasher.hexdigest()}"
        if actual_digest != expected_file_digest or actual_size != expected_size:
            raise WorkerFailure(
                "MODEL_BUNDLE_FILE_MISMATCH",
                "A model file does not match its locked digest and size.",
                {
                    "path": logical_path,
                    "expectedDigest": expected_file_digest,
                    "actualDigest": actual_digest,
                    "expectedSize": expected_size,
                    "actualSize": actual_size,
                    "executionEvidence": "not_executed",
                },
            )
        normalized_files.append(
            {
                "path": logical_path,
                "digest": expected_file_digest,
                "sizeBytes": expected_size,
            }
        )
    actual_paths = {
        path.relative_to(model).as_posix()
        for path in model.rglob("*")
        if path.is_file() and path.name != "worldspec-model.json"
    }
    if actual_paths != declared_paths:
        raise WorkerFailure(
            "MODEL_BUNDLE_UNDECLARED_FILES",
            "The model bundle contains undeclared or omitted files.",
            {
                "undeclared": sorted(actual_paths - declared_paths),
                "missing": sorted(declared_paths - actual_paths),
                "executionEvidence": "not_executed",
            },
        )
    identity = {
        "formatVersion": manifest.get("formatVersion"),
        "backend": backend,
        "files": sorted(normalized_files, key=lambda item: item["path"]),
    }
    computed_digest = f"sha256:{hashlib.sha256(_canonical(identity)).hexdigest()}"
    if manifest.get("formatVersion") != "0.1.0" or computed_digest != digest:
        raise WorkerFailure(
            "MODEL_BUNDLE_DIGEST_MISMATCH",
            "The canonical model bundle manifest does not match the profile digest.",
            {
                "expectedDigest": digest,
                "actualDigest": computed_digest,
                "executionEvidence": "not_executed",
            },
        )
    return model


def trellis2_handler(job: dict[str, Any], cas: FileCas) -> list[dict[str, Any]]:
    if job.get("operation") != "generate":
        raise WorkerFailure(
            "WORKER_OPERATION_UNSUPPORTED", "TRELLIS.2 only accepts generate jobs."
        )
    profile = _profile(job, cas, "trellis2")
    if profile.get("modality") != "single_image":
        raise WorkerFailure(
            "WORKER_MODALITY_UNSUPPORTED", "TRELLIS.2 requires single_image modality."
        )
    unsupported_outputs = set(profile["outputFormats"]) - {"glb", "quality_report"}
    if unsupported_outputs:
        raise WorkerFailure(
            "GENERATION_OUTPUT_UNSUPPORTED",
            "The TRELLIS.2 v0.1 adapter cannot produce every requested output.",
            {"unsupported": sorted(unsupported_outputs)},
        )
    if len(job.get("inputs", [])) != 1:
        raise WorkerFailure(
            "WORKER_INPUT_CARDINALITY_INVALID",
            "TRELLIS.2 requires exactly one image artifact.",
        )
    if not str(job["inputs"][0].get("mediaType", "")).startswith("image/"):
        raise WorkerFailure(
            "WORKER_SOURCE_FORMAT_UNSUPPORTED",
            "TRELLIS.2 requires an input artifact with an image media type.",
        )
    _verify_container(profile)
    torch = _require_module("torch", "torch", "locked-by-source-digest")
    _gpu(torch, job)
    image_module = _require_module("PIL.Image", "Pillow", "locked-by-source-digest")
    pipelines = _require_module(
        "trellis2.pipelines", "TRELLIS.2", "locked-by-source-digest"
    )
    o_voxel = _require_module("o_voxel", "o-voxel", "locked-by-source-digest")
    model_path = _model_cache(profile, "trellis2")
    source = job["inputs"][0]
    source_payload = cas.read(source["digest"])
    parameters = profile.get("parameters", {})
    target_faces = int(parameters.get("decimationTarget", 1_000_000))
    texture_size = int(parameters.get("textureSize", 4096))
    if not 1_000 <= target_faces <= 4_000_000 or not 256 <= texture_size <= 8192:
        raise WorkerFailure(
            "GENERATION_PARAMETER_OUT_OF_RANGE",
            "TRELLIS.2 decimationTarget or textureSize exceeds the bounded profile.",
        )
    image = image_module.open(io.BytesIO(source_payload))
    pipeline = pipelines.Trellis2ImageTo3DPipeline.from_pretrained(str(model_path))
    pipeline.cuda()
    mesh = pipeline.run(image)[0]
    mesh.simplify(16_777_216)
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices,
        faces=mesh.faces,
        attr_volume=mesh.attrs,
        coords=mesh.coords,
        attr_layout=mesh.layout,
        voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=target_faces,
        texture_size=texture_size,
        remesh=True,
        remesh_band=1,
        remesh_project=0,
        verbose=False,
    )
    with tempfile.TemporaryDirectory(prefix="worldspec-trellis2-") as temporary:
        path = Path(temporary) / "asset.glb"
        glb.export(str(path), extension_webp=True)
        glb_payload = path.read_bytes()
    outputs = [
        _artifact(cas, glb_payload, "trellis2", "generated_glb", "model/gltf-binary", "glb")
    ]
    outputs.append(
        _quality(
            cas,
            "trellis2",
            profile,
            [source["digest"]],
            outputs,
            {
                "cudaDevice": str(torch.cuda.get_device_name(0)),
                "torchVersion": str(torch.__version__),
                "realExecution": True,
            },
        )
    )
    return outputs


def _executable(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise WorkerFailure(
            "WORKER_DEPENDENCY_UNAVAILABLE",
            f"{name} is absent from the locked Nerfstudio worker.",
            {"executable": name, "executionEvidence": "not_executed"},
        )
    return path


def _run(command: list[str], timeout: int, cwd: Path) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "WANDB_MODE": "disabled"},
        )
    except subprocess.TimeoutExpired as error:
        raise WorkerFailure(
            "GENERATION_TIMEOUT", f"Command timed out: {Path(command[0]).name}"
        ) from error
    except subprocess.CalledProcessError as error:
        raise WorkerFailure(
            "GENERATION_BACKEND_FAILED",
            f"Command failed: {Path(command[0]).name}",
            {"returnCode": error.returncode, "stderrTail": error.stderr[-4000:]},
        ) from error
    return result.stdout[-4000:]


def _materialize_inputs(job: dict[str, Any], cas: FileCas, directory: Path) -> list[str]:
    digests = []
    for index, item in enumerate(job.get("inputs", [])):
        suffix = Path(item["path"]).suffix.lower()
        if suffix not in {
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".mp4",
            ".mov",
            ".mkv",
            ".webm",
        }:
            raise WorkerFailure(
                "WORKER_SOURCE_FORMAT_UNSUPPORTED",
                "Nerfstudio accepts only declared image or video artifacts.",
                {"logicalPath": item["path"]},
            )
        destination = directory / f"{index:06d}{suffix}"
        destination.write_bytes(cas.read(item["digest"]))
        digests.append(item["digest"])
    return digests


def nerfstudio_handler(job: dict[str, Any], cas: FileCas) -> list[dict[str, Any]]:
    if job.get("operation") != "generate":
        raise WorkerFailure(
            "WORKER_OPERATION_UNSUPPORTED", "Nerfstudio only accepts generate jobs."
        )
    profile = _profile(job, cas, "nerfstudio")
    if profile.get("modality") not in {"multi_view", "video"}:
        raise WorkerFailure(
            "WORKER_MODALITY_UNSUPPORTED",
            "Nerfstudio requires multi_view or video modality.",
        )
    unsupported_outputs = set(profile["outputFormats"]) - {
        "nerf",
        "3dgs",
        "camera_poses",
        "quality_report",
    }
    if unsupported_outputs:
        raise WorkerFailure(
            "GENERATION_OUTPUT_UNSUPPORTED",
            "The Nerfstudio v0.1 adapter cannot produce every requested output.",
            {"unsupported": sorted(unsupported_outputs)},
        )
    _verify_container(profile)
    _require_module("nerfstudio", "nerfstudio", profile["backendVersion"])
    torch = _require_module("torch", "torch", "locked-by-source-digest")
    _gpu(torch, job)
    process = _executable("ns-process-data")
    train = _executable("ns-train")
    export = _executable("ns-export")
    timeout = int(job["limits"]["timeoutSeconds"])
    parameters = profile.get("parameters", {})
    method = str(parameters.get("method", "nerfacto"))
    if method not in {"nerfacto", "splatfacto"}:
        raise WorkerFailure(
            "GENERATION_PARAMETER_OUT_OF_RANGE",
            "Nerfstudio method must be nerfacto or splatfacto in v0.1.",
        )
    iterations = int(parameters.get("maxNumIterations", 30_000))
    if not 1 <= iterations <= 100_000:
        raise WorkerFailure(
            "GENERATION_PARAMETER_OUT_OF_RANGE",
            "maxNumIterations must be between 1 and 100000.",
        )
    with tempfile.TemporaryDirectory(prefix="worldspec-nerfstudio-") as temporary:
        root = Path(temporary)
        source_dir = root / "source"
        source_dir.mkdir()
        source_digests = _materialize_inputs(job, cas, source_dir)
        processed = root / "processed"
        outputs_dir = root / "outputs"
        mode = "video" if profile["modality"] == "video" else "images"
        source_argument = source_dir / "000000" if mode == "video" else source_dir
        if mode == "video":
            matches = list(source_dir.iterdir())
            if len(matches) != 1:
                raise WorkerFailure(
                    "WORKER_INPUT_CARDINALITY_INVALID",
                    "Video reconstruction requires exactly one video.",
                )
            source_argument = matches[0]
        process_log = _run(
            [
                process,
                mode,
                "--data",
                str(source_argument),
                "--output-dir",
                str(processed),
            ],
            timeout,
            root,
        )
        train_log = _run(
            [
                train,
                method,
                "--data",
                str(processed),
                "--output-dir",
                str(outputs_dir),
                "--timestamp",
                "worldspec",
                "--vis",
                "tensorboard",
                "--max-num-iterations",
                str(iterations),
            ],
            timeout,
            root,
        )
        configs = sorted(outputs_dir.rglob("config.yml"))
        if len(configs) != 1:
            raise WorkerFailure(
                "GENERATION_OUTPUT_AMBIGUOUS",
                "Nerfstudio did not produce exactly one config.yml.",
                {"configCount": len(configs)},
            )
        config = configs[0]
        requested = set(profile["outputFormats"])
        generated_files: list[tuple[Path, str, str, str]] = [
            (config, "nerfstudio_config", "application/yaml", "yml")
        ]
        if "nerf" in requested:
            checkpoints = sorted(outputs_dir.rglob("*.ckpt"))
            if not checkpoints:
                raise WorkerFailure(
                    "GENERATION_OUTPUT_MISSING",
                    "Nerfstudio did not produce a model checkpoint.",
                )
            generated_files.append(
                (
                    checkpoints[-1],
                    "nerfstudio_checkpoint",
                    "application/octet-stream",
                    "ckpt",
                )
            )
        export_root = root / "export"
        if "camera_poses" in requested:
            camera_dir = export_root / "cameras"
            _run(
                [
                    export,
                    "cameras",
                    "--load-config",
                    str(config),
                    "--output-dir",
                    str(camera_dir),
                ],
                timeout,
                root,
            )
            for camera in sorted(camera_dir.glob("*.json")):
                generated_files.append(
                    (camera, "camera_poses", "application/json", "json")
                )
        if "3dgs" in requested:
            if method != "splatfacto":
                raise WorkerFailure(
                    "GENERATION_PROFILE_INCOMPATIBLE",
                    "3dgs output requires the splatfacto method.",
                )
            splat_dir = export_root / "splat"
            splat_dir.mkdir(parents=True, exist_ok=True)
            splat = splat_dir / "splat.ply"
            _run(
                [
                    export,
                    "gaussian-splat",
                    "--load-config",
                    str(config),
                    "--output-dir",
                    str(splat_dir),
                    "--output-filename",
                    splat.name,
                ],
                timeout,
                root,
            )
            generated_files.append((splat, "generated_3dgs", "model/ply", "ply"))
        outputs = [
            _artifact(cas, path.read_bytes(), "nerfstudio", role, media_type, suffix)
            for path, role, media_type, suffix in generated_files
        ]
        outputs.append(
            _quality(
                cas,
                "nerfstudio",
                profile,
                source_digests,
                outputs,
                {
                    "nerfstudioVersion": profile["backendVersion"],
                    "method": method,
                    "maxNumIterations": iterations,
                    "processLogTail": process_log,
                    "trainLogTail": train_log,
                    "cudaDevice": str(torch.cuda.get_device_name(0)),
                    "realExecution": True,
                },
            )
        )
        return outputs


GENERATION_ADAPTERS: dict[str, Handler] = {
    "trellis2": trellis2_handler,
    "nerfstudio": nerfstudio_handler,
}
