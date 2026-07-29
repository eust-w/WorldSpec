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
  local failed_stage="${CURRENT_STAGE}"
  trap - ERR
  set +e
  printf 'WORLDSPEC_A800_MIDTERM_FAILED=%s\n' "${CURRENT_STAGE}"
  if [[ -n "${WORLD_SPEC_DIAGNOSTIC_REPLAY_PROFILE_FILENAME:-}" ]] &&
    [[ -d "${RESULT_DIR}" ]] &&
    [[ -d "${ARTIFACT_DIR}" ]]; then
    python - \
      "${RESULT_DIR}/diagnostic-failure.json" \
      "${SOURCE_DIR}/examples/h1-kitchen/${WORLD_SPEC_DIAGNOSTIC_REPLAY_PROFILE_FILENAME}" \
      "${ARTIFACT_DIR}" \
      "${failed_stage}" \
      "${exit_code}" <<'PY'
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone

output_path = pathlib.Path(sys.argv[1])
profile_path = pathlib.Path(sys.argv[2])
artifact_dir = pathlib.Path(sys.argv[3])
allowed_artifacts = (
    "whole-body-controller.json",
    "evaluation-traces.jsonl",
    "equivalence-report.json",
)
artifacts = {}
for name in allowed_artifacts:
    path = artifact_dir / name
    if not path.is_file():
        continue
    payload = path.read_bytes()
    artifacts[name] = {
        "digest": f"sha256:{hashlib.sha256(payload).hexdigest()}",
        "sizeBytes": len(payload),
    }
attempt_id = "unknown"
if profile_path.is_file():
    try:
        attempt_id = json.loads(profile_path.read_text(encoding="utf-8"))["attemptId"]
    except (KeyError, TypeError, ValueError):
        pass
failure = {
    "failureVersion": "0.1.0",
    "status": "failed",
    "attemptId": attempt_id,
    "stage": sys.argv[4],
    "exitCode": int(sys.argv[5]),
    "artifacts": artifacts,
    "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
}
payload = json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
output_path.write_text(payload, encoding="utf-8")
print(
    "WORLDSPEC_A800_WHOLE_BODY_DIAGNOSTIC_FAILURE="
    + json.dumps(failure, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
)
PY
    stage artifact_failure_ready
    for ((attempt = 0; attempt < 1800; attempt++)); do
      if [[ -f "${RESULT_DIR}/artifact-copied" ]]; then
        break
      fi
      sleep 1
    done
    if [[ ! -f "${RESULT_DIR}/artifact-copied" ]]; then
      echo "ERROR: launcher did not acknowledge diagnostic failure artifacts" >&2
    fi
  fi
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
  "${INPUT_DIR}/supervisor-stand-checkpoint.zip" \
  "${WORLD_SPEC_DIAGNOSTIC_REPLAY_PROFILE_FILENAME:-}" \
  "${INPUT_DIR}/a5c-baseline-summary.json" \
  "${INPUT_DIR}/a5c-baseline-report.json" \
  "${INPUT_DIR}/a5c-baseline-controller.json" \
  "${INPUT_DIR}/a5c-baseline-trace.jsonl" \
  "${WORLD_SPEC_IMAGE_SOURCE_REVISION}" <<'PY'
import copy
import hashlib
import json
import pathlib
import sys


def digest_bytes(payload):
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def digest_json(value):
    return digest_bytes(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )

profile = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
stage = profile["stage"]
replay_filename = sys.argv[14]
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
if not replay_filename and profile["runtime"]["containerImage"] != sys.argv[5]:
    raise SystemExit("midterm Profile container image mismatch")
if not replay_filename and profile["runtime"]["packageLockDigest"] != sys.argv[6]:
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

if replay_filename:
    if stage != "whole_body_task_space_control_spike":
        raise SystemExit("diagnostic replay must wrap the frozen whole-body control stage")
    replay_path = pathlib.Path(sys.argv[7]) / "examples" / "h1-kitchen" / replay_filename
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    if replay["stage"] != "whole_body_task_space_control_diagnostic_replay":
        raise SystemExit("diagnostic replay stage mismatch")
    if digest_json(profile) != replay["baseControlProfileDigest"]:
        raise SystemExit("diagnostic replay base control Profile digest mismatch")
    semantic_profile = copy.deepcopy(profile)
    semantic_profile["runtime"].pop("containerImage")
    semantic_profile["runtime"].pop("containerDigest")
    if digest_json(semantic_profile) != replay["semanticProfileProjectionDigest"]:
        raise SystemExit("diagnostic replay semantic Profile projection mismatch")
    evidence_paths = {
        "summary": pathlib.Path(sys.argv[15]),
        "report": pathlib.Path(sys.argv[16]),
        "controller": pathlib.Path(sys.argv[17]),
        "trace": pathlib.Path(sys.argv[18]),
    }
    for name, evidence_path in evidence_paths.items():
        payload = evidence_path.read_bytes()
        expected = replay["baselineEvidence"][name]
        if digest_bytes(payload) != expected["digest"] or len(payload) != expected["sizeBytes"]:
            raise SystemExit(f"diagnostic replay baseline {name} identity mismatch")
    trace_records = [
        line
        for line in evidence_paths["trace"].read_text(encoding="utf-8").splitlines()
        if line
    ]
    if len(trace_records) != replay["baselineEvidence"]["trace"]["recordCount"]:
        raise SystemExit("diagnostic replay baseline trace record count mismatch")
    controller = json.loads(evidence_paths["controller"].read_text(encoding="utf-8"))
    if "profileDigest" not in controller:
        raise SystemExit("diagnostic replay baseline controller lacks profileDigest")
    controller.pop("profileDigest")
    if digest_json(controller) != replay["controllerSemanticProjectionDigest"]:
        raise SystemExit("diagnostic replay baseline controller projection mismatch")
    baseline_report = json.loads(evidence_paths["report"].read_text(encoding="utf-8"))
    bindings = replay["baselineBindings"]
    if (
        bindings["seed"] != profile["seed"]
        or bindings["probeRevision"] != baseline_report["probeDefinition"]["commit"]
        or bindings["imageSourceRevision"] != baseline_report["imageSource"]["commit"]
        or bindings["containerImage"] != baseline_report["container"]["image"]
        or bindings["containerDigest"]
        != baseline_report["container"]["image"].rsplit("@", 1)[1]
        or bindings["packageLockDigest"] != baseline_report["packageLockDigest"]
        or bindings["target"] != baseline_report["target"]
    ):
        raise SystemExit("diagnostic replay baseline binding mismatch")
    for role in ("motion", "capture", "stand"):
        source = baseline_report["policies"][role]
        expected = bindings["policies"][role]
        if (
            expected["checkpointDigest"] != source["archiveDigest"]
            or expected["checkpointSizeBytes"] != source["archiveSizeBytes"]
        ):
            raise SystemExit(
                f"diagnostic replay baseline {role} policy binding mismatch"
            )
    runtime = replay["runtime"]
    if (
        runtime["containerImage"] != sys.argv[5]
        or runtime["containerDigest"] != sys.argv[5].rsplit("@", 1)[1]
        or runtime["packageLockDigest"] != sys.argv[6]
        or runtime["imageSourceRevision"] != sys.argv[19]
    ):
        raise SystemExit("diagnostic replay runtime binding mismatch")
    if replay["allowedChanges"] != [
        "diagnostic_instrumentation",
        "source_archive_digest",
        "container_image",
    ]:
        raise SystemExit("diagnostic replay allowed-change set mismatch")
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

from worldspec_h1_training.contract import (
    canonical_bytes,
    digest_bytes,
    digest_json,
    read_json,
)
from worldspec_h1_training.capture import run_capture_calibration
from worldspec_h1_training.dual_policy import run_dual_policy_probe
from worldspec_h1_training.kitchen_task import run_fixed_kitchen_task_probe
from worldspec_h1_training.midterm import run_midterm_calibration
from worldspec_h1_training.supervisor import run_phase_aware_supervisor_probe
from worldspec_h1_training.whole_body import (
    assess_diagnostic_trace,
    compare_whole_body_traces,
    make_whole_body_evaluation_profile,
    run_whole_body_control_spike,
    whole_body_controller_semantic_projection,
    whole_body_profile_semantic_projection,
)

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
diagnostic_replay_filename = os.environ.get(
    "WORLD_SPEC_DIAGNOSTIC_REPLAY_PROFILE_FILENAME", ""
)
diagnostic_replay_profile = (
    read_json(
        source_dir
        / "examples"
        / "h1-kitchen"
        / diagnostic_replay_filename
    )
    if diagnostic_replay_filename
    else None
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
    whole_body_effective_profile = make_whole_body_evaluation_profile(
        base_profile,
        supervisor_profile,
        midterm_profile,
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

diagnostic_replay = None
if diagnostic_replay_profile is not None:
    if midterm_profile["stage"] != "whole_body_task_space_control_spike":
        raise RuntimeError("diagnostic replay requires the frozen whole-body stage")

    def read_jsonl(path: Path) -> list[dict]:
        records = []
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise RuntimeError(
                        f"trace line {line_number} is not a JSON object"
                    )
                records.append(record)
        return records

    baseline_trace = read_jsonl(
        Path(os.environ["INPUT_DIR"]) / "a5c-baseline-trace.jsonl"
    )
    replay_trace_path = artifact_dir / "evaluation-traces.jsonl"
    replay_trace = read_jsonl(replay_trace_path)
    diagnostic_completeness = assess_diagnostic_trace(
        replay_trace,
        whole_body_effective_profile["control"],
    )
    dynamic_comparison = compare_whole_body_traces(
        baseline_trace,
        replay_trace,
    )
    replay_controller_path = artifact_dir / "whole-body-controller.json"
    replay_controller = read_json(replay_controller_path)
    profile_projection_digest = digest_json(
        whole_body_profile_semantic_projection(midterm_profile)
    )
    controller_projection_digest = digest_json(
        whole_body_controller_semantic_projection(replay_controller)
    )
    target_expected = diagnostic_replay_profile["baselineBindings"]["target"]
    target_actual = result["target"]
    baseline_bindings = diagnostic_replay_profile["baselineBindings"]
    profile_projection_matches = (
        profile_projection_digest
        == diagnostic_replay_profile["semanticProfileProjectionDigest"]
    )
    controller_projection_matches = (
        controller_projection_digest
        == diagnostic_replay_profile["controllerSemanticProjectionDigest"]
    )
    static_checks = {
        "baseControlProfileDigest": (
            digest_json(midterm_profile)
            == diagnostic_replay_profile["baseControlProfileDigest"]
        ),
        "semanticProfileProjectionDigest": profile_projection_matches,
        "controllerSemanticProjectionDigest": controller_projection_matches,
        "sourceBundleDigest": (
            target_actual["sourceBundleDigest"]
            == target_expected["sourceBundleDigest"]
        ),
        "derivedModelDigest": (
            target_actual["derivedModelDigest"]
            == target_expected["derivedModelDigest"]
        ),
        "observationSize": (
            target_actual["observationSize"]
            == target_expected["observationSize"]
        ),
        "actionSize": (
            target_actual["actionSize"] == target_expected["actionSize"]
        ),
    }
    policy_checks = {
        role: (
            midterm_profile[f"{role}Policy"]["checkpointDigest"]
            == baseline_bindings["policies"][role]["checkpointDigest"]
            and midterm_profile[f"{role}Policy"]["checkpointSizeBytes"]
            == baseline_bindings["policies"][role]["checkpointSizeBytes"]
        )
        for role in ("motion", "capture", "stand")
    }
    binding_checks = {
        "seed": midterm_profile["seed"] == baseline_bindings["seed"],
        "scene": static_checks["baseControlProfileDigest"],
        "controller": (
            static_checks["baseControlProfileDigest"]
            and controller_projection_matches
        ),
        "qualityGates": static_checks["baseControlProfileDigest"],
        "mjxCapacity": static_checks["baseControlProfileDigest"],
        "sourceBundle": static_checks["sourceBundleDigest"],
        "derivedModel": static_checks["derivedModelDigest"],
        "observationAbi": static_checks["observationSize"],
        "actionAbi": static_checks["actionSize"],
        "motionPolicy": policy_checks["motion"],
        "capturePolicy": policy_checks["capture"],
        "standPolicy": policy_checks["stand"],
        "packageLock": (
            midterm_profile["runtime"]["packageLockDigest"]
            == baseline_bindings["packageLockDigest"]
            == diagnostic_replay_profile["runtime"]["packageLockDigest"]
        ),
    }
    equivalence_status = (
        "passed"
        if all(static_checks.values()) and all(binding_checks.values())
        else "failed"
    )
    phase_diff = dynamic_comparison["categoricalDifferences"]["phase"]
    policy_diff = dynamic_comparison["categoricalDifferences"]["activePolicy"]
    termination_diff = dynamic_comparison["categoricalDifferences"]["termination"]
    height_diff = dynamic_comparison["numericDifferences"]["minimumBaseHeight"]
    equivalence_report = {
        "id": (
            "conformance://worldspec/h1/a5ci/"
            + diagnostic_replay_profile["attemptId"]
            + "/equivalence"
        ),
        "reportVersion": "0.1.0",
        "status": "completed",
        "scope": "h1_whole_body_task_space_control_diagnostic_equivalence",
        "attemptId": diagnostic_replay_profile["attemptId"],
        "baseControlProfileDigest": diagnostic_replay_profile[
            "baseControlProfileDigest"
        ],
        "replayProfileDigest": digest_json(diagnostic_replay_profile),
        "staticSemanticEquivalence": {
            "profileProjection": {
                "baselineDigest": diagnostic_replay_profile[
                    "semanticProfileProjectionDigest"
                ],
                "replayDigest": profile_projection_digest,
                "matches": profile_projection_matches,
            },
            "controllerProjection": {
                "baselineDigest": diagnostic_replay_profile[
                    "controllerSemanticProjectionDigest"
                ],
                "replayDigest": controller_projection_digest,
                "matches": controller_projection_matches,
            },
            "allowedDifferencesOnly": all(static_checks.values()),
        },
        "bindingChecks": binding_checks,
        "dynamicComparison": {
            "role": "report_only_not_equivalence_proof",
            "baselineTraceDigest": diagnostic_replay_profile[
                "baselineEvidence"
            ]["trace"]["digest"],
            "replayTraceDigest": digest_bytes(replay_trace_path.read_bytes()),
            "baselineRecordCount": len(baseline_trace),
            "replayRecordCount": len(replay_trace),
            "differences": {
                "stepCountDelta": len(replay_trace) - len(baseline_trace),
                "phaseSequenceEqual": (
                    phase_diff["samplesCompared"]
                    == dynamic_comparison["commonStepCount"]
                    and phase_diff["differenceCount"] == 0
                ),
                "activePolicySequenceEqual": (
                    policy_diff["samplesCompared"]
                    == dynamic_comparison["commonStepCount"]
                    and policy_diff["differenceCount"] == 0
                ),
                "terminationSequenceEqual": (
                    termination_diff["samplesCompared"]
                    == dynamic_comparison["commonStepCount"]
                    and termination_diff["differenceCount"] == 0
                ),
                "metricDelta": {
                    "minimumBaseHeight": height_diff[
                        "maximumAbsoluteDifference"
                    ]
                },
            },
            "detail": dynamic_comparison,
        },
        "formalEquivalenceGate": equivalence_status,
        "claimBoundary": {
            "staticSemanticProjectionIsAuthoritative": True,
            "dynamicComparisonIsEvidenceOnly": True,
            "bitwiseTraceEqualityRequired": False,
            "retroactiveRootCauseClaim": "forbidden",
        },
        "generatedAt": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
    }
    equivalence_path = artifact_dir / "equivalence-report.json"
    equivalence_path.write_bytes(canonical_bytes(equivalence_report))
    diagnostic_replay = {
        "profile": diagnostic_replay_profile,
        "diagnosticCompleteness": diagnostic_completeness,
        "equivalenceAssessment": {
            "status": equivalence_status,
            "basis": "static_semantic_projection",
            "failedChecks": sorted(
                [
                    key
                    for key, passed in {
                        **static_checks,
                        **binding_checks,
                    }.items()
                    if not passed
                ]
            ),
            "dynamicComparisonIsInformational": True,
            "reportDigest": digest_bytes(equivalence_path.read_bytes()),
        },
        "equivalenceArtifact": {
            "path": equivalence_path.name,
            "digest": digest_bytes(equivalence_path.read_bytes()),
            "sizeBytes": equivalence_path.stat().st_size,
            "distribution": "internal_only",
        },
    }
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
    if diagnostic_replay is not None:
        diagnostics = diagnostic_replay["diagnosticCompleteness"]
        equivalence = diagnostic_replay["equivalenceAssessment"]
        replay_terminal_reasons = diagnostics["terminalReasons"]
        diagnostic_passed = (
            diagnostics["status"] == "passed"
            and equivalence["status"] == "passed"
        )
        report = {
            **common,
            "id": (
                "attempt://worldspec/h1/a5ci/"
                + diagnostic_replay["profile"]["attemptId"]
                + "/report"
            ),
            "reportVersion": "0.1.0",
            "status": "completed",
            "scope": "h1_whole_body_task_space_control_diagnostic_replay",
            "attemptId": diagnostic_replay["profile"]["attemptId"],
            "executionEvidence": "executed",
            "runtimeAcceptance": "diagnostic_replay",
            "replayProfileDigest": digest_json(diagnostic_replay["profile"]),
            "baseControlProfileDigest": diagnostic_replay["profile"][
                "baseControlProfileDigest"
            ],
            "controllerStatus": "non_publishable",
            "originalTerminationReason": "unknown",
            "replayTerminationReasons": replay_terminal_reasons,
            "formalDiagnosticReplayGate": (
                "passed" if diagnostic_passed else "failed"
            ),
            "formalControlGate": (
                "passed"
                if result["qualityAssessment"]["status"] == "passed"
                else "failed"
            ),
            "artifactTransferStatus": "pending",
            "diagnosticCompleteness": diagnostics,
            "equivalenceAssessment": equivalence,
            "equivalenceArtifact": diagnostic_replay["equivalenceArtifact"],
            "claimBoundary": {
                "status": "diagnostic_replay_only",
                "originalA5CRootCause": "unknown",
                "retroactiveRootCauseClaim": "forbidden",
                "controllerCandidateClaim": "forbidden",
                "fullTaskClaim": "forbidden",
                "l3Claim": "forbidden",
                "fiveRunGate": "not_executed",
                "formalTraining": "not_started",
            },
        }
        print(
            "WORLDSPEC_A800_WHOLE_BODY_DIAGNOSTIC_REPLAY_RESULT="
            + json.dumps(report, separators=(",", ":"))
        )
    else:
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
