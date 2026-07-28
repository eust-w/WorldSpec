"""WorldSpec H1 target-dynamics training backend."""

from .calibration import (
    make_calibration_training_profile,
    run_calibration,
    validate_calibration_profile,
)
from .errors import TrainingError
from .runner import run_training

__all__ = [
    "TrainingError",
    "make_calibration_training_profile",
    "run_calibration",
    "run_training",
    "validate_calibration_profile",
]
__version__ = "0.1.0"
