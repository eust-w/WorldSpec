#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export WORLD_SPEC_PROBE_MODE=capacity_scale
export WORLD_SPEC_A800_TIMEOUT_SECONDS="${WORLD_SPEC_A800_TIMEOUT_SECONDS:-7200}"
exec "${ROOT_DIR}/scripts/run_a800_h1_locked_runtime_probe.sh" "$@"
