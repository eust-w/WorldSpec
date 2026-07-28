"""Real optional ingestion adapters for isolated CAD and OpenUSD workers."""

from __future__ import annotations

import importlib
import json
import tempfile
from pathlib import Path
from typing import Any

from .cas import FileCas
from .generation import GENERATION_ADAPTERS
from .runner import Handler, WorkerFailure
from .training import TRAINING_ADAPTERS


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _one_input(job: dict[str, Any], cas: FileCas) -> tuple[dict[str, Any], bytes]:
    inputs = job.get("inputs", [])
    if len(inputs) != 1:
        raise WorkerFailure(
            "WORKER_INPUT_CARDINALITY_INVALID",
            "CAD and OpenUSD ingestion require exactly one immutable source artifact.",
            {"actual": len(inputs), "required": 1},
        )
    item = inputs[0]
    return item, cas.read(item["digest"])


def _profile(job: dict[str, Any], cas: FileCas) -> dict[str, Any]:
    profiles = job.get("profileDigests", [])
    if len(profiles) != 1:
        raise WorkerFailure(
            "WORKER_PROFILE_CARDINALITY_INVALID",
            "The ingestion worker requires exactly one IngestionProfile digest.",
            {"actual": len(profiles), "required": 1},
        )
    try:
        return json.loads(cas.read(profiles[0]))
    except json.JSONDecodeError as error:
        raise WorkerFailure(
            "WORKER_PROFILE_INVALID", "IngestionProfile is not valid JSON."
        ) from error


def _require(module: str, distribution: str, version: str) -> Any:
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError as error:
        raise WorkerFailure(
            "WORKER_DEPENDENCY_UNAVAILABLE",
            f"{distribution} is required by this isolated adapter.",
            {
                "module": module,
                "distribution": distribution,
                "requiredVersion": version,
                "executionEvidence": "not_executed",
            },
        ) from error


def _output(
    kind: str,
    source: dict[str, Any],
    inspection: dict[str, Any],
    cas: FileCas,
) -> list[dict[str, Any]]:
    document = {
        "kind": kind,
        "specVersion": "0.1.0",
        "status": "needs_review",
        "source": {
            "artifactRef": source["id"],
            "digest": source["digest"],
            "mediaType": source["mediaType"],
            "logicalPath": source["path"],
        },
        "inspection": inspection,
        "nativePayload": {
            "digest": source["digest"],
            "preservation": "source_blob_in_cas",
            "canonicalMappingComplete": False,
        },
        "blocking": [
            "CANONICAL_WORLD_DEFINITION_MAPPING_REQUIRED",
            "RIGHTS_AND_DISTRIBUTION_REVIEW_REQUIRED",
        ],
    }
    payload = _canonical(document)
    digest = cas.put(payload)
    suffix = source["digest"].removeprefix("sha256:")
    return [
        {
            "id": f"artifact://worker/{kind}/{suffix}",
            "digest": digest,
            "mediaType": "application/vnd.worldspec.ingestion-inspection+json",
            "path": f"inspection/{kind}-{suffix}.json",
            "sizeBytes": len(payload),
            "role": "ingestion_inspection",
        }
    ]


def cad_handler(job: dict[str, Any], cas: FileCas) -> list[dict[str, Any]]:
    if job.get("operation") != "ingest":
        raise WorkerFailure(
            "WORKER_OPERATION_UNSUPPORTED", "The CAD adapter only accepts ingest jobs."
        )
    profile = _profile(job, cas)
    source, payload = _one_input(job, cas)
    formats = set(profile.get("formats", []))
    logical_suffix = Path(source["path"]).suffix.lower()
    if logical_suffix in {".step", ".stp"}:
        source_format = "step"
        module_name = "OCP.STEPControl"
        reader_name = "STEPControl_Reader"
    elif logical_suffix in {".iges", ".igs"}:
        source_format = "iges"
        module_name = "OCP.IGESControl"
        reader_name = "IGESControl_Reader"
    else:
        raise WorkerFailure(
            "WORKER_SOURCE_FORMAT_UNSUPPORTED",
            "The CAD adapter accepts STEP/STP or IGES/IGS sources.",
            {"logicalPath": source["path"]},
        )
    if source_format not in formats:
        raise WorkerFailure(
            "WORKER_PROFILE_FORMAT_MISMATCH",
            "The source format is not authorized by the IngestionProfile.",
            {"sourceFormat": source_format, "profileFormats": sorted(formats)},
        )

    reader_module = _require(module_name, "cadquery-ocp", "pinned-by-oci-lock")
    if_select = _require("OCP.IFSelect", "cadquery-ocp", "pinned-by-oci-lock")
    brep_bnd = _require("OCP.BRepBndLib", "cadquery-ocp", "pinned-by-oci-lock")
    bnd = _require("OCP.Bnd", "cadquery-ocp", "pinned-by-oci-lock")
    top_abs = _require("OCP.TopAbs", "cadquery-ocp", "pinned-by-oci-lock")
    top_exp = _require("OCP.TopExp", "cadquery-ocp", "pinned-by-oci-lock")

    with tempfile.TemporaryDirectory(prefix="worldspec-cad-") as temporary:
        path = Path(temporary) / f"source.{source_format}"
        path.write_bytes(payload)
        reader = getattr(reader_module, reader_name)()
        if reader.ReadFile(str(path)) != if_select.IFSelect_RetDone:
            raise WorkerFailure(
                "CAD_NATIVE_READ_FAILED", f"OpenCascade could not read {source_format}."
            )
        transferred = int(reader.TransferRoots())
        shape = reader.OneShape()
        box = bnd.Bnd_Box()
        add_bounds = getattr(
            brep_bnd.BRepBndLib,
            "Add_s",
            getattr(brep_bnd.BRepBndLib, "Add", None),
        )
        if add_bounds is None:
            raise WorkerFailure(
                "CAD_API_INCOMPATIBLE",
                "The installed OpenCascade binding has no supported BRepBndLib.Add API.",
            )
        add_bounds(shape, box)
        bounds = list(box.Get()) if not box.IsVoid() else None

        def count(kind: Any) -> int:
            explorer = top_exp.TopExp_Explorer(shape, kind)
            result = 0
            while explorer.More():
                result += 1
                explorer.Next()
            return result

        topology = {
            "solids": count(top_abs.TopAbs_SOLID),
            "shells": count(top_abs.TopAbs_SHELL),
            "faces": count(top_abs.TopAbs_FACE),
            "edges": count(top_abs.TopAbs_EDGE),
            "vertices": count(top_abs.TopAbs_VERTEX),
        }
    return _output(
        "cad",
        source,
        {
            "adapter": "occt",
            "sourceFormat": source_format,
            "rootsTransferred": transferred,
            "boundsNativeUnits": bounds,
            "topology": topology,
            "unitStatus": "requires_profile_or_source_confirmation",
            "pmiGdAndTFeatureHistory": "native_payload_only",
        },
        cas,
    )


def openusd_handler(job: dict[str, Any], cas: FileCas) -> list[dict[str, Any]]:
    if job.get("operation") != "ingest":
        raise WorkerFailure(
            "WORKER_OPERATION_UNSUPPORTED", "The OpenUSD adapter only accepts ingest jobs."
        )
    profile = _profile(job, cas)
    source, payload = _one_input(job, cas)
    if "openusd" not in set(profile.get("formats", [])):
        raise WorkerFailure(
            "WORKER_PROFILE_FORMAT_MISMATCH",
            "The IngestionProfile does not authorize OpenUSD.",
            {"profileFormats": profile.get("formats", [])},
        )
    usd = _require("pxr.Usd", "usd-core", "26.8")
    usd_geom = _require("pxr.UsdGeom", "usd-core", "26.8")
    with tempfile.TemporaryDirectory(prefix="worldspec-usd-") as temporary:
        suffix = Path(source["path"]).suffix.lower()
        if suffix not in {".usd", ".usda", ".usdc"}:
            suffix = ".usd"
        path = Path(temporary) / f"source{suffix}"
        path.write_bytes(payload)
        stage = usd.Stage.Open(str(path))
        if stage is None:
            raise WorkerFailure("OPENUSD_STAGE_OPEN_FAILED", "OpenUSD could not open the Stage.")
        prims = [
            {
                "path": str(prim.GetPath()),
                "typeName": prim.GetTypeName(),
                "active": bool(prim.IsActive()),
                "instance": bool(prim.IsInstance()),
            }
            for prim in stage.Traverse()
        ]
        default_prim = stage.GetDefaultPrim()
        inspection = {
            "adapter": "usd-core",
            "runtimeVersion": getattr(usd, "__version__", "26.8"),
            "defaultPrim": str(default_prim.GetPath()) if default_prim else None,
            "upAxis": str(usd_geom.GetStageUpAxis(stage)),
            "metersPerUnit": float(usd_geom.GetStageMetersPerUnit(stage)),
            "primCount": len(prims),
            "prims": prims,
            "layerStackPreservation": "native_payload_only",
            "unknownSchemas": "native_payload_only",
        }
    return _output("openusd", source, inspection, cas)


ADAPTERS: dict[str, Handler] = {
    "cad": cad_handler,
    "openusd": openusd_handler,
    **GENERATION_ADAPTERS,
    **TRAINING_ADAPTERS,
}


def adapter(name: str) -> Handler:
    try:
        return ADAPTERS[name]
    except KeyError as error:
        raise ValueError(f"unknown worker adapter: {name}") from error
