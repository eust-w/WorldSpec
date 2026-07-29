"""Launch the digest-bound H1 100M training Job after a passing midterm gate."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from copy_kubernetes_file import copy_from_pod
from upload_kubernetes_file import upload_to_pod

ROOT = Path(__file__).resolve().parents[1]
KUBECONFIG = Path(
    os.environ.get(
        "KUBECONFIG",
        "/Users/d-robotics/.config/droboticflow/kubeconfigs/poc.config",
    )
)
NAMESPACE = os.environ.get("K8S_NAMESPACE", "worldspec-a800-poc")
BUILD_NAMESPACE = os.environ.get("WORLD_SPEC_BUILD_NAMESPACE", "droboticflow")
PROFILE = ROOT / "examples/h1-kitchen/locomotion-training-profile.task-v1.json"
MIDTERM_PROFILE = ROOT / "examples/h1-kitchen/locomotion-midterm-profile.json"
JOB_TEMPLATE = ROOT / "ops/a800/h1-locomotion-formal-job.yaml"
PREPULL_TEMPLATE = ROOT / "ops/a800/h1-training-image-prepull-job.yaml"
ENTRYPOINT = ROOT / "ops/a800/h1-locomotion-formal-entrypoint.sh"
NAMESPACE_MANIFEST = ROOT / "ops/a800/namespace.yaml"
TIMEOUT_SECONDS = int(os.environ.get("WORLD_SPEC_A800_TIMEOUT_SECONDS", "86400"))


class LaunchError(RuntimeError):
    """Raised when a formal A800 run cannot preserve its execution contract."""


def run(
    command: list[str],
    *,
    check: bool = True,
    text: bool = True,
    input: str | bytes | None = None,
) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        command,
        check=check,
        text=text,
        input=input,
        capture_output=True,
    )


def kubectl(namespace: str, *args: str) -> list[str]:
    command = [
        "kubectl",
        "--kubeconfig",
        str(KUBECONFIG),
    ]
    if namespace:
        command.extend(("-n", namespace))
    command.extend(args)
    return command


def canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def file_identity(path: Path) -> tuple[int, str]:
    payload = path.read_bytes()
    return len(payload), f"sha256:{hashlib.sha256(payload).hexdigest()}"


def live_capacity_check() -> None:
    nodes = json.loads(run(kubectl("", "get", "nodes", "-o", "json")).stdout)
    pods = json.loads(run(kubectl("", "get", "pods", "-A", "-o", "json")).stdout)
    selector = "ehc.lgn5.c128m1024.8a800.8re.4d"
    available: dict[str, int] = {}
    for node in nodes["items"]:
        if node["metadata"]["labels"].get(
            "node.kubernetes.io/cce-instance-type"
        ) == selector:
            available[node["metadata"]["name"]] = int(
                node["status"]["allocatable"].get("nvidia.com/gpu", "0")
            )
    for pod in pods["items"]:
        node = pod.get("spec", {}).get("nodeName")
        if (
            node not in available
            or pod.get("status", {}).get("phase") in ("Succeeded", "Failed")
        ):
            continue
        available[node] -= sum(
            int(
                container.get("resources", {})
                .get("requests", {})
                .get("nvidia.com/gpu", "0")
            )
            for container in pod.get("spec", {}).get("containers", [])
        )
    if max(available.values(), default=0) < 1:
        raise LaunchError("A800_CAPACITY_BLOCKED: no unallocated A800 GPU is available")
    print("a800_capacity_preflight=" + json.dumps(available, sort_keys=True))


def validate_inputs(
    profile: dict[str, Any],
    midterm_profile: dict[str, Any],
    report_path: Path,
    checkpoint_path: Path,
    runtime_image: str,
) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    checkpoint_size, checkpoint_digest = file_identity(checkpoint_path)
    initialization = profile["initialization"]
    checkpoint = report["researchCheckpoint"]
    if (
        report.get("formalTrainingGate") != "passed"
        or report.get("qualityAssessment", {}).get("status") != "passed"
        or report.get("midtermProfileDigest")
        != initialization["sourceProfileDigest"]
        or canonical_digest(midterm_profile)
        != initialization["sourceProfileDigest"]
    ):
        raise LaunchError("midterm report/profile does not authorize formal training")
    if (
        checkpoint_digest != checkpoint.get("digest")
        or checkpoint_size != checkpoint.get("sizeBytes")
        or checkpoint.get("distribution") != "internal_only"
    ):
        raise LaunchError("midterm checkpoint/report identity mismatch")
    image_digest = runtime_image.rsplit("@", maxsplit=1)[-1]
    if profile["runtime"]["containerDigest"] != image_digest:
        raise LaunchError("formal Profile and runtime OCI digests differ")
    return report


def validate_result(path: Path) -> dict[str, Any]:
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    registry = Registry()
    schemas = {}
    for schema_path in (ROOT / "schemas/0.1").glob("*.schema.json"):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schemas[schema_path.name] = schema
        registry = registry.with_resource(
            schema["$id"],
            Resource.from_contents(schema),
        )
    result = json.loads(path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(
            schemas["h1-locomotion-training-result.schema.json"],
            registry=registry,
        ).iter_errors(result),
        key=lambda error: list(error.path),
    )
    if errors:
        raise LaunchError("; ".join(error.message for error in errors))
    return result


def main() -> int:
    report_path = Path(os.environ["WORLD_SPEC_MIDTERM_REPORT"]).resolve()
    checkpoint_path = Path(os.environ["WORLD_SPEC_MIDTERM_CHECKPOINT"]).resolve()
    for path in (
        KUBECONFIG,
        PROFILE,
        MIDTERM_PROFILE,
        JOB_TEMPLATE,
        PREPULL_TEMPLATE,
        ENTRYPOINT,
        NAMESPACE_MANIFEST,
        report_path,
        checkpoint_path,
    ):
        if not path.is_file():
            raise LaunchError(f"required file is absent: {path}")
    if run(["git", "-C", str(ROOT), "status", "--porcelain"]).stdout.strip():
        raise LaunchError("formal training requires a clean worktree")
    revision = run(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).stdout.strip()
    image_source = os.environ.get("WORLD_SPEC_IMAGE_SOURCE_REVISION", revision)
    remote = run(
        [
            "git",
            "ls-remote",
            "https://github.com/eust-w/WorldSpec.git",
            "refs/heads/feature/worldspec-v0.1",
        ]
    ).stdout.split()[0]
    if remote != revision:
        raise LaunchError(
            f"probe revision is not remote feature head: local={revision} remote={remote}"
        )
    midterm_profile = json.loads(MIDTERM_PROFILE.read_text(encoding="utf-8"))
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    runtime_image = os.environ.get(
        "WORLD_SPEC_H1_RUNTIME_IMAGE",
        midterm_profile["runtime"]["containerImage"],
    )
    validate_inputs(
        profile,
        midterm_profile,
        report_path,
        checkpoint_path,
        runtime_image,
    )
    package_lock = profile["runtime"]["packageLockDigest"]
    run(
        [
            "kubectl",
            "--kubeconfig",
            str(KUBECONFIG),
            "apply",
            "-f",
            str(NAMESPACE_MANIFEST),
        ]
    )
    if run(kubectl(NAMESPACE, "get", "jobs", "-o", "name")).stdout.strip():
        raise LaunchError("WorldSpec namespace already has an active or retained Job")
    live_capacity_check()

    suffix = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    short = revision[:12]
    script_configmap = f"worldspec-h1-formal-script-{short}-{suffix}"
    source_configmap = f"worldspec-h1-formal-source-{short}-{suffix}"
    prepull_job = ""
    job_name = ""
    pod_name = ""
    result_dir: Path | None = None
    temporary = Path(tempfile.mkdtemp(prefix="worldspec-h1-formal-"))
    try:
        prepull_manifest = temporary / "prepull.yaml"
        prepull_manifest.write_text(
            PREPULL_TEMPLATE.read_text(encoding="utf-8").replace(
                "__RUNTIME_IMAGE__",
                runtime_image,
            ),
            encoding="utf-8",
        )
        prepull_resource = run(
            kubectl(
                BUILD_NAMESPACE,
                "create",
                "-f",
                str(prepull_manifest),
                "-o",
                "name",
            )
        ).stdout.strip()
        prepull_job = prepull_resource.removeprefix("job.batch/")
        run(
            kubectl(
                BUILD_NAMESPACE,
                "wait",
                "--for=condition=complete",
                f"job/{prepull_job}",
                "--timeout=1800s",
            )
        )
        run(
            kubectl(
                BUILD_NAMESPACE,
                "delete",
                "job",
                prepull_job,
                "--wait=true",
                "--timeout=180s",
            )
        )
        prepull_job = ""

        archive_tar = run(
            ["git", "-C", str(ROOT), "archive", "--format=tar", revision],
            text=False,
        ).stdout
        archive = temporary / "worldspec.tar.gz"
        with (
            archive.open("wb") as raw,
            gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as stream,
        ):
            stream.write(archive_tar)
        _, archive_digest = file_identity(archive)
        run(
            kubectl(
                NAMESPACE,
                "create",
                "configmap",
                script_configmap,
                f"--from-file=run.sh={ENTRYPOINT}",
            )
        )
        run(
            kubectl(
                NAMESPACE,
                "create",
                "configmap",
                source_configmap,
                f"--from-file=worldspec.tar.gz={archive}",
            )
        )
        substitutions = {
            "__RUNTIME_IMAGE__": runtime_image,
            "__PROBE_DEFINITION_REVISION__": revision,
            "__IMAGE_SOURCE_REVISION__": image_source,
            "__PROBE_INPUT_REVISION__": revision,
            "__PACKAGE_LOCK_DIGEST__": package_lock,
            "__SOURCE_ARCHIVE_DIGEST__": archive_digest,
            "__SCRIPT_CONFIGMAP__": script_configmap,
            "__SOURCE_CONFIGMAP__": source_configmap,
        }
        manifest_text = JOB_TEMPLATE.read_text(encoding="utf-8")
        for source, replacement in substitutions.items():
            manifest_text = manifest_text.replace(source, replacement)
        manifest = temporary / "job.yaml"
        manifest.write_text(manifest_text, encoding="utf-8")
        resource = run(
            kubectl(NAMESPACE, "create", "-f", str(manifest), "-o", "name")
        ).stdout.strip()
        job_name = resource.removeprefix("job.batch/")
        result_dir = ROOT / "runs/a800" / job_name
        result_dir.mkdir(parents=True)
        print(
            f"namespace={NAMESPACE}\njob={job_name}\nprobe_revision={revision}\n"
            f"image={runtime_image}\nresult_dir={result_dir}"
        )

        deadline = time.monotonic() + TIMEOUT_SECONDS
        last_stage = ""
        input_uploaded = False
        artifacts_copied = False
        while time.monotonic() < deadline:
            found = run(
                kubectl(
                    NAMESPACE,
                    "get",
                    "pods",
                    "-l",
                    f"job-name={job_name}",
                    "-o",
                    "jsonpath={.items[0].metadata.name}",
                ),
                check=False,
            ).stdout.strip()
            if found:
                pod_name = found
                phase = run(
                    kubectl(
                        NAMESPACE,
                        "get",
                        "pod",
                        pod_name,
                        "-o",
                        "jsonpath={.status.phase}",
                    ),
                    check=False,
                ).stdout.strip()
                logs = run(
                    kubectl(NAMESPACE, "logs", pod_name),
                    check=False,
                ).stdout
                stages = [
                    line.split("=", maxsplit=1)[1]
                    for line in logs.splitlines()
                    if line.startswith("WORLDSPEC_A800_FORMAL_STAGE=")
                ]
                stage = stages[-1] if stages else ""
                if stage and stage != last_stage:
                    print(f"pod={pod_name} phase={phase} stage={stage}")
                    last_stage = stage
                prefix = kubectl(NAMESPACE)
                if stage == "waiting_for_input" and not input_uploaded:
                    report_size, report_digest = file_identity(report_path)
                    checkpoint_size, checkpoint_digest = file_identity(checkpoint_path)
                    upload_to_pod(
                        command_prefix=prefix,
                        pod=pod_name,
                        container="formal",
                        source=report_path,
                        remote_path="/scratch/inputs/midterm-report.json",
                        expected_size=report_size,
                        expected_digest=report_digest,
                    )
                    upload_to_pod(
                        command_prefix=prefix,
                        pod=pod_name,
                        container="formal",
                        source=checkpoint_path,
                        remote_path="/scratch/inputs/midterm-checkpoint.zip",
                        expected_size=checkpoint_size,
                        expected_digest=checkpoint_digest,
                    )
                    run(
                        kubectl(
                            NAMESPACE,
                            "exec",
                            pod_name,
                            "-c",
                            "formal",
                            "--",
                            "touch",
                            "/scratch/inputs/input-ready",
                        )
                    )
                    input_uploaded = True
                    print("input_uploaded=true")
                if stage == "artifact_ready" and not artifacts_copied:
                    (result_dir / "job.log").write_text(logs, encoding="utf-8")
                    marker = [
                        line.removeprefix("WORLDSPEC_A800_FORMAL_RESULT=")
                        for line in logs.splitlines()
                        if line.startswith("WORLDSPEC_A800_FORMAL_RESULT=")
                    ]
                    if len(marker) != 1:
                        raise LaunchError(
                            f"expected one formal result marker, found {len(marker)}"
                        )
                    result = json.loads(marker[0])
                    lowered_logs = [line.lower() for line in logs.splitlines()]
                    ccd_overflows = sum(
                        "ccd overflow" in line for line in lowered_logs
                    )
                    other_overflows = sum(
                        "overflow" in line and "ccd overflow" not in line
                        for line in lowered_logs
                    )
                    abnormal_contacts = sum(
                        "abnormal contact" in line for line in lowered_logs
                    )
                    runtime_diagnostics = (
                        ("CCD_OVERFLOW", ccd_overflows),
                        ("CAPACITY_OR_BUFFER_OVERFLOW", other_overflows),
                        ("ABNORMAL_CONTACT", abnormal_contacts),
                    )
                    for code, count in runtime_diagnostics:
                        if count:
                            result["diagnostics"].append(
                                {
                                    "code": code,
                                    "severity": "error",
                                    "message": (
                                        f"formal A800 log contained {count} "
                                        f"{code.lower().replace('_', ' ')} event(s)"
                                    ),
                                    "details": {"count": count},
                                }
                            )
                    if any(count for _, count in runtime_diagnostics):
                        result["status"] = "failed"
                        result["policyStatus"] = "non_publishable"
                    result_path = result_dir / "training-result.json"
                    result_path.write_text(
                        json.dumps(
                            result,
                            ensure_ascii=False,
                            indent=2,
                            sort_keys=True,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    for artifact in result["artifacts"]:
                        copy_from_pod(
                            command_prefix=prefix,
                            pod=pod_name,
                            container="formal",
                            remote_path=f"/scratch/results/artifacts/{artifact['path']}",
                            destination=result_dir / artifact["path"],
                            expected_size=artifact["sizeBytes"],
                            expected_digest=artifact["digest"],
                        )
                    run(
                        kubectl(
                            NAMESPACE,
                            "exec",
                            pod_name,
                            "-c",
                            "formal",
                            "--",
                            "touch",
                            "/scratch/results/artifact-copied",
                        )
                    )
                    artifacts_copied = True
                    print("artifact_copied=true")
                if phase in ("Succeeded", "Failed"):
                    break
            time.sleep(10)
        if pod_name:
            final_logs = run(
                kubectl(NAMESPACE, "logs", pod_name),
                check=False,
            ).stdout
            (result_dir / "job.log").write_text(final_logs, encoding="utf-8")
            for name, args in {
                "pod.yaml": ("get", "pod", pod_name, "-o", "yaml"),
                "pod-describe.txt": ("describe", "pod", pod_name),
                "job.yaml": ("get", "job", job_name, "-o", "yaml"),
            }.items():
                completed = run(kubectl(NAMESPACE, *args), check=False)
                (result_dir / name).write_text(
                    completed.stdout + completed.stderr,
                    encoding="utf-8",
                )
        if not pod_name:
            raise LaunchError("formal Job did not create a Pod")
        phase = run(
            kubectl(
                NAMESPACE,
                "get",
                "pod",
                pod_name,
                "-o",
                "jsonpath={.status.phase}",
            ),
            check=False,
        ).stdout.strip()
        if phase != "Succeeded" or not artifacts_copied:
            raise LaunchError(
                f"formal training ended in phase {phase or 'unknown'}; see {result_dir}"
            )
        result = validate_result(result_dir / "training-result.json")
        pointer = os.environ.get("WORLD_SPEC_FORMAL_RESULT_POINTER")
        if pointer:
            Path(pointer).write_text(str(result_dir) + "\n", encoding="utf-8")
        print(
            f"formal_status={result['status']}\n"
            f"policy_status={result['policyStatus']}\n"
            f"result_dir={result_dir}"
        )
        return 0 if result["status"] == "succeeded" else 3
    finally:
        if prepull_job:
            run(
                kubectl(
                    BUILD_NAMESPACE,
                    "delete",
                    "job",
                    prepull_job,
                    "--ignore-not-found",
                    "--wait=true",
                    "--timeout=180s",
                ),
                check=False,
            )
        if job_name:
            run(
                kubectl(
                    NAMESPACE,
                    "delete",
                    "job",
                    job_name,
                    "--ignore-not-found",
                    "--wait=true",
                    "--timeout=180s",
                ),
                check=False,
            )
        for configmap in (script_configmap, source_configmap):
            run(
                kubectl(
                    NAMESPACE,
                    "delete",
                    "configmap",
                    configmap,
                    "--ignore-not-found",
                ),
                check=False,
            )
        shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (LaunchError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
