from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
A800 = ROOT / "ops" / "a800"


def _documents(name: str) -> list[dict]:
    with (A800 / name).open(encoding="utf-8") as stream:
        return [document for document in yaml.safe_load_all(stream) if document]


def test_a800_namespace_is_isolated_and_gpu_bounded() -> None:
    documents = _documents("namespace.yaml")
    by_kind = {document["kind"]: document for document in documents}

    namespace = by_kind["Namespace"]
    assert namespace["metadata"]["name"] == "worldspec-a800-poc"

    service_account = by_kind["ServiceAccount"]
    assert service_account["metadata"]["namespace"] == "worldspec-a800-poc"
    assert service_account["automountServiceAccountToken"] is False

    quota = by_kind["ResourceQuota"]
    assert quota["metadata"]["namespace"] == "worldspec-a800-poc"
    assert quota["spec"]["hard"]["count/jobs.batch"] == "1"
    assert quota["spec"]["hard"]["requests.nvidia.com/gpu"] == "1"
    assert quota["spec"]["hard"]["limits.nvidia.com/gpu"] == "1"


def test_runtime_spike_job_is_tokenless_digest_ready_and_ephemeral() -> None:
    (job,) = _documents("h1-runtime-spike-job.yaml")
    assert job["kind"] == "Job"
    assert job["metadata"]["namespace"] == "worldspec-a800-poc"

    pod = job["spec"]["template"]["spec"]
    assert pod["serviceAccountName"] == "worldspec-a800-runner"
    assert pod["automountServiceAccountToken"] is False
    assert pod["restartPolicy"] == "Never"
    assert pod["securityContext"]["runAsNonRoot"] is True

    (container,) = pod["containers"]
    assert container["image"] == "__BASE_IMAGE__"
    assert container["imagePullPolicy"] == "Never"
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert container["resources"]["requests"]["nvidia.com/gpu"] == "1"
    assert container["resources"]["limits"]["nvidia.com/gpu"] == "1"
    environment = {item["name"]: item["value"] for item in container["env"]}
    assert environment["TMPDIR"] == "/scratch/tmp"

    volume_kinds = {
        next(key for key in volume if key != "name")
        for volume in pod["volumes"]
    }
    assert volume_kinds == {"emptyDir", "configMap"}
    assert sum("configMap" in volume for volume in pod["volumes"]) == 2
    assert all("secret" not in volume for volume in pod["volumes"])
    assert all("persistentVolumeClaim" not in volume for volume in pod["volumes"])


def test_runtime_spike_reports_execution_without_claiming_locked_oci() -> None:
    entrypoint = (A800 / "h1-runtime-spike-entrypoint.sh").read_text(encoding="utf-8")

    assert '"executionEvidence": "executed"' in entrypoint
    assert '"runtimeAcceptance": "executed_not_locked"' in entrypoint
    assert '"materialization": "verified_git_archive"' in entrypoint
    assert 'jaxBackend"] != "gpu"' in entrypoint
    assert "WORLDSPEC_A800_SPIKE_RESULT=" in entrypoint
