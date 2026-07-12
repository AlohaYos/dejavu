"""Environment check performed at start-up.

Japanese search in dejavu depends on the FTS5 trigram tokenizer (SQLite 3.34+).
On a Python whose SQLite lacks it, search would silently return zero results —
the worst possible failure mode — so fail loudly before opening the database.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

MIN_SQLITE = (3, 34, 0)


class PreflightError(RuntimeError):
    pass


def _has_fts5_trigram() -> bool:
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE VIRTUAL TABLE _probe USING fts5(x, tokenize='trigram')")
        return True
    except sqlite3.Error:
        return False
    finally:
        con.close()


def check(cache_path: Path | None = None) -> None:
    """Raise PreflightError unless FTS5 + trigram are available.

    The probe itself is cheap (a CREATE against an in-memory database), but the result
    is cached in state.json and only re-checked when the Python or SQLite version changes.
    """
    fingerprint = f"{sys.version_info[:2]}-{sqlite3.sqlite_version}"

    if cache_path is not None and cache_path.exists():
        try:
            state = json.loads(cache_path.read_text(encoding="utf-8"))
            if state.get("preflight_ok") == fingerprint:
                return
        except (OSError, ValueError):
            pass  # A corrupt cache is not fatal; fall through to the real check.

    if not _has_fts5_trigram():
        raise PreflightError(
            f"This Python's SQLite ({sqlite3.sqlite_version}) has no FTS5 trigram "
            f"tokenizer (SQLite {'.'.join(map(str, MIN_SQLITE))}+ is required).\n"
            f"  dejavu's Japanese search depends on it.\n"
            f"  Reinstall against a Homebrew Python:\n"
            f"      brew install python@3.13\n"
            f"      uv tool install --python $(brew --prefix)/bin/python3.13 --force dejavu"
        )

    if cache_path is not None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"preflight_ok": fingerprint}), encoding="utf-8")
        except OSError:
            pass  # Failing to write the cache must not break the command.
