#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KUBECONFIG_PATH="${KUBECONFIG:-/Users/d-robotics/.config/droboticflow/kubeconfigs/poc.config}"
K8S_NAMESPACE="${K8S_NAMESPACE:-worldspec-a800-poc}"
BUILD_NAMESPACE="${WORLD_SPEC_BUILD_NAMESPACE:-droboticflow}"
NAMESPACE_MANIFEST="${ROOT_DIR}/ops/a800/namespace.yaml"
JOB_TEMPLATE="${ROOT_DIR}/ops/a800/h1-locomotion-midterm-job.yaml"
PREPULL_TEMPLATE="${ROOT_DIR}/ops/a800/h1-training-image-prepull-job.yaml"
ENTRYPOINT="${ROOT_DIR}/ops/a800/h1-locomotion-midterm-entrypoint.sh"
CHUNK_UPLOAD="${ROOT_DIR}/scripts/upload_kubernetes_file.py"
CHUNK_COPY="${ROOT_DIR}/scripts/copy_kubernetes_file.py"
MIDTERM_PROFILE="${WORLD_SPEC_MIDTERM_PROFILE:-${ROOT_DIR}/examples/h1-kitchen/locomotion-midterm-profile.json}"
STAND_REPORT="${WORLD_SPEC_WARM_START_REPORT:-${ROOT_DIR}/examples/h1-kitchen/locomotion-calibration.a800.passed.json}"
STAND_CHECKPOINT="${WORLD_SPEC_WARM_START_CHECKPOINT:-${WORLD_SPEC_STAND_CHECKPOINT:-${ROOT_DIR}/runs/a800/worldspec-h1-calibration-4mklr/calibration-checkpoint.zip}}"
RETENTION_TEACHER_REPORT="${WORLD_SPEC_RETENTION_TEACHER_REPORT:-}"
RETENTION_TEACHER_CHECKPOINT="${WORLD_SPEC_RETENTION_TEACHER_CHECKPOINT:-}"
SUPERVISOR_STAND_REPORT="${WORLD_SPEC_SUPERVISOR_STAND_REPORT:-}"
SUPERVISOR_STAND_CHECKPOINT="${WORLD_SPEC_SUPERVISOR_STAND_CHECKPOINT:-}"
DIAGNOSTIC_REPLAY_PROFILE="${WORLD_SPEC_DIAGNOSTIC_REPLAY_PROFILE:-}"
A5C_BASELINE_SUMMARY="${WORLD_SPEC_A5C_BASELINE_SUMMARY:-${ROOT_DIR}/examples/h1-kitchen/whole-body-control.a800.failed-summary.json}"
A5C_BASELINE_REPORT="${WORLD_SPEC_A5C_BASELINE_REPORT:-${ROOT_DIR}/runs/a800/worldspec-h1-midterm-d5z6c/whole-body-control-report.json}"
A5C_BASELINE_CONTROLLER="${WORLD_SPEC_A5C_BASELINE_CONTROLLER:-${ROOT_DIR}/runs/a800/worldspec-h1-midterm-d5z6c/whole-body-controller.json}"
A5C_BASELINE_TRACE="${WORLD_SPEC_A5C_BASELINE_TRACE:-${ROOT_DIR}/runs/a800/worldspec-h1-midterm-d5z6c/evaluation-traces.jsonl}"
MIDTERM_PROFILE_FILENAME="$(basename "${MIDTERM_PROFILE}")"
WARM_START_REPORT_FILENAME="$(basename "${STAND_REPORT}")"
RETENTION_TEACHER_REPORT_FILENAME=""
SUPERVISOR_STAND_REPORT_FILENAME=""
DIAGNOSTIC_REPLAY_PROFILE_FILENAME=""
A5CI_MODE=false
A5CI_ATTEMPT_ID=""
RUNTIME_IMAGE="${WORLD_SPEC_H1_RUNTIME_IMAGE:-}"
IMAGE_SOURCE_REVISION="${WORLD_SPEC_IMAGE_SOURCE_REVISION:-}"
PACKAGE_LOCK_DIGEST="${WORLD_SPEC_PACKAGE_LOCK_DIGEST:-sha256:7cc88f20b2c608d6fe673f3b994b879db69d75361206bf25f949d7acc5ed3a41}"
PROBE_REVISION="${WORLD_SPEC_PROBE_DEFINITION_REVISION:-$(git -C "${ROOT_DIR}" rev-parse HEAD)}"
TIMEOUT_SECONDS="${WORLD_SPEC_A800_TIMEOUT_SECONDS:-21600}"
OUTPUT_CHUNK_SIZE_BYTES="${WORLD_SPEC_OUTPUT_CHUNK_SIZE_BYTES:-131072}"
OUTPUT_COPY_RETRIES="${WORLD_SPEC_OUTPUT_COPY_RETRIES:-12}"
RETAIN_INCOMPLETE_REMOTE="${WORLD_SPEC_RETAIN_INCOMPLETE_REMOTE:-true}"
REPORT_FILENAME=midterm-report.json
REPORT_MARKER=WORLDSPEC_A800_MIDTERM_RESULT=
REPORT_SCHEMA=h1-locomotion-midterm-report.schema.json
GATE_FIELD=formalTrainingGate

for required in \
  "${KUBECONFIG_PATH}" \
  "${NAMESPACE_MANIFEST}" \
  "${JOB_TEMPLATE}" \
  "${PREPULL_TEMPLATE}" \
  "${ENTRYPOINT}" \
  "${CHUNK_UPLOAD}" \
  "${CHUNK_COPY}" \
  "${MIDTERM_PROFILE}" \
  "${STAND_REPORT}" \
  "${STAND_CHECKPOINT}"; do
  if [[ ! -r "${required}" ]]; then
    printf 'ERROR: required path is not readable: %s\n' "${required}" >&2
    exit 2
  fi
done

if [[ -n "${DIAGNOSTIC_REPLAY_PROFILE}" ]]; then
  for required in \
    "${DIAGNOSTIC_REPLAY_PROFILE}" \
    "${A5C_BASELINE_SUMMARY}" \
    "${A5C_BASELINE_REPORT}" \
    "${A5C_BASELINE_CONTROLLER}" \
    "${A5C_BASELINE_TRACE}"; do
    if [[ ! -r "${required}" ]]; then
      printf 'ERROR: A5-CI required path is not readable: %s\n' "${required}" >&2
      exit 2
    fi
  done
  DIAGNOSTIC_REPLAY_PROFILE_FILENAME="$(basename "${DIAGNOSTIC_REPLAY_PROFILE}")"
  A5CI_MODE=true
fi

read -r profile_image profile_lock profile_stage < <(
  python3 - "${MIDTERM_PROFILE}" <<'PY'
import json
import pathlib
import sys

profile = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(
    profile["runtime"]["containerImage"],
    profile["runtime"]["packageLockDigest"],
    profile["stage"],
)
PY
)
if [[ "${A5CI_MODE}" == "true" ]]; then
  read -r profile_image profile_lock replay_stage A5CI_ATTEMPT_ID < <(
    python3 - "${DIAGNOSTIC_REPLAY_PROFILE}" <<'PY'
import json
import pathlib
import sys

profile = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(
    profile["runtime"]["containerImage"],
    profile["runtime"]["packageLockDigest"],
    profile["stage"],
    profile["attemptId"],
)
PY
  )
  if [[ "${profile_stage}" != "whole_body_task_space_control_spike" ]] ||
    [[ "${replay_stage}" != "whole_body_task_space_control_diagnostic_replay" ]] ||
    ! [[ "${A5CI_ATTEMPT_ID}" =~ ^[a-z0-9][a-z0-9-]{2,62}$ ]]; then
    echo "ERROR: A5-CI replay/control Profile pairing is invalid" >&2
    exit 2
  fi
  REPORT_FILENAME=whole-body-diagnostic-replay-report.json
  REPORT_MARKER=WORLDSPEC_A800_WHOLE_BODY_DIAGNOSTIC_REPLAY_RESULT=
  REPORT_SCHEMA=h1-whole-body-diagnostic-replay-report.schema.json
  GATE_FIELD=formalDiagnosticReplayGate
fi
if [[ "${profile_stage}" == "dual_policy_switch_probe" ]]; then
  REPORT_FILENAME=dual-policy-report.json
  REPORT_MARKER=WORLDSPEC_A800_DUAL_POLICY_RESULT=
  REPORT_SCHEMA=h1-locomotion-dual-policy-report.schema.json
  GATE_FIELD=formalProbeGate
elif [[ "${profile_stage}" == "loaded_track_settle_capture" ]]; then
  REPORT_FILENAME=capture-report.json
  REPORT_MARKER=WORLDSPEC_A800_CAPTURE_RESULT=
  REPORT_SCHEMA=h1-locomotion-capture-report.schema.json
  GATE_FIELD=formalCaptureGate
elif [[ "${profile_stage}" == "phase_aware_supervisor_probe" ]]; then
  REPORT_FILENAME=supervisor-report.json
  REPORT_MARKER=WORLDSPEC_A800_SUPERVISOR_RESULT=
  REPORT_SCHEMA=h1-locomotion-supervisor-report.schema.json
  GATE_FIELD=formalSupervisorGate
elif [[ "${profile_stage}" == "fixed_kitchen_full_loop_probe" ]]; then
  REPORT_FILENAME=kitchen-task-report.json
  REPORT_MARKER=WORLDSPEC_A800_KITCHEN_TASK_RESULT=
  REPORT_SCHEMA=h1-kitchen-task-report.schema.json
  GATE_FIELD=formalTaskGate
elif [[ "${profile_stage}" == "whole_body_task_space_control_spike" ]]; then
  REPORT_FILENAME=whole-body-control-report.json
  REPORT_MARKER=WORLDSPEC_A800_WHOLE_BODY_RESULT=
  REPORT_SCHEMA=h1-whole-body-control-report.schema.json
  GATE_FIELD=formalControlGate
fi
if [[ "${A5CI_MODE}" == "true" ]]; then
  REPORT_FILENAME=whole-body-diagnostic-replay-report.json
  REPORT_MARKER=WORLDSPEC_A800_WHOLE_BODY_DIAGNOSTIC_REPLAY_RESULT=
  REPORT_SCHEMA=h1-whole-body-diagnostic-replay-report.schema.json
  GATE_FIELD=formalDiagnosticReplayGate
fi
if [[ "${profile_stage}" == "loaded_track_settle_retention" ]] ||
  [[ "${profile_stage}" == "dual_policy_switch_probe" ]] ||
  [[ "${profile_stage}" == "loaded_track_settle_capture" ]] ||
  [[ "${profile_stage}" == "phase_aware_supervisor_probe" ]] ||
  [[ "${profile_stage}" == "fixed_kitchen_full_loop_probe" ]] ||
  [[ "${profile_stage}" == "whole_body_task_space_control_spike" ]]; then
  for required in "${RETENTION_TEACHER_REPORT}" "${RETENTION_TEACHER_CHECKPOINT}"; do
    if [[ -z "${required}" ]] || [[ ! -r "${required}" ]]; then
      printf 'ERROR: retention teacher input is not readable: %s\n' \
        "${required:-unset}" >&2
      exit 2
    fi
  done
  RETENTION_TEACHER_REPORT_FILENAME="$(basename "${RETENTION_TEACHER_REPORT}")"
fi
if [[ "${profile_stage}" == "phase_aware_supervisor_probe" ]] ||
  [[ "${profile_stage}" == "fixed_kitchen_full_loop_probe" ]] ||
  [[ "${profile_stage}" == "whole_body_task_space_control_spike" ]]; then
  for required in "${SUPERVISOR_STAND_REPORT}" "${SUPERVISOR_STAND_CHECKPOINT}"; do
    if [[ -z "${required}" ]] || [[ ! -r "${required}" ]]; then
      printf 'ERROR: supervisor stand input is not readable: %s\n' \
        "${required:-unset}" >&2
      exit 2
    fi
  done
  SUPERVISOR_STAND_REPORT_FILENAME="$(basename "${SUPERVISOR_STAND_REPORT}")"
fi
if [[ -z "${RUNTIME_IMAGE}" ]]; then
  RUNTIME_IMAGE="${profile_image}"
fi
if [[ -z "${IMAGE_SOURCE_REVISION}" ]]; then
  IMAGE_SOURCE_REVISION="${PROBE_REVISION}"
fi
if [[ "${RUNTIME_IMAGE}" != "${profile_image}" ]] ||
  [[ "${PACKAGE_LOCK_DIGEST}" != "${profile_lock}" ]]; then
  echo "ERROR: launcher runtime does not match the midterm Profile" >&2
  exit 2
fi
if ! [[ "${RUNTIME_IMAGE}" =~ ^[^[:space:]@]+@sha256:[0-9a-f]{64}$ ]] ||
  ! [[ "${IMAGE_SOURCE_REVISION}" =~ ^[0-9a-f]{40}$ ]] ||
  ! [[ "${PROBE_REVISION}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "ERROR: runtime and Git revisions are not digest/commit pinned" >&2
  exit 2
fi
if [[ -n "$(git -C "${ROOT_DIR}" status --porcelain)" ]]; then
  echo "ERROR: midterm calibration requires a clean worktree" >&2
  exit 2
fi
git -C "${ROOT_DIR}" merge-base --is-ancestor \
  "${IMAGE_SOURCE_REVISION}" "${PROBE_REVISION}"
remote_revision="$(
  git ls-remote https://github.com/eust-w/WorldSpec.git \
    "refs/heads/feature/worldspec-v0.1" |
    awk '{print $1}'
)"
if [[ "${remote_revision}" != "${PROBE_REVISION}" ]]; then
  printf 'ERROR: probe revision is not remote feature head: local=%s remote=%s\n' \
    "${PROBE_REVISION}" "${remote_revision}" >&2
  exit 2
fi

python3 - \
  "${MIDTERM_PROFILE}" \
  "${STAND_REPORT}" \
  "${STAND_CHECKPOINT}" \
  "${RETENTION_TEACHER_REPORT}" \
  "${RETENTION_TEACHER_CHECKPOINT}" \
  "${SUPERVISOR_STAND_REPORT}" \
  "${SUPERVISOR_STAND_CHECKPOINT}" <<'PY'
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timezone

profile = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
report_payload = pathlib.Path(sys.argv[2]).read_bytes()
checkpoint_payload = pathlib.Path(sys.argv[3]).read_bytes()
source = (
    profile["motionPolicy"]
    if profile["stage"] in {
        "dual_policy_switch_probe",
        "phase_aware_supervisor_probe",
        "fixed_kitchen_full_loop_probe",
        "whole_body_task_space_control_spike",
    }
    else profile["warmStart"]
)
if f"sha256:{hashlib.sha256(report_payload).hexdigest()}" != source["sourceReportDigest"]:
    raise SystemExit("stand report digest mismatch")
if (
    f"sha256:{hashlib.sha256(checkpoint_payload).hexdigest()}"
    != source["checkpointDigest"]
    or len(checkpoint_payload) != source["checkpointSizeBytes"]
):
    raise SystemExit("stand checkpoint identity mismatch")
if profile["stage"] in {
    "loaded_track_settle_retention",
    "dual_policy_switch_probe",
    "loaded_track_settle_capture",
    "phase_aware_supervisor_probe",
    "fixed_kitchen_full_loop_probe",
    "whole_body_task_space_control_spike",
}:
    teacher_report_payload = pathlib.Path(sys.argv[4]).read_bytes()
    teacher_checkpoint_payload = pathlib.Path(sys.argv[5]).read_bytes()
    teacher = (
        profile["standPolicy"]
        if profile["stage"] == "dual_policy_switch_probe"
        else (
            profile["capturePolicy"]
            if profile["stage"] in {
                "phase_aware_supervisor_probe",
                "fixed_kitchen_full_loop_probe",
                "whole_body_task_space_control_spike",
            }
            else (
                profile["motionTeacher"]
                if profile["stage"] == "loaded_track_settle_capture"
                else profile["retentionTeacher"]
            )
        )
    )
    if (
        f"sha256:{hashlib.sha256(teacher_report_payload).hexdigest()}"
        != teacher["sourceReportDigest"]
    ):
        raise SystemExit("retention teacher report digest mismatch")
    if (
        f"sha256:{hashlib.sha256(teacher_checkpoint_payload).hexdigest()}"
        != teacher["checkpointDigest"]
        or len(teacher_checkpoint_payload) != teacher["checkpointSizeBytes"]
    ):
        raise SystemExit("retention teacher checkpoint identity mismatch")
if profile["stage"] in {
    "phase_aware_supervisor_probe",
    "fixed_kitchen_full_loop_probe",
    "whole_body_task_space_control_spike",
}:
    stand_report_payload = pathlib.Path(sys.argv[6]).read_bytes()
    stand_checkpoint_payload = pathlib.Path(sys.argv[7]).read_bytes()
    stand = profile["standPolicy"]
    if (
        f"sha256:{hashlib.sha256(stand_report_payload).hexdigest()}"
        != stand["sourceReportDigest"]
    ):
        raise SystemExit("supervisor stand report digest mismatch")
    if (
        f"sha256:{hashlib.sha256(stand_checkpoint_payload).hexdigest()}"
        != stand["checkpointDigest"]
        or len(stand_checkpoint_payload) != stand["checkpointSizeBytes"]
    ):
        raise SystemExit("supervisor stand checkpoint identity mismatch")
PY

if [[ "${A5CI_MODE}" == "true" ]]; then
  python3 - \
    "${MIDTERM_PROFILE}" \
    "${DIAGNOSTIC_REPLAY_PROFILE}" \
    "${A5C_BASELINE_SUMMARY}" \
    "${A5C_BASELINE_REPORT}" \
    "${A5C_BASELINE_CONTROLLER}" \
    "${A5C_BASELINE_TRACE}" \
    "${RUNTIME_IMAGE}" \
    "${IMAGE_SOURCE_REVISION}" \
    "${PACKAGE_LOCK_DIGEST}" <<'PY'
import copy
import hashlib
import json
import pathlib
import sys


def digest_bytes(payload):
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def digest_json(value):
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return digest_bytes(payload)


control_path = pathlib.Path(sys.argv[1])
replay_path = pathlib.Path(sys.argv[2])
control = json.loads(control_path.read_text(encoding="utf-8"))
replay = json.loads(replay_path.read_text(encoding="utf-8"))
if digest_json(control) != replay["baseControlProfileDigest"]:
    raise SystemExit("A5-CI base control Profile digest mismatch")
semantic = copy.deepcopy(control)
semantic["runtime"].pop("containerImage")
semantic["runtime"].pop("containerDigest")
if digest_json(semantic) != replay["semanticProfileProjectionDigest"]:
    raise SystemExit("A5-CI semantic control Profile projection mismatch")
for name, path in zip(
    ("summary", "report", "controller", "trace"),
    map(pathlib.Path, sys.argv[3:7]),
    strict=True,
):
    payload = path.read_bytes()
    expected = replay["baselineEvidence"][name]
    if digest_bytes(payload) != expected["digest"] or len(payload) != expected["sizeBytes"]:
        raise SystemExit(f"A5-CI baseline {name} identity mismatch")
if sum(1 for line in pathlib.Path(sys.argv[6]).read_text(encoding="utf-8").splitlines() if line) != replay["baselineEvidence"]["trace"]["recordCount"]:
    raise SystemExit("A5-CI baseline trace record count mismatch")
controller = json.loads(pathlib.Path(sys.argv[5]).read_text(encoding="utf-8"))
controller.pop("profileDigest", None)
if digest_json(controller) != replay["controllerSemanticProjectionDigest"]:
    raise SystemExit("A5-CI baseline controller semantic projection mismatch")
baseline_report = json.loads(pathlib.Path(sys.argv[4]).read_text(encoding="utf-8"))
bindings = replay["baselineBindings"]
if (
    bindings["seed"] != control["seed"]
    or bindings["probeRevision"] != baseline_report["probeDefinition"]["commit"]
    or bindings["imageSourceRevision"] != baseline_report["imageSource"]["commit"]
    or bindings["containerImage"] != baseline_report["container"]["image"]
    or bindings["containerDigest"]
    != baseline_report["container"]["image"].rsplit("@", 1)[1]
    or bindings["packageLockDigest"] != baseline_report["packageLockDigest"]
    or bindings["target"] != baseline_report["target"]
):
    raise SystemExit("A5-CI baseline binding mismatch")
for role in ("motion", "capture", "stand"):
    source = baseline_report["policies"][role]
    expected = bindings["policies"][role]
    if (
        expected["checkpointDigest"] != source["archiveDigest"]
        or expected["checkpointSizeBytes"] != source["archiveSizeBytes"]
    ):
        raise SystemExit(f"A5-CI baseline {role} policy binding mismatch")
runtime = replay["runtime"]
if (
    runtime["containerImage"] != sys.argv[7]
    or runtime["containerDigest"] != sys.argv[7].rsplit("@", 1)[1]
    or runtime["imageSourceRevision"] != sys.argv[8]
    or runtime["packageLockDigest"] != sys.argv[9]
):
    raise SystemExit("A5-CI runtime binding mismatch")
if replay["allowedChanges"] != [
    "diagnostic_instrumentation",
    "source_archive_digest",
    "container_image",
]:
    raise SystemExit("A5-CI allowed-change set mismatch")
PY
fi

kubectl_cmd=(kubectl --kubeconfig "${KUBECONFIG_PATH}" -n "${K8S_NAMESPACE}")
build_kubectl_cmd=(
  kubectl --kubeconfig "${KUBECONFIG_PATH}" -n "${BUILD_NAMESPACE}"
)
kubectl --kubeconfig "${KUBECONFIG_PATH}" apply \
  -f "${NAMESPACE_MANIFEST}" >/dev/null
if [[ -n "$("${kubectl_cmd[@]}" get jobs -o name)" ]]; then
  echo "ERROR: WorldSpec namespace already has an active or retained Job" >&2
  exit 2
fi

python3 - "${KUBECONFIG_PATH}" <<'PY'
import json
import subprocess
import sys

base = ["kubectl", "--kubeconfig", sys.argv[1]]
nodes = json.loads(subprocess.check_output([*base, "get", "nodes", "-o", "json"]))
pods = json.loads(subprocess.check_output([*base, "get", "pods", "-A", "-o", "json"]))
selector = "ehc.lgn5.c128m1024.8a800.8re.4d"
available = {}
for node in nodes["items"]:
    if node["metadata"]["labels"].get("node.kubernetes.io/cce-instance-type") == selector:
        available[node["metadata"]["name"]] = int(
            node["status"]["allocatable"].get("nvidia.com/gpu", "0")
        )
for pod in pods["items"]:
    node = pod.get("spec", {}).get("nodeName")
    if node not in available or pod.get("status", {}).get("phase") in ("Succeeded", "Failed"):
        continue
    requested = sum(
        int(container.get("resources", {}).get("requests", {}).get("nvidia.com/gpu", "0"))
        for container in pod.get("spec", {}).get("containers", [])
    )
    available[node] -= requested
if max(available.values(), default=0) < 1:
    raise SystemExit("A800_CAPACITY_BLOCKED: no unallocated A800 GPU is available")
print("a800_capacity_preflight=" + json.dumps(available, sort_keys=True))
PY

run_suffix="$(date -u +%Y%m%d%H%M%S)"
A5CI_JOB_NAME=""
if [[ "${A5CI_MODE}" == "true" ]]; then
  attempt_short="$(
    python3 - "${A5CI_ATTEMPT_ID}" <<'PY'
import hashlib
import sys
print(hashlib.sha256(sys.argv[1].encode("utf-8")).hexdigest()[:12])
PY
  )"
  A5CI_JOB_NAME="worldspec-h1-a5ci-${attempt_short}"
  if [[ -e "${ROOT_DIR}/runs/a800/${A5CI_JOB_NAME}" ]] ||
    [[ -e "${ROOT_DIR}/examples/h1-kitchen/${A5CI_ATTEMPT_ID}.receipt.json" ]]; then
    echo "ERROR: A5-CI deterministic attempt already has local evidence" >&2
    exit 2
  fi
fi
short_revision="${PROBE_REVISION:0:12}"
script_configmap="worldspec-h1-midterm-script-${short_revision}-${run_suffix}"
source_configmap="worldspec-h1-midterm-source-${short_revision}-${run_suffix}"
temporary_manifest="$(mktemp "${TMPDIR:-/tmp}/worldspec-h1-midterm.XXXXXX.yaml")"
prepull_manifest="$(mktemp "${TMPDIR:-/tmp}/worldspec-h1-prepull.XXXXXX.yaml")"
source_archive="$(mktemp "${TMPDIR:-/tmp}/worldspec-source.XXXXXX.tar.gz")"
prepull_job=""
job_name=""
pod_name=""
local_result_dir=""
artifact_copied=false

cleanup() {
  local exit_code=$?
  local retain_remote=false
  set +e
  if [[ -n "${job_name}" ]] &&
    [[ "${exit_code}" -ne 0 ]] &&
    [[ "${artifact_copied}" != "true" ]] &&
    [[ "${RETAIN_INCOMPLETE_REMOTE}" == "true" ]]; then
    retain_remote=true
  fi
  if [[ -n "${prepull_job}" ]]; then
    "${build_kubectl_cmd[@]}" delete job "${prepull_job}" \
      --ignore-not-found --wait=true --timeout=180s >/dev/null 2>&1
  fi
  if [[ -n "${job_name}" ]] && [[ "${retain_remote}" != "true" ]]; then
    "${kubectl_cmd[@]}" delete job "${job_name}" \
      --ignore-not-found --wait=true --timeout=180s >/dev/null 2>&1
  fi
  if [[ "${retain_remote}" == "true" ]]; then
    printf \
      'remote_evidence_retained=true job=%s namespace=%s result_dir=%s\n' \
      "${job_name:-unset}" "${K8S_NAMESPACE}" "${local_result_dir:-unset}" >&2
  else
    "${kubectl_cmd[@]}" delete configmap "${script_configmap}" \
      --ignore-not-found >/dev/null 2>&1
    "${kubectl_cmd[@]}" delete configmap "${source_configmap}" \
      --ignore-not-found >/dev/null 2>&1
  fi
  rm -f "${temporary_manifest}" "${prepull_manifest}" "${source_archive}"
  exit "${exit_code}"
}
trap cleanup EXIT INT TERM

sed -e "s|__RUNTIME_IMAGE__|${RUNTIME_IMAGE}|g" \
  "${PREPULL_TEMPLATE}" >"${prepull_manifest}"
prepull_resource="$("${build_kubectl_cmd[@]}" create \
  -f "${prepull_manifest}" -o name)"
prepull_job="${prepull_resource#job.batch/}"
"${build_kubectl_cmd[@]}" wait \
  --for=condition=complete "job/${prepull_job}" --timeout=1800s >/dev/null
"${build_kubectl_cmd[@]}" delete job "${prepull_job}" \
  --wait=true --timeout=180s >/dev/null
prepull_job=""

git -C "${ROOT_DIR}" archive --format=tar "${PROBE_REVISION}" |
  gzip -n -9 >"${source_archive}"
source_archive_digest="$(
  python3 - "${source_archive}" <<'PY'
import hashlib
import pathlib
import sys
print(f"sha256:{hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()}")
PY
)"
"${kubectl_cmd[@]}" create configmap "${script_configmap}" \
  --from-file="run.sh=${ENTRYPOINT}" >/dev/null
"${kubectl_cmd[@]}" create configmap "${source_configmap}" \
  --from-file="worldspec.tar.gz=${source_archive}" >/dev/null
sed \
  -e "s|__RUNTIME_IMAGE__|${RUNTIME_IMAGE}|g" \
  -e "s|__PROBE_DEFINITION_REVISION__|${PROBE_REVISION}|g" \
  -e "s|__IMAGE_SOURCE_REVISION__|${IMAGE_SOURCE_REVISION}|g" \
  -e "s|__PROBE_INPUT_REVISION__|${PROBE_REVISION}|g" \
  -e "s|__PACKAGE_LOCK_DIGEST__|${PACKAGE_LOCK_DIGEST}|g" \
  -e "s|__SOURCE_ARCHIVE_DIGEST__|${source_archive_digest}|g" \
  -e "s|__MIDTERM_PROFILE_FILENAME__|${MIDTERM_PROFILE_FILENAME}|g" \
  -e "s|__WARM_START_REPORT_FILENAME__|${WARM_START_REPORT_FILENAME}|g" \
  -e "s|__RETENTION_TEACHER_REPORT_FILENAME__|${RETENTION_TEACHER_REPORT_FILENAME}|g" \
  -e "s|__SUPERVISOR_STAND_REPORT_FILENAME__|${SUPERVISOR_STAND_REPORT_FILENAME}|g" \
  -e "s|__DIAGNOSTIC_REPLAY_PROFILE_FILENAME__|${DIAGNOSTIC_REPLAY_PROFILE_FILENAME}|g" \
  -e "s|__SCRIPT_CONFIGMAP__|${script_configmap}|g" \
  -e "s|__SOURCE_CONFIGMAP__|${source_configmap}|g" \
  "${JOB_TEMPLATE}" >"${temporary_manifest}"
if [[ "${A5CI_MODE}" == "true" ]]; then
  python3 - "${temporary_manifest}" "${A5CI_JOB_NAME}" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
payload = path.read_text(encoding="utf-8")
needle = "  generateName: worldspec-h1-midterm-\n"
replacement = f"  name: {sys.argv[2]}\n"
if payload.count(needle) != 1:
    raise SystemExit("A5-CI Job template generateName marker is missing or ambiguous")
path.write_text(payload.replace(needle, replacement), encoding="utf-8")
PY
fi

job_resource="$("${kubectl_cmd[@]}" create -f "${temporary_manifest}" -o name)"
job_name="${job_resource#job.batch/}"
local_result_dir="${ROOT_DIR}/runs/a800/${job_name}"
mkdir -p "${local_result_dir}"
printf 'namespace=%s\njob=%s\nprobe_revision=%s\nimage=%s\nresult_dir=%s\n' \
  "${K8S_NAMESPACE}" "${job_name}" "${PROBE_REVISION}" \
  "${RUNTIME_IMAGE}" "${local_result_dir}"

deadline=$((SECONDS + TIMEOUT_SECONDS))
last_stage=""
while ((SECONDS < deadline)); do
  pod_name="$("${kubectl_cmd[@]}" get pods -l "job-name=${job_name}" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  if [[ -n "${pod_name}" ]]; then
    phase="$("${kubectl_cmd[@]}" get pod "${pod_name}" \
      -o jsonpath='{.status.phase}' 2>/dev/null || true)"
    pod_log="$("${kubectl_cmd[@]}" logs "${pod_name}" 2>/dev/null || true)"
    current_stage="$(awk -F= \
      '/^WORLDSPEC_A800_MIDTERM_STAGE=/{value=$2} END{print value}' \
      <<<"${pod_log}")"
    if [[ -n "${current_stage}" ]] && [[ "${current_stage}" != "${last_stage}" ]]; then
      printf 'pod=%s phase=%s stage=%s\n' \
        "${pod_name}" "${phase}" "${current_stage}"
      last_stage="${current_stage}"
    fi
    if [[ "${current_stage}" == "waiting_for_input" ]] &&
      [[ ! -f "${local_result_dir}/input-uploaded" ]]; then
      read -r stand_report_size stand_report_digest checkpoint_size checkpoint_digest < <(
        python3 - "${STAND_REPORT}" "${STAND_CHECKPOINT}" <<'PY'
import hashlib
import pathlib
import sys
values = []
for value in sys.argv[1:]:
    payload = pathlib.Path(value).read_bytes()
    values.extend((str(len(payload)), f"sha256:{hashlib.sha256(payload).hexdigest()}"))
print(*values)
PY
      )
      python3 "${CHUNK_UPLOAD}" \
        --kubeconfig "${KUBECONFIG_PATH}" \
        --namespace "${K8S_NAMESPACE}" \
        --pod "${pod_name}" \
        --container midterm \
        --source "${STAND_REPORT}" \
        --remote-path /scratch/inputs/stand-report.json \
        --expected-size "${stand_report_size}" \
        --expected-digest "${stand_report_digest}"
      python3 "${CHUNK_UPLOAD}" \
        --kubeconfig "${KUBECONFIG_PATH}" \
        --namespace "${K8S_NAMESPACE}" \
        --pod "${pod_name}" \
        --container midterm \
        --source "${STAND_CHECKPOINT}" \
        --remote-path /scratch/inputs/stand-checkpoint.zip \
        --expected-size "${checkpoint_size}" \
        --expected-digest "${checkpoint_digest}"
      if [[ "${profile_stage}" == "loaded_track_settle_retention" ]] ||
        [[ "${profile_stage}" == "dual_policy_switch_probe" ]] ||
        [[ "${profile_stage}" == "loaded_track_settle_capture" ]] ||
        [[ "${profile_stage}" == "phase_aware_supervisor_probe" ]] ||
        [[ "${profile_stage}" == "fixed_kitchen_full_loop_probe" ]] ||
        [[ "${profile_stage}" == "whole_body_task_space_control_spike" ]]; then
        read -r teacher_report_size teacher_report_digest \
          teacher_checkpoint_size teacher_checkpoint_digest < <(
          python3 - \
            "${RETENTION_TEACHER_REPORT}" \
            "${RETENTION_TEACHER_CHECKPOINT}" <<'PY'
import hashlib
import pathlib
import sys
values = []
for value in sys.argv[1:]:
    payload = pathlib.Path(value).read_bytes()
    values.extend((str(len(payload)), f"sha256:{hashlib.sha256(payload).hexdigest()}"))
print(*values)
PY
        )
        python3 "${CHUNK_UPLOAD}" \
          --kubeconfig "${KUBECONFIG_PATH}" \
          --namespace "${K8S_NAMESPACE}" \
          --pod "${pod_name}" \
          --container midterm \
          --source "${RETENTION_TEACHER_REPORT}" \
          --remote-path /scratch/inputs/stand-teacher-report.json \
          --expected-size "${teacher_report_size}" \
          --expected-digest "${teacher_report_digest}"
        python3 "${CHUNK_UPLOAD}" \
          --kubeconfig "${KUBECONFIG_PATH}" \
          --namespace "${K8S_NAMESPACE}" \
          --pod "${pod_name}" \
          --container midterm \
          --source "${RETENTION_TEACHER_CHECKPOINT}" \
          --remote-path /scratch/inputs/stand-teacher-checkpoint.zip \
          --expected-size "${teacher_checkpoint_size}" \
          --expected-digest "${teacher_checkpoint_digest}"
      fi
      if [[ "${profile_stage}" == "phase_aware_supervisor_probe" ]] ||
        [[ "${profile_stage}" == "fixed_kitchen_full_loop_probe" ]] ||
        [[ "${profile_stage}" == "whole_body_task_space_control_spike" ]]; then
        read -r supervisor_stand_report_size supervisor_stand_report_digest \
          supervisor_stand_checkpoint_size supervisor_stand_checkpoint_digest < <(
          python3 - \
            "${SUPERVISOR_STAND_REPORT}" \
            "${SUPERVISOR_STAND_CHECKPOINT}" <<'PY'
import hashlib
import pathlib
import sys
values = []
for value in sys.argv[1:]:
    payload = pathlib.Path(value).read_bytes()
    values.extend((str(len(payload)), f"sha256:{hashlib.sha256(payload).hexdigest()}"))
print(*values)
PY
        )
        python3 "${CHUNK_UPLOAD}" \
          --kubeconfig "${KUBECONFIG_PATH}" \
          --namespace "${K8S_NAMESPACE}" \
          --pod "${pod_name}" \
          --container midterm \
          --source "${SUPERVISOR_STAND_REPORT}" \
          --remote-path /scratch/inputs/supervisor-stand-report.json \
          --expected-size "${supervisor_stand_report_size}" \
          --expected-digest "${supervisor_stand_report_digest}"
        python3 "${CHUNK_UPLOAD}" \
          --kubeconfig "${KUBECONFIG_PATH}" \
          --namespace "${K8S_NAMESPACE}" \
          --pod "${pod_name}" \
          --container midterm \
          --source "${SUPERVISOR_STAND_CHECKPOINT}" \
          --remote-path /scratch/inputs/supervisor-stand-checkpoint.zip \
          --expected-size "${supervisor_stand_checkpoint_size}" \
          --expected-digest "${supervisor_stand_checkpoint_digest}"
      fi
      if [[ "${A5CI_MODE}" == "true" ]]; then
        baseline_sources=(
          "${A5C_BASELINE_SUMMARY}"
          "${A5C_BASELINE_REPORT}"
          "${A5C_BASELINE_CONTROLLER}"
          "${A5C_BASELINE_TRACE}"
        )
        baseline_remotes=(
          /scratch/inputs/a5c-baseline-summary.json
          /scratch/inputs/a5c-baseline-report.json
          /scratch/inputs/a5c-baseline-controller.json
          /scratch/inputs/a5c-baseline-trace.jsonl
        )
        for index in "${!baseline_sources[@]}"; do
          read -r baseline_size baseline_digest < <(
            python3 - "${baseline_sources[index]}" <<'PY'
import hashlib
import pathlib
import sys
payload = pathlib.Path(sys.argv[1]).read_bytes()
print(len(payload), f"sha256:{hashlib.sha256(payload).hexdigest()}")
PY
          )
          python3 "${CHUNK_UPLOAD}" \
            --kubeconfig "${KUBECONFIG_PATH}" \
            --namespace "${K8S_NAMESPACE}" \
            --pod "${pod_name}" \
            --container midterm \
            --source "${baseline_sources[index]}" \
            --remote-path "${baseline_remotes[index]}" \
            --expected-size "${baseline_size}" \
            --expected-digest "${baseline_digest}" \
            --chunk-size 524288 \
            --retries "${OUTPUT_COPY_RETRIES}"
        done
      fi
      "${kubectl_cmd[@]}" exec "${pod_name}" -c midterm -- \
        touch /scratch/inputs/input-ready
      touch "${local_result_dir}/input-uploaded"
      printf 'input_uploaded=true\n'
    fi
    if [[ "${current_stage}" == "artifact_ready" ]] &&
      [[ "${artifact_copied}" != "true" ]]; then
      "${kubectl_cmd[@]}" logs "${pod_name}" \
        >"${local_result_dir}/job.log"
      python3 - "${local_result_dir}/job.log" \
        "${local_result_dir}/${REPORT_FILENAME}" \
        "${REPORT_MARKER}" \
        "${GATE_FIELD}" <<'PY'
import json
import pathlib
import sys

log_path = pathlib.Path(sys.argv[1])
report_path = pathlib.Path(sys.argv[2])
prefix = sys.argv[3]
gate_field = sys.argv[4]
lines = log_path.read_text(encoding="utf-8").splitlines()
matches = [line[len(prefix):] for line in lines if line.startswith(prefix)]
if len(matches) != 1:
    raise SystemExit(f"expected one result marker, found {len(matches)}")
report = json.loads(matches[0])
ccd = sum("CCD overflow" in line for line in lines)
capacity = sum(
    "overflow" in line.lower() and "ccd overflow" not in line.lower()
    for line in lines
)
abnormal = sum("abnormal contact" in line.lower() for line in lines)
tests = report["qualityAssessment"]["tests"]
joint = sum(
    any(
        "joint" in reason and "limit" in reason
        for reason in test["metrics"].get("terminalReasons", [])
    )
    for test in tests
)
nonfinite = sum(test["metrics"]["nonFiniteSamples"] for test in tests)
clean = ccd == capacity == abnormal == joint == nonfinite == 0
report["logDiagnostics"] = {
    "ccdOverflowCount": ccd,
    "capacityOverflowCount": capacity,
    "abnormalContactCount": abnormal,
    "jointLimitViolationCount": joint,
    "nonFiniteCount": nonfinite,
    "clean": clean,
}
if gate_field == "formalDiagnosticReplayGate":
    diagnostic_clean = (
        report["diagnosticCompleteness"]["status"] == "passed"
        and report["equivalenceAssessment"]["status"] == "passed"
        and ccd == capacity == abnormal == 0
    )
    report[gate_field] = "passed" if diagnostic_clean else "failed"
    report["formalControlGate"] = (
        "passed"
        if report["qualityAssessment"]["status"] == "passed"
        and ccd == capacity == abnormal == joint == nonfinite == 0
        else "failed"
    )
    report["controllerStatus"] = "non_publishable"
    report["artifactTransferStatus"] = "pending"
else:
    report[gate_field] = (
        "passed"
        if report["qualityAssessment"]["status"] == "passed" and clean
        else "failed"
    )
if gate_field == "formalProbeGate":
    report["controllerStatus"] = (
        "candidate" if report[gate_field] == "passed" else "non_publishable"
    )
elif gate_field == "formalCaptureGate":
    report["policyStatus"] = (
        "capture_candidate" if report[gate_field] == "passed" else "non_publishable"
    )
elif gate_field == "formalSupervisorGate":
    report["controllerStatus"] = (
        "supervisor_candidate"
        if report[gate_field] == "passed"
        else "non_publishable"
    )
elif gate_field == "formalTaskGate":
    report["controllerStatus"] = (
        "integration_candidate"
        if report[gate_field] == "passed"
        else "non_publishable"
    )
elif gate_field == "formalControlGate":
    report["controllerStatus"] = (
        "control_candidate"
        if report[gate_field] == "passed"
        else "non_publishable"
    )
report_path.write_text(
    json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
      if [[ "${profile_stage}" == "dual_policy_switch_probe" ]] ||
        [[ "${profile_stage}" == "phase_aware_supervisor_probe" ]] ||
        [[ "${profile_stage}" == "fixed_kitchen_full_loop_probe" ]] ||
        [[ "${profile_stage}" == "whole_body_task_space_control_spike" ]]; then
        read -r controller_size controller_digest trace_size trace_digest < <(
          python3 - "${local_result_dir}/${REPORT_FILENAME}" <<'PY'
import json
import pathlib
import sys
report = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
controller = report["controllerArtifact"]
trace = report["traceArtifact"]
print(controller["sizeBytes"], controller["digest"], trace["sizeBytes"], trace["digest"])
PY
        )
        python3 "${CHUNK_COPY}" \
          --kubeconfig "${KUBECONFIG_PATH}" \
          --namespace "${K8S_NAMESPACE}" \
          --pod "${pod_name}" \
          --container midterm \
          --remote-path "$(
            if [[ "${profile_stage}" == "fixed_kitchen_full_loop_probe" ]]; then
              printf '/scratch/results/artifacts/kitchen-task-controller.json'
            elif [[ "${profile_stage}" == "whole_body_task_space_control_spike" ]]; then
              printf '/scratch/results/artifacts/whole-body-controller.json'
            elif [[ "${profile_stage}" == "phase_aware_supervisor_probe" ]]; then
              printf '/scratch/results/artifacts/phase-aware-supervisor.json'
            else
              printf '/scratch/results/artifacts/dual-policy-controller.json'
            fi
          )" \
          --destination "$(
            if [[ "${profile_stage}" == "fixed_kitchen_full_loop_probe" ]]; then
              printf '%s/kitchen-task-controller.json' "${local_result_dir}"
            elif [[ "${profile_stage}" == "whole_body_task_space_control_spike" ]]; then
              printf '%s/whole-body-controller.json' "${local_result_dir}"
            elif [[ "${profile_stage}" == "phase_aware_supervisor_probe" ]]; then
              printf '%s/phase-aware-supervisor.json' "${local_result_dir}"
            else
              printf '%s/dual-policy-controller.json' "${local_result_dir}"
            fi
          )" \
          --expected-size "${controller_size}" \
          --expected-digest "${controller_digest}" \
          --chunk-size "${OUTPUT_CHUNK_SIZE_BYTES}" \
          --retries "${OUTPUT_COPY_RETRIES}"
      else
        read -r checkpoint_size checkpoint_digest trace_size trace_digest < <(
          python3 - "${local_result_dir}/${REPORT_FILENAME}" <<'PY'
import json
import pathlib
import sys
report = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
checkpoint = report["researchCheckpoint"]
trace = report["traceArtifact"]
print(checkpoint["sizeBytes"], checkpoint["digest"], trace["sizeBytes"], trace["digest"])
PY
        )
        python3 "${CHUNK_COPY}" \
          --kubeconfig "${KUBECONFIG_PATH}" \
          --namespace "${K8S_NAMESPACE}" \
          --pod "${pod_name}" \
          --container midterm \
          --remote-path /scratch/results/artifacts/midterm-checkpoint.zip \
          --destination "${local_result_dir}/midterm-checkpoint.zip" \
          --expected-size "${checkpoint_size}" \
          --expected-digest "${checkpoint_digest}" \
          --chunk-size "${OUTPUT_CHUNK_SIZE_BYTES}" \
          --retries "${OUTPUT_COPY_RETRIES}"
        if [[ "${profile_stage}" == "loaded_track_settle_capture" ]]; then
          read -r snapshot_size snapshot_digest < <(
            python3 - "${local_result_dir}/${REPORT_FILENAME}" <<'PY'
import json
import pathlib
import sys
report = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
snapshot = report["snapshotBank"]
print(snapshot["sizeBytes"], snapshot["digest"])
PY
          )
          python3 "${CHUNK_COPY}" \
            --kubeconfig "${KUBECONFIG_PATH}" \
            --namespace "${K8S_NAMESPACE}" \
            --pod "${pod_name}" \
            --container midterm \
            --remote-path /scratch/results/artifacts/capture-state-bank.npz \
            --destination "${local_result_dir}/capture-state-bank.npz" \
            --expected-size "${snapshot_size}" \
            --expected-digest "${snapshot_digest}" \
            --chunk-size "${OUTPUT_CHUNK_SIZE_BYTES}" \
            --retries "${OUTPUT_COPY_RETRIES}"
        fi
      fi
      python3 "${CHUNK_COPY}" \
        --kubeconfig "${KUBECONFIG_PATH}" \
        --namespace "${K8S_NAMESPACE}" \
        --pod "${pod_name}" \
        --container midterm \
        --remote-path /scratch/results/artifacts/evaluation-traces.jsonl \
        --destination "${local_result_dir}/evaluation-traces.jsonl" \
        --expected-size "${trace_size}" \
        --expected-digest "${trace_digest}" \
        --chunk-size "${OUTPUT_CHUNK_SIZE_BYTES}" \
        --retries "${OUTPUT_COPY_RETRIES}"
      if [[ "${A5CI_MODE}" == "true" ]]; then
        read -r equivalence_size equivalence_digest < <(
          python3 - "${local_result_dir}/${REPORT_FILENAME}" <<'PY'
import json
import pathlib
import sys
report = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
artifact = report["equivalenceArtifact"]
print(artifact["sizeBytes"], artifact["digest"])
PY
        )
        python3 "${CHUNK_COPY}" \
          --kubeconfig "${KUBECONFIG_PATH}" \
          --namespace "${K8S_NAMESPACE}" \
          --pod "${pod_name}" \
          --container midterm \
          --remote-path /scratch/results/artifacts/equivalence-report.json \
          --destination "${local_result_dir}/equivalence-report.json" \
          --expected-size "${equivalence_size}" \
          --expected-digest "${equivalence_digest}" \
          --chunk-size "${OUTPUT_CHUNK_SIZE_BYTES}" \
          --retries "${OUTPUT_COPY_RETRIES}"
        python3 - \
          "${local_result_dir}/${REPORT_FILENAME}" \
          "${local_result_dir}/whole-body-controller.json" \
          "${local_result_dir}/evaluation-traces.jsonl" \
          "${local_result_dir}/equivalence-report.json" \
          "${local_result_dir}/artifact-receipt.json" \
          "${A5CI_ATTEMPT_ID}" <<'PY'
import hashlib
import json
import pathlib
import sys


def identity(path):
    payload = path.read_bytes()
    return {
        "path": path.name,
        "sizeBytes": len(payload),
        "digest": f"sha256:{hashlib.sha256(payload).hexdigest()}",
    }


report_path = pathlib.Path(sys.argv[1])
report = json.loads(report_path.read_text(encoding="utf-8"))
report["artifactTransferStatus"] = "passed"
report_path.write_text(
    json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
receipt_path = pathlib.Path(sys.argv[5])
receipt = {
    "id": f"receipt://worldspec/h1/a5ci/{sys.argv[6]}",
    "receiptVersion": "0.1.0",
    "attemptId": sys.argv[6],
    "status": "verified",
    "artifactCopied": True,
    "artifacts": {
        "report": identity(report_path),
        "controller": identity(pathlib.Path(sys.argv[2])),
        "trace": identity(pathlib.Path(sys.argv[3])),
        "equivalence": identity(pathlib.Path(sys.argv[4])),
    },
    "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
}
receipt_path.write_text(
    json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
      fi
      "${kubectl_cmd[@]}" exec "${pod_name}" -c midterm -- \
        touch /scratch/results/artifact-copied
      artifact_copied=true
      printf 'artifact_copied=true\n'
    fi
    if [[ "${phase}" == "Succeeded" ]] || [[ "${phase}" == "Failed" ]]; then
      break
    fi
  fi
  sleep 10
done

if [[ -n "${pod_name}" ]]; then
  "${kubectl_cmd[@]}" logs "${pod_name}" \
    >"${local_result_dir}/job.log" 2>&1 || true
  "${kubectl_cmd[@]}" get pod "${pod_name}" -o yaml \
    >"${local_result_dir}/pod.yaml" 2>/dev/null || true
  "${kubectl_cmd[@]}" describe pod "${pod_name}" \
    >"${local_result_dir}/pod-describe.txt" 2>/dev/null || true
fi
"${kubectl_cmd[@]}" get job "${job_name}" -o yaml \
  >"${local_result_dir}/job.yaml" 2>/dev/null || true
if [[ -z "${pod_name}" ]]; then
  echo "ERROR: midterm Job did not create a Pod" >&2
  exit 1
fi
phase="$("${kubectl_cmd[@]}" get pod "${pod_name}" \
  -o jsonpath='{.status.phase}' 2>/dev/null || true)"
if [[ "${phase}" != "Succeeded" ]] || [[ "${artifact_copied}" != "true" ]]; then
  printf 'ERROR: midterm ended in phase %s; see %s\n' \
    "${phase:-unknown}" "${local_result_dir}" >&2
  exit 1
fi

python3 - \
  "${ROOT_DIR}" \
  "${local_result_dir}/${REPORT_FILENAME}" \
  "${REPORT_SCHEMA}" <<'PY'
import json
import pathlib
import sys
from referencing import Registry, Resource
from jsonschema import Draft202012Validator

root = pathlib.Path(sys.argv[1])
report_path = pathlib.Path(sys.argv[2])
schema_name = sys.argv[3]
schemas = {}
registry = Registry()
for path in (root / "schemas" / "0.1").glob("*.schema.json"):
    value = json.loads(path.read_text(encoding="utf-8"))
    schemas[path.name] = value
    registry = registry.with_resource(value["$id"], Resource.from_contents(value))
errors = sorted(
    Draft202012Validator(
        schemas[schema_name],
        registry=registry,
    ).iter_errors(json.loads(report_path.read_text(encoding="utf-8"))),
    key=lambda error: list(error.path),
)
if errors:
    raise SystemExit("; ".join(error.message for error in errors))
PY

if [[ "${A5CI_MODE}" == "true" ]]; then
  python3 - \
    "${ROOT_DIR}" \
    "${local_result_dir}/${REPORT_FILENAME}" \
    "${local_result_dir}/evaluation-traces.jsonl" \
    "${local_result_dir}/equivalence-report.json" \
    "${local_result_dir}/artifact-receipt.json" <<'PY'
import hashlib
import json
import pathlib
import sys

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


def identity(path):
    payload = path.read_bytes()
    return len(payload), f"sha256:{hashlib.sha256(payload).hexdigest()}"


root = pathlib.Path(sys.argv[1])
report_path = pathlib.Path(sys.argv[2])
trace_path = pathlib.Path(sys.argv[3])
equivalence_path = pathlib.Path(sys.argv[4])
receipt_path = pathlib.Path(sys.argv[5])
schemas = {}
registry = Registry()
for path in (root / "schemas" / "0.1").glob("*.schema.json"):
    value = json.loads(path.read_text(encoding="utf-8"))
    schemas[path.name] = value
    registry = registry.with_resource(value["$id"], Resource.from_contents(value))


def validate(schema_name, value, label):
    errors = sorted(
        Draft202012Validator(
            schemas[schema_name],
            registry=registry,
        ).iter_errors(value),
        key=lambda error: list(error.path),
    )
    if errors:
        raise SystemExit(
            f"{label}: " + "; ".join(error.message for error in errors)
        )


report = json.loads(report_path.read_text(encoding="utf-8"))
equivalence = json.loads(equivalence_path.read_text(encoding="utf-8"))
receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
validate(
    "h1-whole-body-equivalence-report.schema.json",
    equivalence,
    "equivalence report invalid",
)
validate(
    "h1-whole-body-diagnostic-replay-receipt.schema.json",
    receipt,
    "artifact receipt invalid",
)
records = []
with trace_path.open(encoding="utf-8") as stream:
    for line_number, line in enumerate(stream, 1):
        if not line.strip():
            continue
        record = json.loads(line)
        validate(
            "h1-whole-body-diagnostic-trace-record.schema.json",
            record,
            f"diagnostic trace line {line_number} invalid",
        )
        records.append(record)
if not records:
    raise SystemExit("diagnostic trace is empty")
if report["artifactTransferStatus"] != "passed":
    raise SystemExit("diagnostic replay artifact transfer is not passed")
if report["equivalenceAssessment"]["reportDigest"] != identity(equivalence_path)[1]:
    raise SystemExit("diagnostic replay equivalence report digest mismatch")
for name, path in (
    ("report", report_path),
    ("controller", report_path.parent / "whole-body-controller.json"),
    ("trace", trace_path),
    ("equivalence", equivalence_path),
):
    size, digest = identity(path)
    actual = receipt["artifacts"][name]
    if actual["sizeBytes"] != size or actual["digest"] != digest:
        raise SystemExit(f"diagnostic replay receipt {name} identity mismatch")
if receipt["attemptId"] != report["attemptId"]:
    raise SystemExit("diagnostic replay receipt/report attempt mismatch")
PY
fi

gate="$(
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' \
    "${local_result_dir}/${REPORT_FILENAME}" "${GATE_FIELD}"
)"
printf 'probe_gate=%s\nresult_dir=%s\n' "${gate}" "${local_result_dir}"
if [[ -n "${WORLD_SPEC_MIDTERM_RESULT_POINTER:-}" ]]; then
  printf '%s\n' "${local_result_dir}" >"${WORLD_SPEC_MIDTERM_RESULT_POINTER}"
fi
if [[ "${gate}" != "passed" ]]; then
  exit 3
fi
