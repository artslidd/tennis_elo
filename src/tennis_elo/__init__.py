"""Reproducible tennis Elo ratings, CLI, and optional web dashboard.

The base package is standard-library only. Importing it must not pull in
Streamlit or pandas; those are confined to the optional dashboard extra.
"""

from .api import available_seasons, calculate
from .export import (
    history_csv,
    history_rows,
    ranking_rows,
    rankings_csv,
    summary_dict,
    write_outputs,
)
from .models import (
    CalculationResult,
    HistoryEntry,
    LoadResult,
    Match,
    PlayerRating,
    RatingConfig,
    RatingResult,
)

__all__ = [
    "CalculationResult",
    "HistoryEntry",
    "LoadResult",
    "Match",
    "PlayerRating",
    "RatingConfig",
    "RatingResult",
    "available_seasons",
    "calculate",
    "history_csv",
    "history_rows",
    "ranking_rows",
    "rankings_csv",
    "summary_dict",
    "write_outputs",
]
