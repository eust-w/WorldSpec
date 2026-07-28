#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KUBECONFIG_PATH="${KUBECONFIG:-/Users/d-robotics/.config/droboticflow/kubeconfigs/poc.config}"
K8S_NAMESPACE="${K8S_NAMESPACE:-worldspec-a800-poc}"
BUILD_NAMESPACE="${WORLD_SPEC_BUILD_NAMESPACE:-droboticflow}"
NAMESPACE_MANIFEST="${ROOT_DIR}/ops/a800/namespace.yaml"
JOB_TEMPLATE="${ROOT_DIR}/ops/a800/h1-locked-runtime-probe-job.yaml"
PREPULL_TEMPLATE="${ROOT_DIR}/ops/a800/h1-training-image-prepull-job.yaml"
ENTRYPOINT="${ROOT_DIR}/ops/a800/h1-locked-runtime-probe-entrypoint.sh"
RUNTIME_IMAGE="${WORLD_SPEC_H1_RUNTIME_IMAGE:-ccr-29eug8s3-pub.cnc.bj.baidubce.com/dataflow-poc/worldspec-h1-training@sha256:576c564be62a0319be0862fa2f8ca7bd344ed100a46f5c34c4d4d5ae1774058f}"
IMAGE_SOURCE_REVISION="${WORLD_SPEC_IMAGE_SOURCE_REVISION:-e8b8e9219ccec382d5b20005738d38b9790de230}"
PACKAGE_LOCK_DIGEST="${WORLD_SPEC_PACKAGE_LOCK_DIGEST:-sha256:7cc88f20b2c608d6fe673f3b994b879db69d75361206bf25f949d7acc5ed3a41}"
PROBE_REVISION="${WORLD_SPEC_PROBE_DEFINITION_REVISION:-$(git -C "${ROOT_DIR}" rev-parse HEAD)}"
TIMEOUT_SECONDS="${WORLD_SPEC_A800_TIMEOUT_SECONDS:-3600}"

for required in \
  "${KUBECONFIG_PATH}" \
  "${NAMESPACE_MANIFEST}" \
  "${JOB_TEMPLATE}" \
  "${PREPULL_TEMPLATE}" \
  "${ENTRYPOINT}"; do
  if [[ ! -r "${required}" ]]; then
    printf 'ERROR: required path is not readable: %s\n' "${required}" >&2
    exit 2
  fi
done
if ! [[ "${RUNTIME_IMAGE}" =~ ^[^[:space:]@]+@sha256:[0-9a-f]{64}$ ]]; then
  echo "ERROR: WORLD_SPEC_H1_RUNTIME_IMAGE must be pinned by sha256 digest" >&2
  exit 2
fi
if ! [[ "${IMAGE_SOURCE_REVISION}" =~ ^[0-9a-f]{40}$ ]] ||
  ! [[ "${PROBE_REVISION}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "ERROR: source and probe revisions must be full Git commits" >&2
  exit 2
fi
if ! [[ "${PACKAGE_LOCK_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "ERROR: WORLD_SPEC_PACKAGE_LOCK_DIGEST must be a sha256 digest" >&2
  exit 2
fi
if ! [[ "${TIMEOUT_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: WORLD_SPEC_A800_TIMEOUT_SECONDS must be a positive integer" >&2
  exit 2
fi
if [[ -n "$(git -C "${ROOT_DIR}" status --porcelain)" ]]; then
  echo "ERROR: locked runtime probe requires a clean worktree" >&2
  exit 2
fi
git -C "${ROOT_DIR}" cat-file -e "${IMAGE_SOURCE_REVISION}^{commit}"
git -C "${ROOT_DIR}" merge-base --is-ancestor \
  "${IMAGE_SOURCE_REVISION}" "${PROBE_REVISION}"
remote_revision="$(
  git ls-remote https://github.com/eust-w/WorldSpec.git \
    "refs/heads/feature/worldspec-v0.1" |
    awk '{print $1}'
)"
if [[ "${remote_revision}" != "${PROBE_REVISION}" ]]; then
  printf 'ERROR: probe revision is not the remote feature head: local=%s remote=%s\n' \
    "${PROBE_REVISION}" "${remote_revision}" >&2
  exit 2
fi

kubectl_cmd=(kubectl --kubeconfig "${KUBECONFIG_PATH}" -n "${K8S_NAMESPACE}")
build_kubectl_cmd=(
  kubectl --kubeconfig "${KUBECONFIG_PATH}" -n "${BUILD_NAMESPACE}"
)
kubectl --kubeconfig "${KUBECONFIG_PATH}" apply -f "${NAMESPACE_MANIFEST}" >/dev/null
if [[ -n "$("${kubectl_cmd[@]}" get jobs \
  -l app.kubernetes.io/name=worldspec-h1-locked-runtime-probe -o name)" ]]; then
  echo "ERROR: a WorldSpec locked runtime probe Job already exists" >&2
  exit 2
fi

run_suffix="$(date -u +%Y%m%d%H%M%S)"
short_revision="${PROBE_REVISION:0:12}"
script_configmap="worldspec-h1-locked-script-${short_revision}-${run_suffix}"
source_configmap="worldspec-h1-locked-source-${short_revision}-${run_suffix}"
temporary_manifest="$(mktemp "${TMPDIR:-/tmp}/worldspec-h1-locked.XXXXXX.yaml")"
prepull_manifest="$(mktemp "${TMPDIR:-/tmp}/worldspec-h1-prepull.XXXXXX.yaml")"
source_archive="$(mktemp "${TMPDIR:-/tmp}/worldspec-source.XXXXXX.tar.gz")"
prepull_job=""
prepull_pod=""
job_name=""
pod_name=""
local_result_dir=""

cleanup() {
  local exit_code=$?
  set +e
  if [[ -n "${prepull_job}" ]]; then
    "${build_kubectl_cmd[@]}" delete job "${prepull_job}" \
      --ignore-not-found --wait=true --timeout=180s >/dev/null 2>&1
  fi
  if [[ -n "${job_name}" ]]; then
    "${kubectl_cmd[@]}" delete job "${job_name}" \
      --ignore-not-found --wait=true --timeout=180s >/dev/null 2>&1
  fi
  "${kubectl_cmd[@]}" delete configmap "${script_configmap}" \
    --ignore-not-found >/dev/null 2>&1
  "${kubectl_cmd[@]}" delete configmap "${source_configmap}" \
    --ignore-not-found >/dev/null 2>&1
  rm -f "${temporary_manifest}" "${prepull_manifest}" "${source_archive}"
  exit "${exit_code}"
}
trap cleanup EXIT INT TERM

if [[ -n "$("${build_kubectl_cmd[@]}" get jobs \
  -l app.kubernetes.io/name=worldspec-h1-image-prepull -o name)" ]]; then
  echo "ERROR: a WorldSpec H1 image pre-pull Job already exists" >&2
  exit 2
fi
sed -e "s|__RUNTIME_IMAGE__|${RUNTIME_IMAGE}|g" \
  "${PREPULL_TEMPLATE}" >"${prepull_manifest}"
prepull_resource="$("${build_kubectl_cmd[@]}" create \
  -f "${prepull_manifest}" -o name)"
prepull_job="${prepull_resource#job.batch/}"
printf 'prepull_namespace=%s\nprepull_job=%s\n' \
  "${BUILD_NAMESPACE}" "${prepull_job}"
if ! "${build_kubectl_cmd[@]}" wait \
  --for=condition=complete "job/${prepull_job}" --timeout=1800s >/dev/null; then
  prepull_pod="$("${build_kubectl_cmd[@]}" get pods \
    -l "job-name=${prepull_job}" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  if [[ -n "${prepull_pod}" ]]; then
    "${build_kubectl_cmd[@]}" describe pod "${prepull_pod}" >&2 || true
    "${build_kubectl_cmd[@]}" logs "${prepull_pod}" >&2 || true
  fi
  echo "ERROR: digest-pinned image pre-pull failed" >&2
  exit 1
fi
"${build_kubectl_cmd[@]}" delete job "${prepull_job}" \
  --wait=true --timeout=180s >/dev/null
prepull_job=""

git -C "${ROOT_DIR}" archive --format=tar "${IMAGE_SOURCE_REVISION}" |
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
  -e "s|__PACKAGE_LOCK_DIGEST__|${PACKAGE_LOCK_DIGEST}|g" \
  -e "s|__SOURCE_ARCHIVE_DIGEST__|${source_archive_digest}|g" \
  -e "s|__SCRIPT_CONFIGMAP__|${script_configmap}|g" \
  -e "s|__SOURCE_CONFIGMAP__|${source_configmap}|g" \
  "${JOB_TEMPLATE}" >"${temporary_manifest}"

job_resource="$("${kubectl_cmd[@]}" create -f "${temporary_manifest}" -o name)"
job_name="${job_resource#job.batch/}"
local_result_dir="${ROOT_DIR}/runs/a800/${job_name}"
mkdir -p "${local_result_dir}"
printf 'namespace=%s\njob=%s\nprobe_revision=%s\nimage_source_revision=%s\nimage=%s\nresult_dir=%s\n' \
  "${K8S_NAMESPACE}" "${job_name}" "${PROBE_REVISION}" \
  "${IMAGE_SOURCE_REVISION}" "${RUNTIME_IMAGE}" "${local_result_dir}"

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
      '/^WORLDSPEC_A800_LOCKED_PROBE_STAGE=/{value=$2} END{print value}' \
      <<<"${pod_log}")"
    if [[ -n "${current_stage}" ]] && [[ "${current_stage}" != "${last_stage}" ]]; then
      printf 'pod=%s phase=%s stage=%s\n' \
        "${pod_name}" "${phase}" "${current_stage}"
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
  echo "ERROR: locked runtime probe did not create a Pod" >&2
  exit 1
fi
phase="$("${kubectl_cmd[@]}" get pod "${pod_name}" \
  -o jsonpath='{.status.phase}' 2>/dev/null || true)"
if [[ "${phase}" != "Succeeded" ]]; then
  printf 'ERROR: locked probe ended in phase %s; see %s\n' \
    "${phase:-unknown}" "${local_result_dir}" >&2
  exit 1
fi

python3 - "${local_result_dir}/job.log" \
  "${local_result_dir}/locked-runtime-report.json" \
  "${PROBE_REVISION}" "${IMAGE_SOURCE_REVISION}" "${RUNTIME_IMAGE}" <<'PY'
import json
import pathlib
import sys

log_path = pathlib.Path(sys.argv[1])
report_path = pathlib.Path(sys.argv[2])
prefix = "WORLDSPEC_A800_LOCKED_PROBE_RESULT="
matches = [
    line[len(prefix):]
    for line in log_path.read_text(encoding="utf-8").splitlines()
    if line.startswith(prefix)
]
if len(matches) != 1:
    raise SystemExit(f"expected one result marker, found {len(matches)}")
report = json.loads(matches[0])
if report.get("status") != "passed" or report.get("runtimeAcceptance") != "locked":
    raise SystemExit("locked runtime probe did not pass")
if report.get("probeDefinition", {}).get("commit") != sys.argv[3]:
    raise SystemExit("probe definition revision mismatch")
if report.get("imageSource", {}).get("commit") != sys.argv[4]:
    raise SystemExit("image source revision mismatch")
if report.get("container", {}).get("image") != sys.argv[5]:
    raise SystemExit("runtime image mismatch")
report_path.write_text(
    json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(json.dumps({
    "status": report["status"],
    "runtimeAcceptance": report["runtimeAcceptance"],
    "image": report["container"]["image"],
    "gpu": report["gpu"]["name"],
    "jaxBackend": report["gpu"]["jaxBackend"],
    "derivedModelDigest": report["target"]["derivedModelDigest"],
    "result": str(report_path),
}, ensure_ascii=False))
PY
