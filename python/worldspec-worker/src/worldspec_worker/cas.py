"""Read-only/append-only access to the WorldSpec file CAS."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


class CasError(RuntimeError):
    pass


def _hex_digest(digest: str) -> str:
    prefix = "sha256:"
    if not digest.startswith(prefix):
        raise CasError(f"unsupported digest: {digest}")
    value = digest[len(prefix) :]
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise CasError(f"invalid SHA-256 digest: {digest}")
    return value


class FileCas:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        (self.root / "objects" / "sha256").mkdir(parents=True, exist_ok=True)
        (self.root / "tmp").mkdir(parents=True, exist_ok=True)

    def path(self, digest: str) -> Path:
        value = _hex_digest(digest)
        return self.root / "objects" / "sha256" / value[:2] / value[2:]

    def read(self, digest: str) -> bytes:
        path = self.path(digest)
        try:
            payload = path.read_bytes()
        except FileNotFoundError as error:
            raise CasError(f"CAS object not found: {digest}") from error
        actual = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        if actual != digest:
            raise CasError(f"CAS object failed digest verification: {digest}")
        return payload

    def put(self, payload: bytes) -> str:
        digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        target = self.path(digest)
        if target.exists():
            if self.read(digest) != payload:
                raise CasError(f"CAS collision: {digest}")
            return digest
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix="worker-", dir=self.root / "tmp")
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                temporary.replace(target)
            except FileExistsError:
                temporary.unlink(missing_ok=True)
        finally:
            temporary.unlink(missing_ok=True)
        return digest
