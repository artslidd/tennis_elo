"""Command line interface for the tennis Elo package.

The CLI resolves :func:`tennis_elo.api.calculate` through the module object so
tests can replace that seam, and so no data/engine import happens until a valid
``rank`` invocation actually runs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import api
from .export import ranking_rows, write_outputs
from .models import RatingConfig

_DEFAULT_TOP = 20
_NAME_WIDTH = 28


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tennis-elo",
        description="Reproducible tennis Elo ratings from *-atp-season.csv files.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    rank = subparsers.add_parser(
        "rank",
        help="calculate rankings for one to three consecutive seasons",
        description=(
            "Calculate fresh-start Elo rankings for one to three distinct, "
            "consecutive seasons and export them."
        ),
    )
    rank.add_argument(
        "--seasons",
        nargs="+",
        required=True,
        type=int,
        metavar="YEAR",
        help="one to three distinct consecutive season years, e.g. 2025 2026",
    )
    rank.add_argument(
        "--input-dir",
        default=".",
        help="directory holding *-atp-season.csv files (default: current directory)",
    )
    rank.add_argument(
        "--output-dir",
        default=None,
        help="fresh output directory (default: outputs/<selected-years>)",
    )
    rank.add_argument(
        "--initial-rating",
        type=float,
        default=1500.0,
        help="starting rating for every player (default: 1500)",
    )
    rank.add_argument(
        "--k-factor",
        type=float,
        default=32.0,
        help="Elo K factor (default: 32)",
    )
    rank.add_argument(
        "--exclude-retirements",
        action="store_true",
        help="drop matches whose status_extra marks a retirement",
    )
    rank.add_argument(
        "--history",
        action="store_true",
        help="also export one row per player per match",
    )
    rank.add_argument(
        "--min-matches",
        type=int,
        default=0,
        help="only present players with at least this many matches (default: 0)",
    )
    rank.add_argument(
        "--top",
        type=int,
        default=_DEFAULT_TOP,
        help=f"rows shown in the terminal table (default: {_DEFAULT_TOP})",
    )
    return parser


def _default_output_dir(seasons: tuple[int, ...]) -> Path:
    if len(seasons) == 1:
        return Path("outputs") / str(seasons[0])
    return Path("outputs") / f"{seasons[0]}-{seasons[-1]}"


def _fail(message: object) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def _format_table(rows: list[dict], top: int) -> str:
    header = f"{'#':>4}  {'Player':<{_NAME_WIDTH}}  {'Rating':>7}  {'M':>4}  {'W':>4}  {'L':>4}"
    lines = [header]
    for row in rows[:top]:
        name = row["name"]
        if len(name) > _NAME_WIDTH:
            name = name[: _NAME_WIDTH - 3] + "..."
        lines.append(
            f"{row['rank']:>4}  {name:<{_NAME_WIDTH}}  {row['rating']:>7.0f}  "
            f"{row['matches']:>4}  {row['wins']:>4}  {row['losses']:>4}"
        )
    return "\n".join(lines)


def _run_rank(args: argparse.Namespace) -> int:
    if args.min_matches < 0:
        return _fail("--min-matches must be greater than or equal to zero")
    if args.top < 0:
        return _fail("--top must be greater than or equal to zero")

    try:
        config = RatingConfig(
            initial_rating=args.initial_rating,
            k_factor=args.k_factor,
            include_retirements=not args.exclude_retirements,
        )
    except ValueError as exc:
        return _fail(exc)

    try:
        result = api.calculate(
            args.input_dir, args.seasons, config=config, include_history=args.history
        )
    except (ValueError, OSError) as exc:
        return _fail(exc)

    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir(result.seasons)
    try:
        written = write_outputs(
            result,
            output_dir,
            min_matches=args.min_matches,
            include_history=args.history,
        )
    except (ValueError, OSError) as exc:
        return _fail(exc)

    rows = ranking_rows(result, min_matches=args.min_matches)
    seasons = " ".join(str(year) for year in result.seasons)
    print(
        f"Seasons: {seasons}  |  matches: {result.ratings.matches_processed}"
        f"  |  players: {len(result.ratings.players)}"
    )
    print(f"Showing top {min(args.top, len(rows))} of {len(rows)} player rows")
    print(_format_table(rows, args.top))
    if result.load.excluded_counts:
        excluded = ", ".join(
            f"{reason}={count}" for reason, count in sorted(result.load.excluded_counts.items())
        )
        print(f"Excluded rows: {excluded}")
    for label in ("rankings", "history", "summary"):
        if label in written:
            print(f"Wrote {label}: {written[label]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process status code (0 success, 2 expected error)."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "rank":
        return _run_rank(args)
    parser.error(f"unknown command: {args.command!r}")  # pragma: no cover - argparse guards
    return 2  # pragma: no cover - parser.error raises
