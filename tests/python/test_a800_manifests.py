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
    assert quota["spec"]["hard"]["requests.memory"] == "64Gi"
    assert quota["spec"]["hard"]["limits.memory"] == "64Gi"
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


def test_h1_image_builder_contains_registry_secret_to_build_namespace() -> None:
    (job,) = _documents("h1-training-image-build-job.yaml")
    assert job["metadata"]["namespace"] == "droboticflow"

    pod = job["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    (container,) = pod["containers"]
    assert "@sha256:" in container["image"]
    assert "--digest-file=/dev/termination-log" in container["args"]
    assert any(argument.startswith("--destination=__") for argument in container["args"])
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert container["securityContext"]["capabilities"]["add"] == [
        "CHOWN",
        "DAC_OVERRIDE",
        "FOWNER",
        "SETGID",
        "SETUID",
    ]

    secret_volumes = [
        volume["secret"]["secretName"]
        for volume in pod["volumes"]
        if "secret" in volume
    ]
    assert secret_volumes == ["droboticflow-registry"]
    spike = _documents("h1-runtime-spike-job.yaml")[0]
    spike_volumes = spike["spec"]["template"]["spec"]["volumes"]
    assert all("secret" not in volume for volume in spike_volumes)


def test_h1_training_image_builds_as_root_but_runs_as_non_root() -> None:
    dockerfile = (
        Path(__file__).parents[2] / "containers" / "h1-training" / "Dockerfile"
    ).read_text(encoding="utf-8")
    build_user = dockerfile.index("USER 0:0")
    install = dockerfile.index("RUN python -m pip install")
    runtime_user = dockerfile.rindex("USER 10001:10001")
    assert build_user < install < runtime_user
    assert "chown -R 10001:10001 /home/worldspec /workspace" not in dockerfile


def test_locked_runtime_probe_uses_digest_without_credentials_or_installs() -> None:
    (job,) = _documents("h1-locked-runtime-probe-job.yaml")
    pod = job["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsUser"] == 10001
    assert pod["securityContext"]["runAsGroup"] == 10001
    (container,) = pod["containers"]
    assert container["image"] == "__RUNTIME_IMAGE__"
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert container["resources"]["requests"]["cpu"] == "8"
    assert container["resources"]["requests"]["memory"] == "32Gi"
    assert container["resources"]["limits"]["nvidia.com/gpu"] == "1"
    assert all("secret" not in volume for volume in pod["volumes"])
    assert all("persistentVolumeClaim" not in volume for volume in pod["volumes"])

    entrypoint = (A800 / "h1-locked-runtime-probe-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    assert '"runtimeAcceptance": "locked"' in entrypoint
    assert "uv sync" not in entrypoint
    assert "pip install" not in entrypoint
    assert "serviceAccountTokenMounted" in entrypoint


def test_capacity_scale_probe_is_isolated_and_uses_canonical_environment_count() -> None:
    (job,) = _documents("h1-capacity-scale-probe-job.yaml")
    assert job["metadata"]["namespace"] == "worldspec-a800-poc"
    assert job["metadata"]["labels"]["app.kubernetes.io/name"] == (
        "worldspec-h1-capacity-scale-probe"
    )
    pod = job["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsUser"] == 10001
    assert pod["securityContext"]["runAsGroup"] == 10001
    (container,) = pod["containers"]
    environment = {item["name"]: item["value"] for item in container["env"]}
    assert environment["WORLD_SPEC_PROBE_MODE"] == "capacity_scale"
    assert container["image"] == "__RUNTIME_IMAGE__"
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert container["resources"]["requests"]["nvidia.com/gpu"] == "1"
    assert all("secret" not in volume for volume in pod["volumes"])
    assert all("persistentVolumeClaim" not in volume for volume in pod["volumes"])

    entrypoint = (A800 / "h1-locked-runtime-probe-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    assert '"runtimeAcceptance": "capacity_scale_preflight"' in entrypoint
    assert '"canonicalTrainingStatus": "not_executed"' in entrypoint
    assert '"numEnvs": num_envs' in entrypoint
    assert '"effectiveNaconmax"' in entrypoint
    assert '"effectiveNaccdmax"' in entrypoint
    assert "WORLDSPEC_A800_CAPACITY_SCALE_RESULT=" in entrypoint


def test_ccd_iterations_probe_is_single_candidate_and_fail_closed() -> None:
    (job,) = _documents("h1-ccd-iterations-probe-job.yaml")
    assert job["metadata"]["namespace"] == "worldspec-a800-poc"
    assert job["metadata"]["labels"]["app.kubernetes.io/name"] == (
        "worldspec-h1-ccd-iterations-probe"
    )
    pod = job["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsUser"] == 10001
    assert pod["securityContext"]["runAsGroup"] == 10001
    (container,) = pod["containers"]
    environment = {item["name"]: item["value"] for item in container["env"]}
    assert environment["WORLD_SPEC_PROBE_MODE"] == "ccd_iterations"
    assert container["image"] == "__RUNTIME_IMAGE__"
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert container["resources"]["requests"]["nvidia.com/gpu"] == "1"
    assert container["resources"]["limits"]["nvidia.com/gpu"] == "1"
    assert all("secret" not in volume for volume in pod["volumes"])
    assert all(
        "persistentVolumeClaim" not in volume
        for volume in pod["volumes"]
    )

    entrypoint = (A800 / "h1-locked-runtime-probe-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    assert '"baselineIterations": 35' in entrypoint
    assert '"candidateIterations": 50' in entrypoint
    assert '"selectionPolicy": "single_predeclared_candidate"' in entrypoint
    assert "rollout_steps = 200" in entrypoint
    assert "WORLDSPEC_A800_CCD_ITERATIONS_RESULT=" in entrypoint

    launcher = (
        ROOT / "scripts" / "run_a800_h1_locked_runtime_probe.sh"
    ).read_text(encoding="utf-8")
    assert '"ccd_iterations, currently set" in line' in launcher
    assert '"needs to be increased" in line' in launcher
    assert 'report["status"] = "passed" if report["logDiagnostics"]["clean"]' in (
        launcher
    )


def test_private_image_is_prepulled_without_mounting_registry_secret() -> None:
    (job,) = _documents("h1-training-image-prepull-job.yaml")
    assert job["metadata"]["namespace"] == "droboticflow"
    pod = job["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["imagePullSecrets"] == [{"name": "droboticflow-registry"}]
    (container,) = pod["containers"]
    assert container["image"] == "__RUNTIME_IMAGE__"
    assert container["imagePullPolicy"] == "Always"
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert "volumes" not in pod


def test_ppo_smoke_is_isolated_and_cannot_claim_canonical_training() -> None:
    (job,) = _documents("h1-ppo-smoke-job.yaml")
    pod = job["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsUser"] == 10001
    assert pod["securityContext"]["runAsGroup"] == 10001
    (container,) = pod["containers"]
    assert container["image"] == "__RUNTIME_IMAGE__"
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert container["resources"]["requests"]["cpu"] == "8"
    assert container["resources"]["requests"]["memory"] == "32Gi"
    assert container["resources"]["limits"]["nvidia.com/gpu"] == "1"
    assert all("secret" not in volume for volume in pod["volumes"])
    assert all("persistentVolumeClaim" not in volume for volume in pod["volumes"])

    entrypoint = (A800 / "h1-ppo-smoke-entrypoint.sh").read_text(encoding="utf-8")
    assert '"runtimeAcceptance": "research_smoke"' in entrypoint
    assert '"policyStatus": "non_publishable"' in entrypoint
    assert '"canonicalTrainingStatus": "not_executed"' in entrypoint
    assert "train_and_evaluate" not in entrypoint
    assert "WORLDSPEC_A800_PPO_SMOKE_RESULT=" in entrypoint


def test_locomotion_calibration_is_isolated_and_research_only() -> None:
    (job,) = _documents("h1-locomotion-calibration-job.yaml")
    assert job["metadata"]["namespace"] == "worldspec-a800-poc"
    assert job["metadata"]["labels"]["app.kubernetes.io/name"] == (
        "worldspec-h1-locomotion-calibration"
    )
    pod = job["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsUser"] == 10001
    assert pod["securityContext"]["runAsGroup"] == 10001
    (container,) = pod["containers"]
    assert container["image"] == "__RUNTIME_IMAGE__"
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert container["resources"]["requests"]["cpu"] == "8"
    assert container["resources"]["requests"]["memory"] == "32Gi"
    assert container["resources"]["limits"]["nvidia.com/gpu"] == "1"
    assert all("secret" not in volume for volume in pod["volumes"])
    assert all(
        "persistentVolumeClaim" not in volume
        for volume in pod["volumes"]
    )

    entrypoint = (
        A800 / "h1-locomotion-calibration-entrypoint.sh"
    ).read_text(encoding="utf-8")
    assert '"runtimeAcceptance": "research_calibration"' in entrypoint
    assert '"policyStatus": "non_publishable"' in entrypoint
    assert '"canonicalTrainingStatus": "not_executed"' in entrypoint
    assert "container digest does not match the executing image" in entrypoint
    assert "WORLDSPEC_A800_CALIBRATION_RESULT=" in entrypoint
    assert "stage artifact_ready" in entrypoint
    assert "launcher did not acknowledge checkpoint retrieval" in entrypoint

    launcher = (
        ROOT / "scripts" / "run_a800_h1_locomotion_calibration.sh"
    ).read_text(encoding="utf-8")
    assert 'current_stage}" == "artifact_ready"' in launcher
    assert "/scratch/results/artifact-copied" in launcher
    assert "copy_kubernetes_file.py" in launcher
    assert "--expected-digest" in launcher
    assert "calibration checkpoint was not retrieved before Pod exit" in launcher
    assert (
        "calibration batchSize times numMinibatches must be divisible by numEnvs"
        in launcher
    )


def test_locomotion_midterm_is_single_gpu_tokenless_and_uses_handshakes() -> None:
    (job,) = _documents("h1-locomotion-midterm-job.yaml")
    assert job["metadata"]["namespace"] == "worldspec-a800-poc"
    assert job["metadata"]["labels"]["app.kubernetes.io/name"] == (
        "worldspec-h1-locomotion-midterm"
    )
    pod = job["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsUser"] == 10001
    assert pod["securityContext"]["runAsGroup"] == 10001
    (container,) = pod["containers"]
    environment = {item["name"]: item["value"] for item in container["env"]}
    assert environment["WORLD_SPEC_MIDTERM_PROFILE_FILENAME"] == (
        "__MIDTERM_PROFILE_FILENAME__"
    )
    assert environment["WORLD_SPEC_WARM_START_REPORT_FILENAME"] == (
        "__WARM_START_REPORT_FILENAME__"
    )
    assert environment["WORLD_SPEC_RETENTION_TEACHER_REPORT_FILENAME"] == (
        "__RETENTION_TEACHER_REPORT_FILENAME__"
    )
    assert container["name"] == "midterm"
    assert container["image"] == "__RUNTIME_IMAGE__"
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert container["resources"]["requests"]["nvidia.com/gpu"] == "1"
    assert container["resources"]["limits"]["nvidia.com/gpu"] == "1"
    assert all("secret" not in volume for volume in pod["volumes"])
    assert all(
        "persistentVolumeClaim" not in volume
        for volume in pod["volumes"]
    )

    entrypoint = (A800 / "h1-locomotion-midterm-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    assert "stage waiting_for_input" in entrypoint
    assert "input-ready" in entrypoint
    assert "stage artifact_ready" in entrypoint
    assert "artifact-copied" in entrypoint
    assert "run_midterm_calibration" in entrypoint
    assert '"policyStatus": "non_publishable"' in entrypoint

    launcher = (
        ROOT / "scripts" / "run_a800_h1_locomotion_midterm.sh"
    ).read_text(encoding="utf-8")
    assert "upload_kubernetes_file.py" in launcher
    assert "copy_kubernetes_file.py" in launcher
    assert "A800_CAPACITY_BLOCKED" in launcher
    assert "formalTrainingGate" in launcher
    assert "/scratch/inputs/stand-teacher-checkpoint.zip" in launcher

    transition_launcher = (
        ROOT / "scripts" / "run_a800_h1_transition_calibration.sh"
    ).read_text(encoding="utf-8")
    assert "WORLD_SPEC_CCD_SPIKE_REPORT" in transition_launcher
    assert 'report.get("status") != "passed"' in transition_launcher
    assert 'report.get("transitionProfileDigest") != profile_digest' in (
        transition_launcher
    )
    assert 'report.get("container", {}).get("image")' in transition_launcher
    assert '"selectionPolicy": "single_predeclared_candidate"' in (
        transition_launcher
    )
    assert 'report.get("logDiagnostics", {}).get("clean") is not True' in (
        transition_launcher
    )
    assert "run_a800_h1_locomotion_midterm.sh" in transition_launcher

    retention_launcher = (
        ROOT / "scripts" / "run_a800_h1_retention_calibration.sh"
    ).read_text(encoding="utf-8")
    assert "locomotion-transition.a800.failed.json" in retention_launcher
    assert "locomotion-calibration.a800.passed.json" in retention_launcher
    assert "WORLD_SPEC_RETENTION_TEACHER_REPORT" in retention_launcher
    assert "WORLD_SPEC_RETENTION_TEACHER_CHECKPOINT" in retention_launcher
    assert "run_a800_h1_locomotion_midterm.sh" in retention_launcher


def test_dual_policy_probe_reuses_isolated_transport_without_training() -> None:
    entrypoint = (A800 / "h1-locomotion-midterm-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    launcher = (
        ROOT / "scripts" / "run_a800_h1_locomotion_midterm.sh"
    ).read_text(encoding="utf-8")
    wrapper = (
        ROOT / "scripts" / "run_a800_h1_dual_policy_probe.sh"
    ).read_text(encoding="utf-8")

    assert 'stage == "dual_policy_switch_probe"' in entrypoint
    assert "run_dual_policy_probe" in entrypoint
    assert "WORLDSPEC_A800_DUAL_POLICY_RESULT=" in entrypoint
    assert '"controllerStatus"' in entrypoint
    assert 'REPORT_SCHEMA=h1-locomotion-dual-policy-report.schema.json' in launcher
    assert 'GATE_FIELD=formalProbeGate' in launcher
    assert "/scratch/results/artifacts/dual-policy-controller.json" in launcher
    assert "locomotion-transition.a800.failed.json" in wrapper
    assert "locomotion-calibration.a800.passed.json" in wrapper
    assert "worldspec-h1-midterm-nxszt/midterm-checkpoint.zip" in wrapper
    assert "worldspec-h1-calibration-4mklr/calibration-checkpoint.zip" in wrapper


def test_capture_calibration_binds_both_policies_and_fails_closed() -> None:
    entrypoint = (A800 / "h1-locomotion-midterm-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    launcher = (ROOT / "scripts" / "run_a800_h1_locomotion_midterm.sh").read_text(
        encoding="utf-8"
    )
    wrapper = (ROOT / "scripts" / "run_a800_h1_capture_calibration.sh").read_text(
        encoding="utf-8"
    )

    assert '"loaded_track_settle_capture"' in entrypoint
    assert "run_capture_calibration" in entrypoint
    assert "WORLDSPEC_A800_CAPTURE_RESULT=" in entrypoint
    assert '"runtimeAcceptance": "research_capture"' in entrypoint
    assert '"capture_candidate"' in entrypoint
    assert "REPORT_SCHEMA=h1-locomotion-capture-report.schema.json" in launcher
    assert "GATE_FIELD=formalCaptureGate" in launcher
    assert "/scratch/results/artifacts/capture-state-bank.npz" in launcher
    assert "locomotion-calibration.a800.passed.json" in wrapper
    assert "locomotion-transition.a800.failed.json" in wrapper
    assert "worldspec-h1-calibration-4mklr/calibration-checkpoint.zip" in wrapper
    assert "worldspec-h1-midterm-nxszt/midterm-checkpoint.zip" in wrapper
    assert "run_a800_h1_locomotion_midterm.sh" in wrapper


def test_locomotion_formal_job_is_single_gpu_tokenless_and_evidence_first() -> None:
    (job,) = _documents("h1-locomotion-formal-job.yaml")
    assert job["metadata"]["namespace"] == "worldspec-a800-poc"
    assert job["metadata"]["labels"]["app.kubernetes.io/name"] == (
        "worldspec-h1-locomotion-formal"
    )
    pod = job["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsUser"] == 10001
    assert pod["securityContext"]["runAsGroup"] == 10001
    (container,) = pod["containers"]
    assert container["name"] == "formal"
    assert container["image"] == "__RUNTIME_IMAGE__"
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert container["resources"]["requests"]["nvidia.com/gpu"] == "1"
    assert container["resources"]["limits"]["nvidia.com/gpu"] == "1"
    assert all("secret" not in volume for volume in pod["volumes"])
    assert all(
        "persistentVolumeClaim" not in volume
        for volume in pod["volumes"]
    )

    entrypoint = (A800 / "h1-locomotion-formal-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    assert "stage waiting_for_input" in entrypoint
    assert "input-ready" in entrypoint
    assert "stage artifact_ready" in entrypoint
    assert "artifact-copied" in entrypoint
    assert "run_training" in entrypoint
    assert '"policy_candidate" if all_passed' in entrypoint

    orchestrator = (
        ROOT / "scripts" / "run_a800_h1_midterm_then_training.sh"
    ).read_text(encoding="utf-8")
    assert "run_a800_h1_locomotion_midterm.sh" in orchestrator
    assert 'formalTrainingGate") != "passed"' in orchestrator
    assert "run_a800_h1_locomotion_formal.py" in orchestrator

    formal_launcher = (
        ROOT / "scripts" / "run_a800_h1_locomotion_formal.py"
    ).read_text(encoding="utf-8")
    assert "CCD_OVERFLOW" in formal_launcher
    assert "CAPACITY_OR_BUFFER_OVERFLOW" in formal_launcher
    assert "ABNORMAL_CONTACT" in formal_launcher
    assert 'result["policyStatus"] = "non_publishable"' in formal_launcher
