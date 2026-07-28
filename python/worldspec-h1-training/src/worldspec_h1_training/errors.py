"""Typed failures for the H1 training boundary."""

from __future__ import annotations

from typing import Any


class TrainingError(RuntimeError):
    """A fail-closed error with a stable machine-readable code."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
