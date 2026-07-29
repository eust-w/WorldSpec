"""Upload one file through bounded kubectl exec chunks with digest verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath


class ChunkUploadError(RuntimeError):
    """Raised when a local or remote upload identity cannot be verified."""


RunCommand = Callable[..., subprocess.CompletedProcess[bytes]]
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _safe_remote_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or value.endswith("/")
        or any(part in ("", ".") for part in path.parts[1:])
    ):
        raise ChunkUploadError("remote path must be an absolute normalized file path")
    return value


def upload_to_pod(
    *,
    command_prefix: Sequence[str],
    pod: str,
    container: str,
    source: Path,
    remote_path: str,
    expected_size: int,
    expected_digest: str,
    chunk_size: int = 512 * 1024,
    retries: int = 4,
    run: RunCommand = subprocess.run,
) -> dict[str, object]:
    """Upload independent chunks, then verify the complete remote file."""

    remote_path = _safe_remote_path(remote_path)
    payload = source.read_bytes()
    actual_digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    if len(payload) != expected_size or actual_digest != expected_digest:
        raise ChunkUploadError(
            "local source identity mismatch: "
            f"size={len(payload)}/{expected_size} "
            f"digest={actual_digest}/{expected_digest}"
        )
    if chunk_size < 1 or retries < 1:
        raise ChunkUploadError("chunk size and retries must be positive")
    truncate = run(
        [
            *command_prefix,
            "exec",
            pod,
            "-c",
            container,
            "--",
            "truncate",
            "-s",
            "0",
            remote_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if truncate.returncode != 0:
        raise ChunkUploadError(
            "cannot initialize remote file: "
            + truncate.stderr.decode(errors="replace").strip()
        )

    chunk_count = (expected_size + chunk_size - 1) // chunk_size
    for index in range(chunk_count):
        chunk = payload[index * chunk_size : (index + 1) * chunk_size]
        chunk_digest = hashlib.sha256(chunk).hexdigest()
        command = [
            *command_prefix,
            "exec",
            "-i",
            pod,
            "-c",
            container,
            "--",
            "sh",
            "-ceu",
            (
                'temporary="$(mktemp "$1.worldspec-upload.XXXXXX")"\n'
                "trap 'rm -f \"$temporary\"' EXIT HUP INT TERM\n"
                'cat >"$temporary"\n'
                'actual_size="$(stat -c %s "$temporary")"\n'
                'actual_digest="$(sha256sum "$temporary" | cut -d " " -f 1)"\n'
                'test "$actual_size" = "$2"\n'
                'test "$actual_digest" = "$3"\n'
                'dd if="$temporary" of="$1" bs="$4" seek="$5" '
                "count=1 conv=notrunc status=none"
            ),
            "worldspec-upload-chunk",
            remote_path,
            str(len(chunk)),
            chunk_digest,
            str(chunk_size),
            str(index),
        ]
        last_error = ""
        for _ in range(retries):
            completed = run(
                command,
                input=chunk,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if completed.returncode == 0:
                break
            last_error = (
                f"returncode={completed.returncode} "
                f"stderr={completed.stderr.decode(errors='replace').strip()}"
            )
        else:
            raise ChunkUploadError(
                f"chunk {index + 1}/{chunk_count} failed after "
                f"{retries} attempts: {last_error}"
            )

    verify = run(
        [
            *command_prefix,
            "exec",
            pod,
            "-c",
            container,
            "--",
            "sh",
            "-ceu",
            'printf "%s %s\\n" "$(stat -c %s "$1")" "$(sha256sum "$1" | cut -d " " -f 1)"',
            "worldspec-upload-verify",
            remote_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if verify.returncode != 0:
        raise ChunkUploadError(
            "cannot verify remote file: "
            + verify.stderr.decode(errors="replace").strip()
        )
    try:
        remote_size_text, remote_digest = verify.stdout.decode().strip().split()
        remote_size = int(remote_size_text)
    except (UnicodeDecodeError, ValueError) as error:
        raise ChunkUploadError("remote verification output is invalid") from error
    if (
        remote_size != expected_size
        or not _DIGEST.fullmatch(remote_digest)
        or f"sha256:{remote_digest}" != expected_digest
    ):
        raise ChunkUploadError(
            "remote artifact identity mismatch: "
            f"size={remote_size}/{expected_size} "
            f"digest=sha256:{remote_digest}/{expected_digest}"
        )
    return {
        "status": "verified",
        "path": remote_path,
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
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--remote-path", required=True)
    parser.add_argument("--expected-size", type=int, required=True)
    parser.add_argument("--expected-digest", required=True)
    parser.add_argument("--chunk-size", type=int, default=512 * 1024)
    parser.add_argument("--retries", type=int, default=4)
    args = parser.parse_args()
    result = upload_to_pod(
        command_prefix=[
            "kubectl",
            "--kubeconfig",
            args.kubeconfig,
            "-n",
            args.namespace,
        ],
        pod=args.pod,
        container=args.container,
        source=args.source,
        remote_path=args.remote_path,
        expected_size=args.expected_size,
        expected_digest=args.expected_digest,
        chunk_size=args.chunk_size,
        retries=args.retries,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
