#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KUBECONFIG_PATH="${KUBECONFIG:-/Users/d-robotics/.config/droboticflow/kubeconfigs/poc.config}"
K8S_NAMESPACE="${K8S_NAMESPACE:-droboticflow}"
JOB_TEMPLATE="${ROOT_DIR}/ops/a800/h1-training-image-build-job.yaml"
BASE_IMAGE="${WORLD_SPEC_A800_BASE_IMAGE:-ccr-29eug8s3-pub.cnc.bj.baidubce.com/dataflow-poc/real2sim-worker@sha256:d37f7e8a483518bdb447cd460b8c6dfb4407e385c1715b32a9d7f193a11dcdee}"
REVISION="${WORLD_SPEC_REVISION:-$(git -C "${ROOT_DIR}" rev-parse HEAD)}"
TIMEOUT_SECONDS="${WORLD_SPEC_IMAGE_BUILD_TIMEOUT_SECONDS:-3600}"
run_suffix="$(date -u +%Y%m%d%H%M%S)"
short_revision="${REVISION:0:12}"
DESTINATION="${WORLD_SPEC_H1_IMAGE_DESTINATION:-ccr-29eug8s3-pub.cnc.bj.baidubce.com/dataflow-poc/worldspec-h1-training:${short_revision}-${run_suffix}}"
CONTEXT_DIR="/workspace/system/builds/contexts/worldspec-h1-${short_revision}-${run_suffix}"

for required in "${KUBECONFIG_PATH}" "${JOB_TEMPLATE}"; do
  if [[ ! -r "${required}" ]]; then
    printf 'ERROR: required path is not readable: %s\n' "${required}" >&2
    exit 2
  fi
done
if ! [[ "${REVISION}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "ERROR: WORLD_SPEC_REVISION must be a full Git commit" >&2
  exit 2
fi
if ! [[ "${BASE_IMAGE}" =~ ^[^[:space:]@]+@sha256:[0-9a-f]{64}$ ]]; then
  echo "ERROR: WORLD_SPEC_A800_BASE_IMAGE must be pinned by sha256 digest" >&2
  exit 2
fi
if ! [[ "${DESTINATION}" =~ ^[^[:space:]@]+:[a-zA-Z0-9._-]+$ ]]; then
  echo "ERROR: WORLD_SPEC_H1_IMAGE_DESTINATION must be a tagged OCI reference" >&2
  exit 2
fi
if ! [[ "${TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: WORLD_SPEC_IMAGE_BUILD_TIMEOUT_SECONDS must be a positive integer" >&2
  exit 2
fi
if [[ -n "$(git -C "${ROOT_DIR}" status --porcelain)" ]]; then
  echo "ERROR: image build requires a clean worktree" >&2
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

package_lock_digest="$(
  python3 - "${ROOT_DIR}/python/worldspec-h1-training/uv.lock" <<'PY'
import hashlib
import pathlib
import sys

print(f"sha256:{hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()}")
PY
)"
context_digest="$(
  git -C "${ROOT_DIR}" archive --format=tar "${REVISION}" |
    python3 -c 'import hashlib,sys; print("sha256:" + hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'
)"

kubectl_cmd=(kubectl --kubeconfig "${KUBECONFIG_PATH}" -n "${K8S_NAMESPACE}")
api_pod="$(
  "${kubectl_cmd[@]}" get pods \
    -l app=droboticflow-api \
    --field-selector=status.phase=Running \
    -o jsonpath='{.items[0].metadata.name}'
)"
if [[ -z "${api_pod}" ]]; then
  echo "ERROR: no running droboticflow-api Pod is available for context upload" >&2
  exit 2
fi
for resource in \
  "pvc/droboticflow-workspace" \
  "secret/droboticflow-registry"; do
  "${kubectl_cmd[@]}" get "${resource}" >/dev/null
done
if [[ -n "$("${kubectl_cmd[@]}" get jobs -l app.kubernetes.io/name=worldspec-h1-image-build -o name)" ]]; then
  echo "ERROR: a WorldSpec H1 image build Job already exists" >&2
  exit 2
fi

temporary_manifest="$(mktemp "${TMPDIR:-/tmp}/worldspec-h1-build.XXXXXX.yaml")"
job_name=""
pod_name=""
local_result_dir=""
context_uploaded=false

cleanup_context() {
  local attempt cleanup_api_pod
  for attempt in 1 2 3; do
    cleanup_api_pod="$(
      "${kubectl_cmd[@]}" get pods \
        -l app=droboticflow-api \
        --field-selector=status.phase=Running \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true
    )"
    if [[ -z "${cleanup_api_pod}" ]]; then
      continue
    fi
    "${kubectl_cmd[@]}" exec "${cleanup_api_pod}" -- \
      rm -rf -- "${CONTEXT_DIR}" >/dev/null 2>&1 || true
    if "${kubectl_cmd[@]}" exec "${cleanup_api_pod}" -- \
      test ! -e "${CONTEXT_DIR}" >/dev/null 2>&1; then
      context_uploaded=false
      return 0
    fi
  done
  printf 'WARNING: temporary build context was not removed: %s\n' \
    "${CONTEXT_DIR}" >&2
  return 1
}

cleanup() {
  local exit_code=$?
  set +e
  if [[ -n "${job_name}" ]]; then
    "${kubectl_cmd[@]}" delete job "${job_name}" \
      --ignore-not-found --wait=true --timeout=180s >/dev/null 2>&1
  fi
  if [[ "${context_uploaded}" == "true" ]]; then
    cleanup_context || true
  fi
  rm -f "${temporary_manifest}"
  exit "${exit_code}"
}
trap cleanup EXIT INT TERM

"${kubectl_cmd[@]}" exec "${api_pod}" -- rm -rf -- "${CONTEXT_DIR}"
"${kubectl_cmd[@]}" exec "${api_pod}" -- mkdir -p -- "${CONTEXT_DIR}"
context_uploaded=true
git -C "${ROOT_DIR}" archive --format=tar "${REVISION}" |
  "${kubectl_cmd[@]}" exec -i "${api_pod}" -- \
    tar --no-same-owner -xf - -C "${CONTEXT_DIR}"

sed \
  -e "s|__CONTEXT_DIR__|${CONTEXT_DIR}|g" \
  -e "s|__DESTINATION__|${DESTINATION}|g" \
  -e "s|__BASE_IMAGE__|${BASE_IMAGE}|g" \
  -e "s|__WORLD_SPEC_REVISION__|${REVISION}|g" \
  -e "s|__PACKAGE_LOCK_DIGEST__|${package_lock_digest}|g" \
  "${JOB_TEMPLATE}" >"${temporary_manifest}"

job_resource="$("${kubectl_cmd[@]}" create -f "${temporary_manifest}" -o name)"
job_name="${job_resource#job.batch/}"
local_result_dir="${ROOT_DIR}/runs/a800/${job_name}"
mkdir -p "${local_result_dir}"
printf 'namespace=%s\njob=%s\nrevision=%s\ndestination=%s\ncontext_digest=%s\npackage_lock_digest=%s\nresult_dir=%s\n' \
  "${K8S_NAMESPACE}" \
  "${job_name}" \
  "${REVISION}" \
  "${DESTINATION}" \
  "${context_digest}" \
  "${package_lock_digest}" \
  "${local_result_dir}"

deadline=$((SECONDS + TIMEOUT_SECONDS))
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
    printf 'pod=%s phase=%s\n' "${pod_name}" "${phase}"
    if [[ "${phase}" == "Succeeded" ]] || [[ "${phase}" == "Failed" ]]; then
      break
    fi
  fi
  sleep 20
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
  echo "ERROR: the image build Job did not create a Pod" >&2
  exit 1
fi
phase="$(
  "${kubectl_cmd[@]}" get pod "${pod_name}" \
    -o jsonpath='{.status.phase}' 2>/dev/null || true
)"
if [[ "${phase}" != "Succeeded" ]]; then
  printf 'ERROR: image build Pod ended in phase %s; see %s\n' \
    "${phase:-unknown}" "${local_result_dir}" >&2
  exit 1
fi
image_digest="$(
  "${kubectl_cmd[@]}" get pod "${pod_name}" \
    -o jsonpath='{.status.containerStatuses[0].state.terminated.message}'
)"
if ! [[ "${image_digest}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  printf 'ERROR: Kaniko did not return an image digest: %s\n' "${image_digest}" >&2
  exit 1
fi
image_name="${DESTINATION%:*}"
image_ref="${image_name}@${image_digest}"

python3 - \
  "${local_result_dir}/image-build-report.json" \
  "${REVISION}" \
  "${context_digest}" \
  "${package_lock_digest}" \
  "${BASE_IMAGE}" \
  "${DESTINATION}" \
  "${image_ref}" <<'PY'
import datetime
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
report = {
    "reportVersion": "0.1.0",
    "status": "passed",
    "executionEvidence": "executed",
    "sourceCommit": sys.argv[2],
    "contextDigest": sys.argv[3],
    "packageLockDigest": sys.argv[4],
    "baseImage": sys.argv[5],
    "destinationTag": sys.argv[6],
    "image": sys.argv[7],
    "generatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
}
path.write_text(
    json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
PY
