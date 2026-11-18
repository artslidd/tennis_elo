"""Console launcher for the optional local Tennis Elo Streamlit dashboard.

``tennis-elo-dashboard`` starts the installed Streamlit CLI against
:mod:`tennis_elo.dashboard` and binds the loopback interface by default, so the
dashboard is only reachable from the local machine. Streamlit is an optional
extra: importing this module never imports Streamlit, and a missing extra
produces an actionable installation message instead of a traceback.

The launcher blocks for as long as the web server runs (that is what ``streamlit
run`` does); stop it with Ctrl-C.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .dashboard_views import safe_label

__all__ = [
    "APP_PATH",
    "DEFAULT_ADDRESS",
    "DEFAULT_PORT",
    "MISSING_EXTRA_MESSAGE",
    "build_parser",
    "build_streamlit_argv",
    "main",
]

APP_PATH = Path(__file__).resolve().with_name("dashboard.py")
DEFAULT_ADDRESS = "localhost"
DEFAULT_PORT = 8501

MISSING_EXTRA_MESSAGE = (
    "The dashboard needs the optional web dependencies (Streamlit and pandas).\n"
    "Install them with:\n"
    "    uv sync --extra dashboard\n"
    "then start the dashboard with:\n"
    "    uv run --extra dashboard tennis-elo-dashboard"
)


def _port(value: str) -> int:
    """Argparse type that rejects unusable TCP ports."""
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"port must be an integer, got {value!r}") from None
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def build_parser() -> argparse.ArgumentParser:
    """Build the launcher argument parser."""
    parser = argparse.ArgumentParser(
        prog="tennis-elo-dashboard",
        description="Serve the local Tennis Elo Streamlit dashboard (localhost only).",
    )
    parser.add_argument(
        "--address",
        default=DEFAULT_ADDRESS,
        help=f"interface to bind (default: {DEFAULT_ADDRESS}, loopback only)",
    )
    parser.add_argument(
        "--port",
        type=_port,
        default=DEFAULT_PORT,
        help=f"TCP port to bind (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="do not open a browser window (useful for smoke tests and servers)",
    )
    parser.add_argument(
        "streamlit_args",
        nargs=argparse.REMAINDER,
        metavar="-- STREAMLIT_ARG",
        help="extra arguments forwarded to `streamlit run` (after `--`)",
    )
    return parser


def build_streamlit_argv(
    *,
    port: int = DEFAULT_PORT,
    address: str = DEFAULT_ADDRESS,
    headless: bool = False,
    extra: Sequence[str] = (),
    app_path: Path = APP_PATH,
) -> list[str]:
    """Build the exact ``streamlit run`` argv used by :func:`main`."""
    argv = [
        "streamlit",
        "run",
        str(app_path),
        f"--server.address={address}",
        f"--server.port={int(port)}",
        # Keep the local dashboard free of usage telemetry.
        "--browser.gatherUsageStats=false",
    ]
    if headless:
        argv.append("--server.headless=true")
    argv.extend(str(item) for item in extra)
    return argv


def _import_streamlit_cli_main() -> Callable[[], Any]:
    """Import the installed Streamlit CLI lazily (optional dependency seam)."""
    from streamlit.web import cli as streamlit_cli

    return streamlit_cli.main


def _run_streamlit_cli(argv: Sequence[str], cli_main: Callable[[], Any]) -> int:
    """Run the blocking Streamlit CLI with ``argv``, restoring ``sys.argv``."""
    previous_argv = sys.argv
    sys.argv = list(argv)
    try:
        result = cli_main()
    finally:
        sys.argv = previous_argv
    return int(result) if result else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``tennis-elo-dashboard`` console script."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help / usage errors already printed
        return int(exc.code or 0)

    extra = list(args.streamlit_args)
    if extra and extra[0] == "--":
        extra = extra[1:]
    streamlit_argv = build_streamlit_argv(
        port=args.port,
        address=safe_label(args.address) or DEFAULT_ADDRESS,
        headless=args.headless,
        extra=extra,
    )

    try:
        cli_main = _import_streamlit_cli_main()
    except ModuleNotFoundError:
        print(MISSING_EXTRA_MESSAGE, file=sys.stderr)
        return 1
    except ImportError as exc:  # pragma: no cover - defensive, streamlit present but broken
        print(f"Could not start Streamlit: {safe_label(exc)}", file=sys.stderr)
        return 1

    return _run_streamlit_cli(streamlit_argv, cli_main)


if __name__ == "__main__":  # pragma: no cover - exercised through the console script
    raise SystemExit(main())
