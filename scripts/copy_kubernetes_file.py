"""Copy one Pod file through bounded kubectl exec chunks with digest verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path


class ChunkCopyError(RuntimeError):
    """Raised when a remote chunk or the final artifact cannot be verified."""


RunCommand = Callable[..., subprocess.CompletedProcess[bytes]]


def copy_from_pod(
    *,
    command_prefix: Sequence[str],
    pod: str,
    container: str,
    remote_path: str,
    destination: Path,
    expected_size: int,
    expected_digest: str,
    chunk_size: int = 512 * 1024,
    retries: int = 4,
    run: RunCommand = subprocess.run,
) -> dict[str, object]:
    """Copy a file in independent chunks and verify its complete identity."""

    if expected_size < 1:
        raise ChunkCopyError("expected size must be positive")
    if (
        not expected_digest.startswith("sha256:")
        or len(expected_digest) != len("sha256:") + 64
    ):
        raise ChunkCopyError("expected digest must be a sha256 digest")
    if chunk_size < 1 or retries < 1:
        raise ChunkCopyError("chunk size and retries must be positive")

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    partial.unlink(missing_ok=True)
    hasher = hashlib.sha256()
    chunk_count = (expected_size + chunk_size - 1) // chunk_size
    try:
        with partial.open("wb") as output:
            for index in range(chunk_count):
                expected_chunk_size = min(
                    chunk_size,
                    expected_size - index * chunk_size,
                )
                command = [
                    *command_prefix,
                    "exec",
                    pod,
                    "-c",
                    container,
                    "--",
                    "dd",
                    f"if={remote_path}",
                    f"bs={chunk_size}",
                    f"skip={index}",
                    "count=1",
                    "status=none",
                ]
                last_error = ""
                payload: bytes | None = None
                for _ in range(retries):
                    completed = run(
                        command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False,
                    )
                    candidate = completed.stdout
                    if completed.returncode == 0 and len(candidate) == expected_chunk_size:
                        payload = candidate
                        break
                    last_error = (
                        f"returncode={completed.returncode} "
                        f"bytes={len(candidate)}/{expected_chunk_size} "
                        f"stderr={completed.stderr.decode(errors='replace').strip()}"
                    )
                if payload is None:
                    raise ChunkCopyError(
                        f"chunk {index + 1}/{chunk_count} failed after "
                        f"{retries} attempts: {last_error}"
                    )
                output.write(payload)
                hasher.update(payload)
            output.flush()
            os.fsync(output.fileno())
        actual_size = partial.stat().st_size
        actual_digest = f"sha256:{hasher.hexdigest()}"
        if actual_size != expected_size or actual_digest != expected_digest:
            raise ChunkCopyError(
                "copied artifact identity mismatch: "
                f"size={actual_size}/{expected_size} "
                f"digest={actual_digest}/{expected_digest}"
            )
        os.replace(partial, destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return {
        "status": "verified",
        "path": str(destination),
        "sizeBytes": expected_size,
        "digest": expected_digest,
        "chunkSizeBytes": chunk_size,
        "chunkCount": chunk_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--pod", required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--remote-path", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--expected-size", type=int, required=True)
    parser.add_argument("--expected-digest", required=True)
    parser.add_argument("--chunk-size", type=int, default=512 * 1024)
    parser.add_argument("--retries", type=int, default=4)
    args = parser.parse_args()
    result = copy_from_pod(
        command_prefix=[
            "kubectl",
            "--kubeconfig",
            args.kubeconfig,
            "-n",
            args.namespace,
        ],
        pod=args.pod,
        container=args.container,
        remote_path=args.remote_path,
        destination=args.destination,
        expected_size=args.expected_size,
        expected_digest=args.expected_digest,
        chunk_size=args.chunk_size,
        retries=args.retries,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
