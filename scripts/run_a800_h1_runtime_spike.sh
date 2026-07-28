#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KUBECONFIG_PATH="${KUBECONFIG:-/Users/d-robotics/.config/droboticflow/kubeconfigs/poc.config}"
K8S_NAMESPACE="${K8S_NAMESPACE:-worldspec-a800-poc}"
NAMESPACE_MANIFEST="${ROOT_DIR}/ops/a800/namespace.yaml"
JOB_TEMPLATE="${ROOT_DIR}/ops/a800/h1-runtime-spike-job.yaml"
ENTRYPOINT="${ROOT_DIR}/ops/a800/h1-runtime-spike-entrypoint.sh"
BASE_IMAGE="${WORLD_SPEC_A800_BASE_IMAGE:-ccr-29eug8s3-pub.cnc.bj.baidubce.com/dataflow-poc/real2sim-worker@sha256:d37f7e8a483518bdb447cd460b8c6dfb4407e385c1715b32a9d7f193a11dcdee}"
TIMEOUT_SECONDS="${WORLD_SPEC_A800_TIMEOUT_SECONDS:-7200}"
REVISION="${WORLD_SPEC_REVISION:-$(git -C "${ROOT_DIR}" rev-parse HEAD)}"

for required in \
  "${KUBECONFIG_PATH}" \
  "${NAMESPACE_MANIFEST}" \
  "${JOB_TEMPLATE}" \
  "${ENTRYPOINT}"; do
  if [[ ! -r "${required}" ]]; then
    printf 'ERROR: required path is not readable: %s\n' "${required}" >&2
    exit 2
  fi
done
if ! [[ "${TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: WORLD_SPEC_A800_TIMEOUT_SECONDS must be a positive integer" >&2
  exit 2
fi
if ! [[ "${REVISION}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "ERROR: WORLD_SPEC_REVISION must be a full Git commit" >&2
  exit 2
fi
if ! [[ "${BASE_IMAGE}" =~ ^[^[:space:]@]+@sha256:[0-9a-f]{64}$ ]]; then
  echo "ERROR: WORLD_SPEC_A800_BASE_IMAGE must be pinned by sha256 digest" >&2
  exit 2
fi

remote_revision="$(
  git ls-remote https://github.com/eust-w/WorldSpec.git \
    "refs/heads/feature/worldspec-v0.1" |
    awk '{print $1}'
)"
if [[ "${remote_revision}" != "${REVISION}" ]]; then
  printf 'ERROR: revision is not the current remote feature branch head: local=%s remote=%s\n' \
    "${REVISION}" "${remote_revision}" >&2
  exit 2
fi

kubectl_cmd=(kubectl --kubeconfig "${KUBECONFIG_PATH}" -n "${K8S_NAMESPACE}")
context="$(kubectl --kubeconfig "${KUBECONFIG_PATH}" config current-context)"
if [[ -z "${context}" ]]; then
  echo "ERROR: kubeconfig has no current context" >&2
  exit 2
fi

kubectl --kubeconfig "${KUBECONFIG_PATH}" apply -f "${NAMESPACE_MANIFEST}" >/dev/null

existing="$(
  "${kubectl_cmd[@]}" get jobs \
    -l app.kubernetes.io/name=worldspec-h1-runtime-spike \
    -o name
)"
if [[ -n "${existing}" ]]; then
  echo "ERROR: a WorldSpec H1 runtime spike Job already exists" >&2
  printf '%s\n' "${existing}" >&2
  exit 2
fi

short_revision="${REVISION:0:12}"
run_suffix="$(date -u +%Y%m%d%H%M%S)"
configmap_name="worldspec-h1-spike-${short_revision}-${run_suffix}"
source_configmap_name="worldspec-h1-source-${short_revision}-${run_suffix}"
temporary_manifest="$(mktemp "${TMPDIR:-/tmp}/worldspec-h1-spike.XXXXXX.yaml")"
source_archive="$(mktemp "${TMPDIR:-/tmp}/worldspec-source.XXXXXX.tar.gz")"
job_name=""
pod_name=""
local_result_dir=""

cleanup() {
  local exit_code=$?
  set +e
  if [[ -n "${job_name}" ]]; then
    "${kubectl_cmd[@]}" delete job "${job_name}" \
      --ignore-not-found --wait=true --timeout=180s >/dev/null 2>&1
  fi
  "${kubectl_cmd[@]}" delete configmap "${configmap_name}" \
    --ignore-not-found >/dev/null 2>&1
  "${kubectl_cmd[@]}" delete configmap "${source_configmap_name}" \
    --ignore-not-found >/dev/null 2>&1
  rm -f "${temporary_manifest}" "${source_archive}"
  exit "${exit_code}"
}
trap cleanup EXIT INT TERM

if [[ -n "$(git -C "${ROOT_DIR}" status --porcelain)" ]]; then
  echo "ERROR: source archive requires a clean worktree" >&2
  exit 2
fi
git -C "${ROOT_DIR}" archive --format=tar "${REVISION}" | gzip -n -9 >"${source_archive}"
source_archive_digest="$(
  python3 - "${source_archive}" <<'PY'
import hashlib
import pathlib
import sys

print(f"sha256:{hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()}")
PY
)"

"${kubectl_cmd[@]}" create configmap "${configmap_name}" \
  --from-file="run.sh=${ENTRYPOINT}" >/dev/null
"${kubectl_cmd[@]}" create configmap "${source_configmap_name}" \
  --from-file="worldspec.tar.gz=${source_archive}" >/dev/null

sed \
  -e "s|__BASE_IMAGE__|${BASE_IMAGE}|g" \
  -e "s|__WORLD_SPEC_REVISION__|${REVISION}|g" \
  -e "s|__SCRIPT_CONFIGMAP__|${configmap_name}|g" \
  -e "s|__SOURCE_CONFIGMAP__|${source_configmap_name}|g" \
  -e "s|__SOURCE_ARCHIVE_DIGEST__|${source_archive_digest}|g" \
  "${JOB_TEMPLATE}" >"${temporary_manifest}"

job_resource="$("${kubectl_cmd[@]}" create -f "${temporary_manifest}" -o name)"
job_name="${job_resource#job.batch/}"
local_result_dir="${ROOT_DIR}/runs/a800/${job_name}"
mkdir -p "${local_result_dir}"

printf 'context=%s\nnamespace=%s\njob=%s\nrevision=%s\nresult_dir=%s\n' \
  "${context}" "${K8S_NAMESPACE}" "${job_name}" "${REVISION}" "${local_result_dir}"
printf 'source_archive_digest=%s\n' "${source_archive_digest}"

deadline=$((SECONDS + TIMEOUT_SECONDS))
last_stage=""
while ((SECONDS < deadline)); do
  pod_name="$(
    "${kubectl_cmd[@]}" get pods -l "job-name=${job_name}" \
      -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true
  )"
  if [[ -n "${pod_name}" ]]; then
    phase="$(
      "${kubectl_cmd[@]}" get pod "${pod_name}" \
        -o jsonpath='{.status.phase}' 2>/dev/null || true
    )"
    pod_log="$("${kubectl_cmd[@]}" logs "${pod_name}" 2>/dev/null || true)"
    current_stage="$(
      awk -F= '/^WORLDSPEC_A800_SPIKE_STAGE=/{value=$2} END{print value}' \
        <<<"${pod_log}"
    )"
    if [[ -n "${current_stage}" ]] && [[ "${current_stage}" != "${last_stage}" ]]; then
      printf 'pod=%s phase=%s stage=%s\n' "${pod_name}" "${phase}" "${current_stage}"
      last_stage="${current_stage}"
    fi
    if [[ "${phase}" == "Succeeded" ]] || [[ "${phase}" == "Failed" ]]; then
      break
    fi
  fi
  sleep 10
done

if [[ -n "${pod_name}" ]]; then
  "${kubectl_cmd[@]}" logs "${pod_name}" >"${local_result_dir}/job.log" 2>&1 || true
  "${kubectl_cmd[@]}" get pod "${pod_name}" -o yaml \
    >"${local_result_dir}/pod.yaml" 2>/dev/null || true
  "${kubectl_cmd[@]}" describe pod "${pod_name}" \
    >"${local_result_dir}/pod-describe.txt" 2>/dev/null || true
fi
"${kubectl_cmd[@]}" get job "${job_name}" -o yaml \
  >"${local_result_dir}/job.yaml" 2>/dev/null || true

if [[ -z "${pod_name}" ]]; then
  echo "ERROR: the spike Job did not create a Pod" >&2
  exit 1
fi
phase="$(
  "${kubectl_cmd[@]}" get pod "${pod_name}" \
    -o jsonpath='{.status.phase}' 2>/dev/null || true
)"
if [[ "${phase}" != "Succeeded" ]]; then
  printf 'ERROR: spike Pod ended in phase %s; see %s\n' \
    "${phase:-unknown}" "${local_result_dir}" >&2
  exit 1
fi

python3 - "${local_result_dir}/job.log" \
  "${local_result_dir}/runtime-spike-report.json" \
  "${REVISION}" <<'PY'
import json
import pathlib
import sys

log_path = pathlib.Path(sys.argv[1])
report_path = pathlib.Path(sys.argv[2])
expected_revision = sys.argv[3]
prefix = "WORLDSPEC_A800_SPIKE_RESULT="
matches = [
    line[len(prefix):]
    for line in log_path.read_text(encoding="utf-8").splitlines()
    if line.startswith(prefix)
]
if len(matches) != 1:
    raise SystemExit(f"expected one result marker, found {len(matches)}")
report = json.loads(matches[0])
if report.get("status") != "passed":
    raise SystemExit(f"unexpected spike status: {report.get('status')!r}")
if report.get("source", {}).get("commit") != expected_revision:
    raise SystemExit("spike result is bound to the wrong source revision")
if report.get("runtimeAcceptance") != "executed_not_locked":
    raise SystemExit("spike must not claim a locked runtime")
one_step = report.get("oneStep", {})
required = ("observationFinite", "qposFinite", "qvelFinite", "rewardFinite")
if any(one_step.get(key) is not True for key in required):
    raise SystemExit("spike finite-state evidence is incomplete")
report_path.write_text(
    json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(json.dumps({
    "status": report["status"],
    "scope": report["scope"],
    "runtimeAcceptance": report["runtimeAcceptance"],
    "gpu": report["gpu"]["name"],
    "jaxBackend": report["gpu"]["jaxBackend"],
    "derivedModelDigest": report["target"]["derivedModelDigest"],
    "result": str(report_path),
}, ensure_ascii=False))
PY
