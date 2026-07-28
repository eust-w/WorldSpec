"""WorldSpec H1 target-dynamics training backend."""

from .errors import TrainingError
from .runner import run_training

__all__ = ["TrainingError", "run_training"]
__version__ = "0.1.0"
