"""CLI for a single isolated WorldSpec JobSpec."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapters import ADAPTERS, adapter
from .runner import run_job


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="worldspec-worker")
    result.add_argument("--job", type=Path, required=True)
    result.add_argument("--result", type=Path, required=True)
    result.add_argument("--cas-root", type=Path, required=True)
    mode = result.add_mutually_exclusive_group()
    mode.add_argument(
        "--mock",
        action="store_true",
        help="CI-only echo handler; never accepted as generation or certification evidence.",
    )
    mode.add_argument(
        "--adapter",
        choices=sorted(ADAPTERS),
        help="Run one real optional adapter; missing native dependencies fail explicitly.",
    )
    return result


def main() -> int:
    arguments = parser().parse_args()
    job = json.loads(arguments.job.read_text(encoding="utf-8"))
    handlers = (
        {job["operation"]: adapter(arguments.adapter)} if arguments.adapter else None
    )
    outcome = run_job(
        job, arguments.cas_root, handlers=handlers, allow_mock=arguments.mock
    )
    arguments.result.parent.mkdir(parents=True, exist_ok=True)
    arguments.result.write_text(
        json.dumps(outcome, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return 0 if outcome["status"] == "succeeded" else 1
