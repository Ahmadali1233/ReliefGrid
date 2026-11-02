"""Allocation engine: pure Python, no database or web code."""

from .allocate import Decision, Take, allocate
from .explain import explain
from .rules import DEFAULT_RULES, URGENCY_LEVELS, clean_rules, normalize_urgency, sort_key

__all__ = [
    "Decision", "Take", "allocate", "explain",
    "DEFAULT_RULES", "URGENCY_LEVELS", "clean_rules", "normalize_urgency", "sort_key",
]
