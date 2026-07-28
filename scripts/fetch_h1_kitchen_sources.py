#!/usr/bin/env python3
"""Materialize and verify locked H1 kitchen sources into a local cache.

The script never overwrites an existing output and does not execute downloaded
Python or model files. Git receives exact commit hashes from the committed lock.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / "third_party" / "h1-kitchen.lock.json"


class VerificationError(RuntimeError):
    pass


def read_lock(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("lockVersion") != "0.1.0":
        raise VerificationError("unsupported lockVersion")
    return document


def digest_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"


def safe_relative(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise VerificationError(f"unsafe locked path: {relative}")
    resolved = (root / candidate).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise VerificationError(f"locked path escapes repository: {relative}")
    return resolved


def tree_digest(repository: Path, relative: str) -> tuple[str, int]:
    tree_root = safe_relative(repository, relative)
    files = sorted(
        (path for path in tree_root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(repository).as_posix().encode("utf-8"),
    )
    hasher = hashlib.sha256()
    for path in files:
        if path.is_symlink():
            raise VerificationError(f"symlink is forbidden in locked tree: {path}")
        path_digest = digest_file(path).removeprefix("sha256:")
        relative_path = path.relative_to(repository).as_posix()
        hasher.update(f"{path_digest}  {relative_path}\n".encode())
    return f"sha256:{hasher.hexdigest()}", len(files)


def run(command: list[str], cwd: Path) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        raise VerificationError(
            f"command failed ({result.returncode}): {' '.join(command)}\n{result.stderr}"
        )


def verify_repository(repository: Path, source: dict[str, Any]) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or result.stdout.strip() != source["commit"]:
        raise VerificationError(f"{source['id']} HEAD does not match locked commit")

    verified_components = []
    for component in source["components"]:
        license_path = safe_relative(repository, component["license"]["path"])
        if digest_file(license_path) != component["license"]["digest"]:
            raise VerificationError(f"{component['id']} license digest mismatch")
        if component["kind"] == "tree":
            actual_digest, actual_count = tree_digest(repository, component["path"])
            if actual_digest != component["treeDigest"]:
                raise VerificationError(f"{component['id']} tree digest mismatch")
            if actual_count != component["fileCount"]:
                raise VerificationError(f"{component['id']} file count mismatch")
            verified_components.append(
                {
                    "id": component["id"],
                    "treeDigest": actual_digest,
                    "fileCount": actual_count,
                    "license": component["license"],
                }
            )
        elif component["kind"] == "files":
            verified_files = []
            for item in component["files"]:
                path = safe_relative(repository, item["path"])
                if path.is_symlink() or not path.is_file():
                    raise VerificationError(f"locked file is absent or a symlink: {item['path']}")
                if path.stat().st_size != item["sizeBytes"]:
                    raise VerificationError(f"locked file size mismatch: {item['path']}")
                actual = digest_file(path)
                if actual != item["digest"]:
                    raise VerificationError(f"locked file digest mismatch: {item['path']}")
                verified_files.append(item)
            verified_components.append(
                {
                    "id": component["id"],
                    "files": verified_files,
                    "license": component["license"],
                }
            )
        else:
            raise VerificationError(f"unsupported component kind: {component['kind']}")
    return {
        "id": source["id"],
        "repository": source["repository"],
        "commit": source["commit"],
        "components": verified_components,
    }


def materialize(lock: dict[str, Any], output: Path, lock_digest: str) -> dict[str, Any]:
    if output.exists():
        raise VerificationError(f"refusing to overwrite existing output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}.", dir=output.parent
    ) as temporary:
        staging = Path(temporary) / "payload"
        staging.mkdir()
        verified_sources = []
        for index, source in enumerate(lock["sources"]):
            repository = staging / "repositories" / f"source-{index}"
            repository.parent.mkdir(parents=True, exist_ok=True)
            run(
                [
                    "git",
                    "clone",
                    "--filter=blob:none",
                    "--no-tags",
                    "--no-checkout",
                    source["repository"],
                    str(repository),
                ],
                staging,
            )
            sparse_paths = sorted(
                {
                    component.get("path")
                    or str(Path(item["path"]).parent)
                    for component in source["components"]
                    for item in (component.get("files") or [{}])
                }
            )
            run(["git", "sparse-checkout", "init", "--cone"], repository)
            run(["git", "sparse-checkout", "set", *sparse_paths], repository)
            run(["git", "checkout", "--detach", source["commit"]], repository)
            verified_sources.append(verify_repository(repository, source))

        manifest = {
            "manifestVersion": "0.1.0",
            "lockDigest": lock_digest,
            "sources": verified_sources,
            "executionStatus": "verified_not_executed",
        }
        (staging / "verified-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        staging.rename(output)
        return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--verify-repository",
        type=Path,
        help="verify one existing repository against the matching --source-id",
    )
    parser.add_argument("--source-id")
    args = parser.parse_args()
    lock = read_lock(args.lock)
    if args.verify_repository:
        if not args.source_id:
            raise VerificationError("--source-id is required with --verify-repository")
        source = next(
            (item for item in lock["sources"] if item["id"] == args.source_id),
            None,
        )
        if source is None:
            raise VerificationError(f"unknown source id: {args.source_id}")
        print(json.dumps(verify_repository(args.verify_repository, source), sort_keys=True))
        return 0
    manifest = materialize(lock, args.output, digest_file(args.lock))
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
