#!/usr/bin/env bash
set -Eeuo pipefail

readonly SOURCE_DIR=/scratch/worldspec
readonly SOURCE_CACHE=/scratch/h1-source-cache
readonly BUNDLE_DIR=/scratch/h1-bundle
readonly MODEL_DIR=/scratch/h1-training-model
readonly INPUT_DIR=/scratch/inputs
readonly RESULT_DIR=/scratch/results
readonly ARTIFACT_DIR="${RESULT_DIR}/artifacts"
readonly SOURCE_ARCHIVE=/opt/worldspec-source/worldspec.tar.gz
CURRENT_STAGE=initialization

stage() {
  CURRENT_STAGE="$1"
  printf 'WORLDSPEC_A800_MIDTERM_STAGE=%s\n' "$1"
}

fail() {
  local exit_code=$?
  printf 'WORLDSPEC_A800_MIDTERM_FAILED=%s\n' "${CURRENT_STAGE}"
  exit "${exit_code}"
}

trap fail ERR

for required in \
  WORLD_SPEC_REPOSITORY \
  WORLD_SPEC_PROBE_DEFINITION_REVISION \
  WORLD_SPEC_IMAGE_SOURCE_REVISION \
  WORLD_SPEC_PROBE_INPUT_REVISION \
  WORLD_SPEC_RUNTIME_IMAGE \
  WORLD_SPEC_PACKAGE_LOCK_DIGEST \
  WORLD_SPEC_SOURCE_ARCHIVE_DIGEST \
  WORLD_SPEC_MIDTERM_PROFILE_FILENAME \
  WORLD_SPEC_WARM_START_REPORT_FILENAME; do
  if [[ -z "${!required:-}" ]]; then
    printf 'ERROR: %s is required\n' "${required}" >&2
    exit 2
  fi
done

mkdir -p \
  "${HOME}" \
  "${XDG_CACHE_HOME}" \
  "${TMPDIR}" \
  "${SOURCE_DIR}" \
  "${MODEL_DIR}" \
  "${INPUT_DIR}" \
  "${RESULT_DIR}" \
  "${ARTIFACT_DIR}"

stage security_and_gpu_inventory
if [[ "$(id -u)" != "10001" ]] || [[ "$(id -g)" != "10001" ]]; then
  echo "ERROR: midterm did not start as uid/gid 10001" >&2
  exit 1
fi
if touch /worldspec-root-write-test 2>/dev/null; then
  rm -f /worldspec-root-write-test
  echo "ERROR: root filesystem is writable" >&2
  exit 1
fi
nvidia-smi --query-gpu=name,driver_version,memory.total \
  --format=csv,noheader,nounits >"${RESULT_DIR}/gpu.csv"

stage source_verification
python - "${SOURCE_ARCHIVE}" "${WORLD_SPEC_SOURCE_ARCHIVE_DIGEST}" <<'PY'
import hashlib
import pathlib
import sys

archive = pathlib.Path(sys.argv[1])
actual = f"sha256:{hashlib.sha256(archive.read_bytes()).hexdigest()}"
if actual != sys.argv[2]:
    raise SystemExit(f"source archive digest mismatch: expected={sys.argv[2]} actual={actual}")
PY
tar -xzf "${SOURCE_ARCHIVE}" -C "${SOURCE_DIR}"
python - \
  "${SOURCE_DIR}/python/worldspec-h1-training/uv.lock" \
  "${WORLD_SPEC_PACKAGE_LOCK_DIGEST}" <<'PY'
import hashlib
import pathlib
import sys

actual = f"sha256:{hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()}"
if actual != sys.argv[2]:
    raise SystemExit(f"package lock mismatch: expected={sys.argv[2]} actual={actual}")
PY

stage waiting_for_input
for ((attempt = 0; attempt < 1800; attempt++)); do
  if [[ -f "${INPUT_DIR}/input-ready" ]]; then
    break
  fi
  sleep 1
done
if [[ ! -f "${INPUT_DIR}/input-ready" ]]; then
  echo "ERROR: launcher did not provide midterm inputs" >&2
  exit 1
fi

stage input_verification
python - \
  "${SOURCE_DIR}/examples/h1-kitchen/${WORLD_SPEC_MIDTERM_PROFILE_FILENAME}" \
  "${SOURCE_DIR}/examples/h1-kitchen/${WORLD_SPEC_WARM_START_REPORT_FILENAME}" \
  "${INPUT_DIR}/stand-report.json" \
  "${INPUT_DIR}/stand-checkpoint.zip" \
  "${WORLD_SPEC_RUNTIME_IMAGE}" \
  "${WORLD_SPEC_PACKAGE_LOCK_DIGEST}" \
  "${SOURCE_DIR}" \
  "${WORLD_SPEC_RETENTION_TEACHER_REPORT_FILENAME:-}" \
  "${INPUT_DIR}/stand-teacher-report.json" \
  "${INPUT_DIR}/stand-teacher-checkpoint.zip" \
  "${WORLD_SPEC_SUPERVISOR_STAND_REPORT_FILENAME:-}" \
  "${INPUT_DIR}/supervisor-stand-report.json" \
  "${INPUT_DIR}/supervisor-stand-checkpoint.zip" <<'PY'
import hashlib
import json
import pathlib
import sys

profile = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
stage = profile["stage"]
checked_report_path = pathlib.Path(sys.argv[2])
input_report_path = pathlib.Path(sys.argv[3])
checkpoint_path = pathlib.Path(sys.argv[4])
checked_report = checked_report_path.read_bytes()
input_report = input_report_path.read_bytes()
if input_report != checked_report:
    raise SystemExit("uploaded warm-start report differs from the repository-bound report")
source = (
    profile["motionPolicy"]
    if stage in {
        "dual_policy_switch_probe",
        "phase_aware_supervisor_probe",
        "fixed_kitchen_full_loop_probe",
        "whole_body_task_space_control_spike",
    }
    else profile["warmStart"]
)
report_digest = f"sha256:{hashlib.sha256(input_report).hexdigest()}"
checkpoint_payload = checkpoint_path.read_bytes()
checkpoint_digest = f"sha256:{hashlib.sha256(checkpoint_payload).hexdigest()}"
if report_digest != source["sourceReportDigest"]:
    raise SystemExit("warm-start report digest mismatch")
if (
    checkpoint_digest != source["checkpointDigest"]
    or len(checkpoint_payload) != source["checkpointSizeBytes"]
):
    raise SystemExit("warm-start checkpoint digest or size mismatch")
report = json.loads(input_report)
if source["sourceStage"] == "stand-v2.1":
    if report["qualityAssessment"]["status"] != "passed":
        raise SystemExit("stand source report is not passing")
elif source["sourceStage"] == "loaded-track-settle-v1-failed":
    if (
        report["qualityAssessment"]["status"] != "failed"
        or report["formalTrainingGate"] != "failed"
        or report["policyStatus"] != "non_publishable"
    ):
        raise SystemExit("transition source report is not the frozen failed evidence")
elif source["sourceStage"] == "loaded-track-settle-transition-v2-failed":
    if (
        report["qualityAssessment"]["status"] != "failed"
        or report["formalTrainingGate"] != "failed"
        or report["policyStatus"] != "non_publishable"
        or report["training"]["profileStage"] != "loaded_track_settle_transition"
    ):
        raise SystemExit("retention source report is not the frozen failed evidence")
else:
    raise SystemExit("unsupported warm-start source stage")
if report["researchCheckpoint"]["digest"] != checkpoint_digest:
    raise SystemExit("warm-start report/checkpoint lineage mismatch")
if profile["runtime"]["containerImage"] != sys.argv[5]:
    raise SystemExit("midterm Profile container image mismatch")
if profile["runtime"]["packageLockDigest"] != sys.argv[6]:
    raise SystemExit("midterm Profile package lock mismatch")
if stage in {
    "loaded_track_settle_retention",
    "dual_policy_switch_probe",
    "loaded_track_settle_capture",
    "phase_aware_supervisor_probe",
    "fixed_kitchen_full_loop_probe",
    "whole_body_task_space_control_spike",
}:
    teacher = (
        profile["standPolicy"]
        if stage == "dual_policy_switch_probe"
        else (
            profile["capturePolicy"]
            if stage in {
                "phase_aware_supervisor_probe",
                "fixed_kitchen_full_loop_probe",
                "whole_body_task_space_control_spike",
            }
            else (
                profile["motionTeacher"]
                if stage == "loaded_track_settle_capture"
                else profile["retentionTeacher"]
            )
        )
    )
    teacher_filename = sys.argv[8]
    if not teacher_filename:
        raise SystemExit("retention teacher report filename is missing")
    teacher_checked_path = (
        pathlib.Path(sys.argv[7])
        / "examples"
        / "h1-kitchen"
        / teacher_filename
    )
    teacher_input_report_path = pathlib.Path(sys.argv[9])
    teacher_checkpoint_path = pathlib.Path(sys.argv[10])
    teacher_checked = teacher_checked_path.read_bytes()
    teacher_input_report = teacher_input_report_path.read_bytes()
    if teacher_input_report != teacher_checked:
        raise SystemExit("uploaded retention teacher report differs from repository evidence")
    teacher_report_digest = (
        f"sha256:{hashlib.sha256(teacher_input_report).hexdigest()}"
    )
    teacher_checkpoint = teacher_checkpoint_path.read_bytes()
    teacher_checkpoint_digest = (
        f"sha256:{hashlib.sha256(teacher_checkpoint).hexdigest()}"
    )
    if teacher_report_digest != teacher["sourceReportDigest"]:
        raise SystemExit("retention teacher report digest mismatch")
    if (
        teacher_checkpoint_digest != teacher["checkpointDigest"]
        or len(teacher_checkpoint) != teacher["checkpointSizeBytes"]
    ):
        raise SystemExit("retention teacher checkpoint identity mismatch")
    teacher_report = json.loads(teacher_input_report)
    if teacher_report["researchCheckpoint"]["digest"] != teacher_checkpoint_digest:
        raise SystemExit("auxiliary policy report/checkpoint lineage mismatch")
    if teacher["sourceStage"] == "stand-v2.1":
        if teacher_report["qualityAssessment"]["status"] != "passed":
            raise SystemExit("stand teacher evidence is not passing")
    elif teacher["sourceStage"] == "loaded-track-settle-transition-v2-failed":
        if (
            teacher_report["qualityAssessment"]["status"] != "failed"
            or teacher_report["formalTrainingGate"] != "failed"
            or teacher_report["policyStatus"] != "non_publishable"
            or teacher_report["training"]["profileStage"]
            != "loaded_track_settle_transition"
        ):
            raise SystemExit("motion teacher is not the frozen transition-v2 evidence")
    elif teacher["sourceStage"] == "loaded-track-settle-capture-v1-passed":
        if (
            teacher_report["qualityAssessment"]["status"] != "passed"
            or teacher_report["formalCaptureGate"] != "passed"
            or teacher_report["policyStatus"] != "capture_candidate"
        ):
            raise SystemExit("capture policy is not the frozen passing A3 evidence")
    else:
        raise SystemExit("unsupported auxiliary policy source stage")
if stage in {
    "phase_aware_supervisor_probe",
    "fixed_kitchen_full_loop_probe",
    "whole_body_task_space_control_spike",
}:
    stand = profile["standPolicy"]
    stand_filename = sys.argv[11]
    if not stand_filename:
        raise SystemExit("supervisor stand report filename is missing")
    checked_stand_path = (
        pathlib.Path(sys.argv[7])
        / "examples"
        / "h1-kitchen"
        / stand_filename
    )
    input_stand_report_path = pathlib.Path(sys.argv[12])
    stand_checkpoint_path = pathlib.Path(sys.argv[13])
    checked_stand = checked_stand_path.read_bytes()
    input_stand_report = input_stand_report_path.read_bytes()
    if input_stand_report != checked_stand:
        raise SystemExit("uploaded supervisor stand report differs from repository evidence")
    stand_report_digest = f"sha256:{hashlib.sha256(input_stand_report).hexdigest()}"
    stand_checkpoint = stand_checkpoint_path.read_bytes()
    stand_checkpoint_digest = f"sha256:{hashlib.sha256(stand_checkpoint).hexdigest()}"
    if stand_report_digest != stand["sourceReportDigest"]:
        raise SystemExit("supervisor stand report digest mismatch")
    if (
        stand_checkpoint_digest != stand["checkpointDigest"]
        or len(stand_checkpoint) != stand["checkpointSizeBytes"]
    ):
        raise SystemExit("supervisor stand checkpoint identity mismatch")
    stand_report = json.loads(input_stand_report)
    if (
        stand_report["qualityAssessment"]["status"] != "passed"
        or stand_report["researchCheckpoint"]["digest"] != stand_checkpoint_digest
    ):
        raise SystemExit("supervisor stand policy lineage is not passing")
if stage == "whole_body_task_space_control_spike":
    a5r_path = (
        pathlib.Path(sys.argv[7])
        / "examples"
        / "h1-kitchen"
        / "kitchen-task.a5r.a800.failed.json"
    )
    a5r_digest = f"sha256:{hashlib.sha256(a5r_path.read_bytes()).hexdigest()}"
    if a5r_digest != profile["failedA5RReportDigest"]:
        raise SystemExit("whole-body Spike A5-R failure lineage mismatch")
PY

stage installed_runtime
python - <<'PY'
import importlib.metadata as metadata

expected = {
    "brax": "0.14.2",
    "flax": "0.11.2",
    "jax": "0.6.2",
    "jaxlib": "0.6.2",
    "jsonschema": "4.26.0",
    "mujoco": "3.6.0",
    "mujoco-mjx": "3.6.0",
    "orbax-checkpoint": "0.11.31",
    "playground": "0.2.0",
    "warp-lang": "1.11.0",
    "worldspec-h1-training": "0.1.0",
    "worldspec-worker": "0.1.0",
}
actual = {name: metadata.version(name) for name in expected}
if actual != expected:
    raise SystemExit(f"installed package mismatch: expected={expected!r} actual={actual!r}")
PY

stage source_materialization
python "${SOURCE_DIR}/scripts/fetch_h1_kitchen_sources.py" \
  --output "${SOURCE_CACHE}"

stage target_composition
python "${SOURCE_DIR}/scripts/compose_h1_robotiq.py" \
  --cache "${SOURCE_CACHE}" \
  --output "${BUNDLE_DIR}"

stage loaded_track_settle
env \
  SOURCE_DIR="${SOURCE_DIR}" \
  BUNDLE_DIR="${BUNDLE_DIR}" \
  MODEL_DIR="${MODEL_DIR}" \
  INPUT_DIR="${INPUT_DIR}" \
  RESULT_DIR="${RESULT_DIR}" \
  ARTIFACT_DIR="${ARTIFACT_DIR}" \
  python - <<'PY'
from __future__ import annotations

import csv
import importlib.metadata
import json
import os
import platform
from datetime import datetime, timezone
from pathlib import Path

import jax

from worldspec_h1_training.contract import read_json
from worldspec_h1_training.capture import run_capture_calibration
from worldspec_h1_training.dual_policy import run_dual_policy_probe
from worldspec_h1_training.kitchen_task import run_fixed_kitchen_task_probe
from worldspec_h1_training.midterm import run_midterm_calibration
from worldspec_h1_training.supervisor import run_phase_aware_supervisor_probe
from worldspec_h1_training.whole_body import run_whole_body_control_spike

source_dir = Path(os.environ["SOURCE_DIR"])
result_dir = Path(os.environ["RESULT_DIR"])
artifact_dir = Path(os.environ["ARTIFACT_DIR"])
base_profile = read_json(
    source_dir / "examples" / "h1-kitchen" / "locomotion-training-profile.json"
)
midterm_profile = read_json(
    source_dir
    / "examples"
    / "h1-kitchen"
    / os.environ["WORLD_SPEC_MIDTERM_PROFILE_FILENAME"]
)
if midterm_profile["stage"] == "dual_policy_switch_probe":
    result = run_dual_policy_probe(
        base_profile,
        midterm_profile,
        Path(os.environ["BUNDLE_DIR"]),
        Path(os.environ["MODEL_DIR"]),
        artifact_dir,
        Path(os.environ["INPUT_DIR"]) / "stand-checkpoint.zip",
        Path(os.environ["INPUT_DIR"]) / "stand-teacher-checkpoint.zip",
    )
elif midterm_profile["stage"] == "loaded_track_settle_capture":
    result = run_capture_calibration(
        base_profile,
        midterm_profile,
        Path(os.environ["BUNDLE_DIR"]),
        Path(os.environ["MODEL_DIR"]),
        artifact_dir,
        Path(os.environ["INPUT_DIR"]) / "stand-checkpoint.zip",
        Path(os.environ["INPUT_DIR"]) / "stand-teacher-checkpoint.zip",
    )
elif midterm_profile["stage"] == "phase_aware_supervisor_probe":
    result = run_phase_aware_supervisor_probe(
        base_profile,
        midterm_profile,
        Path(os.environ["BUNDLE_DIR"]),
        Path(os.environ["MODEL_DIR"]),
        artifact_dir,
        Path(os.environ["INPUT_DIR"]) / "stand-checkpoint.zip",
        Path(os.environ["INPUT_DIR"]) / "stand-teacher-checkpoint.zip",
        Path(os.environ["INPUT_DIR"]) / "supervisor-stand-checkpoint.zip",
    )
elif midterm_profile["stage"] == "fixed_kitchen_full_loop_probe":
    supervisor_profile = read_json(
        source_dir
        / "examples"
        / "h1-kitchen"
        / "locomotion-supervisor-profile.json"
    )
    result = run_fixed_kitchen_task_probe(
        base_profile,
        supervisor_profile,
        midterm_profile,
        Path(os.environ["BUNDLE_DIR"]),
        Path(os.environ["MODEL_DIR"]),
        artifact_dir,
        Path(os.environ["INPUT_DIR"]) / "stand-checkpoint.zip",
        Path(os.environ["INPUT_DIR"]) / "stand-teacher-checkpoint.zip",
        Path(os.environ["INPUT_DIR"]) / "supervisor-stand-checkpoint.zip",
    )
elif midterm_profile["stage"] == "whole_body_task_space_control_spike":
    supervisor_profile = read_json(
        source_dir
        / "examples"
        / "h1-kitchen"
        / "locomotion-supervisor-profile.json"
    )
    result = run_whole_body_control_spike(
        base_profile,
        supervisor_profile,
        midterm_profile,
        Path(os.environ["BUNDLE_DIR"]),
        Path(os.environ["MODEL_DIR"]),
        artifact_dir,
        Path(os.environ["INPUT_DIR"]) / "stand-checkpoint.zip",
        Path(os.environ["INPUT_DIR"]) / "stand-teacher-checkpoint.zip",
        Path(os.environ["INPUT_DIR"]) / "supervisor-stand-checkpoint.zip",
    )
else:
    result = run_midterm_calibration(
        base_profile,
        midterm_profile,
        Path(os.environ["BUNDLE_DIR"]),
        Path(os.environ["MODEL_DIR"]),
        artifact_dir,
        Path(os.environ["INPUT_DIR"]) / "stand-checkpoint.zip",
        (
            Path(os.environ["INPUT_DIR"]) / "stand-teacher-checkpoint.zip"
            if midterm_profile["stage"] == "loaded_track_settle_retention"
            else None
        ),
    )
    result["training"]["profileStage"] = midterm_profile["stage"]
with (result_dir / "gpu.csv").open(encoding="utf-8") as stream:
    gpu_row = next(csv.reader(stream))
package_names = (
    "brax",
    "flax",
    "jax",
    "jaxlib",
    "jsonschema",
    "mujoco",
    "mujoco-mjx",
    "orbax-checkpoint",
    "playground",
    "warp-lang",
    "worldspec-h1-training",
    "worldspec-worker",
)
common = {
    "probeDefinition": {
        "repository": os.environ["WORLD_SPEC_REPOSITORY"],
        "commit": os.environ["WORLD_SPEC_PROBE_DEFINITION_REVISION"],
    },
    "imageSource": {
        "repository": os.environ["WORLD_SPEC_REPOSITORY"],
        "commit": os.environ["WORLD_SPEC_IMAGE_SOURCE_REVISION"],
    },
    "probeInput": {
        "repository": os.environ["WORLD_SPEC_REPOSITORY"],
        "commit": os.environ["WORLD_SPEC_PROBE_INPUT_REVISION"],
        "materialization": "verified_git_archive",
        "archiveDigest": os.environ["WORLD_SPEC_SOURCE_ARCHIVE_DIGEST"],
    },
    "container": {
        "image": os.environ["WORLD_SPEC_RUNTIME_IMAGE"],
        "runAsUser": 10001,
        "runAsGroup": 10001,
        "readOnlyRootFilesystem": True,
        "serviceAccountTokenMounted": False,
        "secretMountCount": 0,
    },
    "platform": {
        "system": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    },
    "gpu": {
        "name": gpu_row[0].strip(),
        "driverVersion": gpu_row[1].strip(),
        "memoryMiB": int(gpu_row[2].strip()),
        "jaxBackend": jax.default_backend(),
        "jaxDevices": [str(device) for device in jax.devices()],
    },
    "packages": {name: importlib.metadata.version(name) for name in package_names},
    "packageLockDigest": os.environ["WORLD_SPEC_PACKAGE_LOCK_DIGEST"],
    **result,
    "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
}
if midterm_profile["stage"] == "dual_policy_switch_probe":
    report = {
        "id": (
            "dual-policy-report://worldspec/h1/a800-"
            + os.environ["WORLD_SPEC_PROBE_INPUT_REVISION"][:12]
        ),
        "reportVersion": "0.1.0",
        "status": "completed",
        "scope": "h1_dual_policy_switch_probe",
        "executionEvidence": "executed",
        "runtimeAcceptance": "research_probe",
        "controllerStatus": (
            "candidate"
            if result["qualityAssessment"]["status"] == "passed"
            else "non_publishable"
        ),
        "formalProbeGate": (
            "passed"
            if result["qualityAssessment"]["status"] == "passed"
            else "failed"
        ),
        **common,
    }
    print(
        "WORLDSPEC_A800_DUAL_POLICY_RESULT="
        + json.dumps(report, separators=(",", ":"))
    )
elif midterm_profile["stage"] == "loaded_track_settle_capture":
    report = {
        "id": (
            "capture-report://worldspec/h1/a800-"
            + os.environ["WORLD_SPEC_PROBE_INPUT_REVISION"][:12]
        ),
        "reportVersion": "0.1.0",
        "status": "completed",
        "scope": "h1_motion_state_capture_calibration",
        "executionEvidence": "executed",
        "runtimeAcceptance": "research_capture",
        "policyStatus": (
            "capture_candidate"
            if result["qualityAssessment"]["status"] == "passed"
            else "non_publishable"
        ),
        "formalCaptureGate": (
            "passed"
            if result["qualityAssessment"]["status"] == "passed"
            else "failed"
        ),
        **common,
    }
    print(
        "WORLDSPEC_A800_CAPTURE_RESULT="
        + json.dumps(report, separators=(",", ":"))
    )
elif midterm_profile["stage"] == "phase_aware_supervisor_probe":
    report = {
        "id": (
            "supervisor-report://worldspec/h1/a800-"
            + os.environ["WORLD_SPEC_PROBE_INPUT_REVISION"][:12]
        ),
        "reportVersion": "0.1.0",
        "status": "completed",
        "scope": "h1_phase_aware_supervisor_probe",
        "executionEvidence": "executed",
        "runtimeAcceptance": "research_supervisor",
        "controllerStatus": (
            "supervisor_candidate"
            if result["qualityAssessment"]["status"] == "passed"
            else "non_publishable"
        ),
        "formalSupervisorGate": (
            "passed"
            if result["qualityAssessment"]["status"] == "passed"
            else "failed"
        ),
        **common,
    }
    print(
        "WORLDSPEC_A800_SUPERVISOR_RESULT="
        + json.dumps(report, separators=(",", ":"))
    )
elif midterm_profile["stage"] == "fixed_kitchen_full_loop_probe":
    report = {
        "id": (
            "kitchen-task-report://worldspec/h1/a800-"
            + os.environ["WORLD_SPEC_PROBE_INPUT_REVISION"][:12]
        ),
        "reportVersion": "0.1.0",
        "status": "completed",
        "scope": "h1_fixed_kitchen_full_loop_probe",
        "executionEvidence": "executed",
        "runtimeAcceptance": "research_integration",
        "controllerStatus": (
            "integration_candidate"
            if result["qualityAssessment"]["status"] == "passed"
            else "non_publishable"
        ),
        "formalTaskGate": (
            "passed"
            if result["qualityAssessment"]["status"] == "passed"
            else "failed"
        ),
        **common,
    }
    print(
        "WORLDSPEC_A800_KITCHEN_TASK_RESULT="
        + json.dumps(report, separators=(",", ":"))
    )
elif midterm_profile["stage"] == "whole_body_task_space_control_spike":
    report = {
        "id": (
            "whole-body-control-report://worldspec/h1/a800-"
            + os.environ["WORLD_SPEC_PROBE_INPUT_REVISION"][:12]
        ),
        "reportVersion": "0.1.0",
        "status": "completed",
        "scope": "h1_whole_body_task_space_control_spike",
        "executionEvidence": "executed",
        "runtimeAcceptance": "research_control_spike",
        "controllerStatus": (
            "control_candidate"
            if result["qualityAssessment"]["status"] == "passed"
            else "non_publishable"
        ),
        "formalControlGate": (
            "passed"
            if result["qualityAssessment"]["status"] == "passed"
            else "failed"
        ),
        **common,
    }
    print(
        "WORLDSPEC_A800_WHOLE_BODY_RESULT="
        + json.dumps(report, separators=(",", ":"))
    )
else:
    report = {
        "id": (
            "midterm-report://worldspec/h1-loaded-track-settle/a800-"
            + os.environ["WORLD_SPEC_PROBE_INPUT_REVISION"][:12]
        ),
        "reportVersion": "0.1.0",
        "status": "completed",
        "scope": "h1_loaded_track_settle_midterm",
        "executionEvidence": "executed",
        "runtimeAcceptance": "research_midterm",
        "policyStatus": "non_publishable",
        "formalTrainingGate": (
            "passed"
            if result["qualityAssessment"]["status"] == "passed"
            else "failed"
        ),
        **common,
    }
    print("WORLDSPEC_A800_MIDTERM_RESULT=" + json.dumps(report, separators=(",", ":")))
PY

stage artifact_ready
for ((attempt = 0; attempt < 3600; attempt++)); do
  if [[ -f "${RESULT_DIR}/artifact-copied" ]]; then
    break
  fi
  sleep 1
done
if [[ ! -f "${RESULT_DIR}/artifact-copied" ]]; then
  echo "ERROR: launcher did not acknowledge midterm artifact retrieval" >&2
  exit 1
fi

stage completed
