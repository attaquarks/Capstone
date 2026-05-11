"""Centralised filesystem paths for the Supply Chain Intelligence Agent.

All modules should import these constants instead of re-deriving paths
from ``__file__``. This keeps the layout consistent across the package
and makes the project relocatable (e.g. inside a container that copies
the repo into ``/app``).

Override via environment variables when running in non-standard layouts
(Docker mounts a volume on ``runtime/`` for state persistence):

* ``PROJECT_ROOT``         — absolute path of the repository root.
* ``DATA_DIR``             — seed CSV/spec data (default ``<root>/data``).
* ``RUNTIME_DIR``          — feedback DB, checkpoint DB, JSON exports (default ``<root>/runtime``).
* ``EVALUATION_DIR``       — eval config + thresholds (default ``<root>/evaluation``).
* ``TESTS_DIR``            — curated test datasets (default ``<root>/tests``).
* ``DOCS_DIR``             — auto-generated reports land here (default ``<root>/docs``).
* ``CHROMA_DIR``           — local ChromaDB persistence (default ``<root>/runtime/chroma_db``).
* ``CHECKPOINT_DB_PATH``   — full path to the LangGraph SQLite checkpoint file.
* ``FEEDBACK_DB_PATH``     — full path to the Streamlit feedback SQLite DB.
* ``FEEDBACK_JSON_PATH``   — full path to the Lab 12 JSON mirror.
"""

from __future__ import annotations

import os
from pathlib import Path


def _resolve_root() -> Path:
    """Walk up from this file until we find the repo root marker."""
    env = os.getenv("PROJECT_ROOT")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    # src/paths.py  →  src/  →  <repo>
    return here.parent.parent


PROJECT_ROOT: Path = _resolve_root()

DATA_DIR: Path = Path(os.getenv("DATA_DIR", PROJECT_ROOT / "data"))
RUNTIME_DIR: Path = Path(os.getenv("RUNTIME_DIR", PROJECT_ROOT / "runtime"))
EVALUATION_DIR: Path = Path(os.getenv("EVALUATION_DIR", PROJECT_ROOT / "evaluation"))
TESTS_DIR: Path = Path(os.getenv("TESTS_DIR", PROJECT_ROOT / "tests"))
DOCS_DIR: Path = Path(os.getenv("DOCS_DIR", PROJECT_ROOT / "docs"))

CHROMA_DIR: Path = Path(os.getenv("CHROMA_DIR", RUNTIME_DIR / "chroma_db"))
CHECKPOINT_DB_PATH: Path = Path(
    os.getenv("CHECKPOINT_DB_PATH", RUNTIME_DIR / "checkpoint_db.sqlite")
)
FEEDBACK_DB_PATH: Path = Path(
    os.getenv("FEEDBACK_DB_PATH", RUNTIME_DIR / "feedback_log.db")
)
FEEDBACK_JSON_PATH: Path = Path(
    os.getenv("FEEDBACK_JSON_PATH", RUNTIME_DIR / "feedback_log.json")
)


def ensure_runtime_dirs() -> None:
    """Create the writable directories on first use. Safe to call repeatedly."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


__all__ = [
    "PROJECT_ROOT",
    "DATA_DIR",
    "RUNTIME_DIR",
    "EVALUATION_DIR",
    "TESTS_DIR",
    "DOCS_DIR",
    "CHROMA_DIR",
    "CHECKPOINT_DB_PATH",
    "FEEDBACK_DB_PATH",
    "FEEDBACK_JSON_PATH",
    "ensure_runtime_dirs",
]
