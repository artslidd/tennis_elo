"""Streamlit Community Cloud entrypoint for the Tennis Elo dashboard.

Point Community Cloud at ``deploy/streamlit_app.py``. It installs
``deploy/requirements.txt`` (that file sits next to this entrypoint, so it wins
over the repository's ``uv.lock``), makes the ``src/`` package importable without
installing it, and pins the data directory to the repository root so visitors
cannot point the server at other folders.

Run the same thing locally with ``uv run --extra dashboard streamlit run
deploy/streamlit_app.py``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tennis_elo.dashboard_views import DATA_DIR_ENV

# An explicit (non-blank) value, e.g. from Community Cloud secrets, still wins.
if not os.environ.get(DATA_DIR_ENV, "").strip():
    os.environ[DATA_DIR_ENV] = str(REPO_ROOT)

from tennis_elo.dashboard import main

main()
