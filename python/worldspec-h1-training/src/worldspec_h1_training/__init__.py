"""WorldSpec H1 target-dynamics training backend."""

from .calibration import (
    make_calibration_training_profile,
    run_calibration,
    validate_calibration_profile,
)
from .errors import TrainingError
from .midterm import (
    make_midterm_training_profile,
    make_task_load_retention_training_profile,
    run_midterm_calibration,
    validate_midterm_profile,
    validate_task_load_retention_profile,
)
from .runner import run_training

__all__ = [
    "TrainingError",
    "make_calibration_training_profile",
    "make_midterm_training_profile",
    "make_task_load_retention_training_profile",
    "run_calibration",
    "run_midterm_calibration",
    "run_training",
    "validate_calibration_profile",
    "validate_midterm_profile",
    "validate_task_load_retention_profile",
]
__version__ = "0.1.0"
