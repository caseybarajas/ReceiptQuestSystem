"""Receipt Quest System - Turn your thermal printer into an ADHD-friendly quest board."""

__version__ = "1.0.0"
__author__ = "Receipt Quest Team"

from .core.models import Quest, Objective
from .core.quest_generator import LocalLLMQuestGenerator

__all__ = ["Quest", "Objective", "LocalLLMQuestGenerator"]
