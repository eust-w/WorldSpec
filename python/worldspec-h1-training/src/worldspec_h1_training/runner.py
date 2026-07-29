"""Public training entry point used by the isolated worker."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from .contract import digest_json, validate_profile
from .environment import make_environment
from .errors import TrainingError
from .model import prepare_training_model
from .preflight import runtime_preflight, static_preflight
from .trainer import _flat_observation_size, train_and_evaluate
from .warm_start import materialize_warm_start, validate_network_compatibility


def run_training(
    profile: dict[str, Any],
    bundle_dir: Path,
    output_dir: Path,
    warm_start_archive: Path | None = None,
    initialization_report: dict[str, Any] | None = None,
) -> None:
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
        temporary_root = Path(temporary)
        training_model, derivation = prepare_training_model(
            profile,
            bundle_dir,
            temporary_root / "model",
        )
        runtime_preflight(profile, training_model)
        env = make_environment(profile, training_model)
        initialization: dict[str, Any] | None = None
        restore_checkpoint_path: Path | None = None
        if profile["training"]["hyperparameterStatus"] == "calibrated_task_profile":
            if warm_start_archive is None or initialization_report is None:
                raise TrainingError(
                    "TRAINING_WARM_START_MISSING",
                    "Formal task training requires its passing midterm report and checkpoint.",
                )
            source_profile_digest = profile["initialization"]["sourceProfileDigest"]
            checkpoint = initialization_report.get("researchCheckpoint", {})
            if (
                initialization_report.get("formalTrainingGate") != "passed"
                or initialization_report.get("qualityAssessment", {}).get("status") != "passed"
                or initialization_report.get("midtermProfileDigest") != source_profile_digest
                or checkpoint.get("distribution") != "internal_only"
            ):
                raise TrainingError(
                    "TRAINING_WARM_START_REPORT_INVALID",
                    "The initialization report does not authorize formal training.",
                )
            restore_checkpoint_path, initialization = materialize_warm_start(
                warm_start_archive,
                temporary_root / "warm-start",
                checkpoint["digest"],
                checkpoint["sizeBytes"],
            )
            validate_network_compatibility(
                initialization,
                observation_size=_flat_observation_size(env.observation_size["state"]),
                action_size=int(env.action_size),
            )
            initialization["sourceProfileDigest"] = source_profile_digest
            initialization["sourceReportDigest"] = digest_json(initialization_report)
        train_and_evaluate(
            profile,
            env,
            output_dir,
            derivation,
            restore_checkpoint_path=restore_checkpoint_path,
            initialization=initialization,
        )
