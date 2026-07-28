"""Versioned worker execution with explicit failure semantics."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .cas import CasError, FileCas

Handler = Callable[[dict[str, Any], FileCas], list[dict[str, Any]]]


class WorkerFailure(RuntimeError):
    def __init__(
        self, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _result(
    job: dict[str, Any],
    status: str,
    outputs: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    started_at: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": f"jobresult://local/{job['id'].split('://', 1)[-1]}",
        "protocolVersion": "0.1.0",
        "jobRef": job["id"],
        "status": status,
        "outputs": outputs,
        "diagnostics": diagnostics,
        "startedAt": started_at,
        "finishedAt": _now(),
    }
    result["resultDigest"] = f"sha256:{hashlib.sha256(_canonical(result)).hexdigest()}"
    return result


def mock_handler(job: dict[str, Any], cas: FileCas) -> list[dict[str, Any]]:
    outputs = []
    for item in job["inputs"]:
        cas.read(item["digest"])
        outputs.append(
            {
                "id": item["id"].replace("artifact://", "artifact://mock/"),
                "digest": item["digest"],
                "mediaType": item["mediaType"],
                "path": f"mock/{Path(item['path']).name}",
                "role": "mock_ci_echo",
            }
        )
    return outputs


def run_job(
    job: dict[str, Any],
    cas_root: Path,
    handlers: dict[str, Handler] | None = None,
    allow_mock: bool = False,
) -> dict[str, Any]:
    started_at = _now()
    cas = FileCas(cas_root)
    handlers = dict(handlers or {})
    if allow_mock:
        handlers.setdefault(job["operation"], mock_handler)
    handler = handlers.get(job["operation"])
    if handler is None:
        return _result(
            job,
            "failed",
            [],
            [
                {
                    "code": "WORKER_HANDLER_UNAVAILABLE",
                    "severity": "error",
                    "message": f"No real handler is installed for {job['operation']}.",
                    "details": {"mockAllowed": False},
                }
            ],
            started_at,
        )
    try:
        return _result(job, "succeeded", handler(job, cas), [], started_at)
    except WorkerFailure as error:
        diagnostic: dict[str, Any] = {
            "code": error.code,
            "severity": "error",
            "message": str(error),
        }
        if error.details:
            diagnostic["details"] = error.details
        return _result(job, "failed", [], [diagnostic], started_at)
    except (CasError, OSError, ValueError, KeyError) as error:
        return _result(
            job,
            "failed",
            [],
            [
                {
                    "code": "WORKER_EXECUTION_FAILED",
                    "severity": "error",
                    "message": str(error),
                }
            ],
            started_at,
        )
