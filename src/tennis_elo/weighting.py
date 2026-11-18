"""Fixed, operator-selected tournament coefficients for Elo's base K-factor."""

from collections.abc import Mapping
from types import MappingProxyType

TOURNAMENT_COEFFICIENTS: Mapping[str, float] = MappingProxyType(
    {
        "challenger": 0.75,
        "atp_250": 1.0,
        "atp_500": 1.25,
        "masters_1000": 1.5,
        "atp_finals": 1.75,
        "grand_slam": 2.0,
        "other": 1.0,
        "unknown": 1.0,
    }
)


def coefficient_for_level(level: str) -> float:
    """Return a canonical level's coefficient; reject misspelled level keys."""
    try:
        return TOURNAMENT_COEFFICIENTS[level]
    except KeyError:
        raise ValueError(f"unknown tournament level: {level!r}") from None
