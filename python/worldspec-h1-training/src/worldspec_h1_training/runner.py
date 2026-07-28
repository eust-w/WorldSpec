"""Public training entry point used by the isolated worker."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from .contract import validate_profile
from .environment import make_environment
from .errors import TrainingError
from .model import prepare_training_model
from .preflight import runtime_preflight, static_preflight
from .trainer import train_and_evaluate


def run_training(profile: dict[str, Any], bundle_dir: Path, output_dir: Path) -> None:
    """Train only when every source, runtime, model, and output gate is satisfied."""

    validate_profile(profile)
    static_preflight(profile, bundle_dir)
    if profile["runtime"].get("status") != "locked":
        raise TrainingError(
            "TRAINING_RUNTIME_NOT_LOCKED",
            "The accepted engine decision has no locked OCI/package runtime.",
        )
    if output_dir.exists() and any(output_dir.iterdir()):
        raise TrainingError(
            "TRAINING_OUTPUT_NOT_EMPTY",
            "Training refuses to mix outputs with existing files.",
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    if os.environ.get("JAX_DEFAULT_MATMUL_PRECISION") != "highest":
        raise TrainingError(
            "TRAINING_PRECISION_ENV_MISSING",
            "Set JAX_DEFAULT_MATMUL_PRECISION=highest before worker startup.",
        )
    with tempfile.TemporaryDirectory(prefix="worldspec-h1-model-") as temporary:
        training_model, derivation = prepare_training_model(profile, bundle_dir, Path(temporary))
        runtime_preflight(profile, training_model)
        env = make_environment(profile, training_model)
        train_and_evaluate(profile, env, output_dir, derivation)
