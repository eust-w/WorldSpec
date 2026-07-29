#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export WORLD_SPEC_PROBE_MODE=ccd_iterations
export WORLD_SPEC_JOB_TEMPLATE="${ROOT_DIR}/ops/a800/h1-ccd-iterations-probe-job.yaml"

exec "${ROOT_DIR}/scripts/run_a800_h1_locked_runtime_probe.sh"
