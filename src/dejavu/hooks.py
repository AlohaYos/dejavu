"""Session-end harvest: ask the assistant to file what it learned, once per session.

The host (Claude Code) runs a Stop hook when a turn ends. A hook that exits 2 has its
stderr handed back to the assistant rather than shown to the user, which turns this into
the one place where a rule can be delivered *at the moment it applies* — the guidance
below costs nothing on the turns it does not fire, unlike a line parked in
dejavu-triggers.md that is re-read every single turn.

What it says: knowledge that outlives this repository belongs in the vault, write it
without asking. What it deliberately does not do: decide *what* is worth keeping. That
needs the session's content, which only the assistant has.
"""

from __future__ import annotations

import time
from pathlib import Path

from . import scope as scope_mod

MARKER_DIR_NAME = "harvest"
MARKER_MAX_AGE_DAYS = 30

# Written to stderr on exit 2, so the assistant reads it as instruction. Kept short: it is
# competing with a full session's context for attention.
HARVEST_MESSAGE = """\
[dejavu] Session harvest.

Anything learned here that would still be true in a *different* repository — a tool's
real behaviour, an undocumented constraint, something that took real digging — belongs
in the vault. File it now:

  1. dejavu search "<keywords>"  — first. Extend the existing note if there is one.
  2. dejavu obsidian add "<title>" --category <folder> --project <name> --body -
  3. Report it in one line.

Do not ask the user whether to save; they prune the vault themselves, so an unnecessary
note is cheaper than a lost one. Repository-specific detail is out of scope — that is
`dejavu add`. Nothing worth keeping? Say "harvest: nothing" and stop.\
"""


def _marker_dir() -> Path:
    return scope_mod.user_home() / MARKER_DIR_NAME


def _safe_name(session_id: str) -> str:
    """A session id is host-supplied, so it must never escape the marker directory."""
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in session_id)[:120]


def _transcript_lines(path: str) -> int:
    """Turn count, near enough. Returns 0 when the transcript is missing or unreadable —
    which suppresses the harvest, the safe direction to fail in."""
    try:
        with open(path, "rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def _sweep(marker_dir: Path) -> None:
    cutoff = time.time() - MARKER_MAX_AGE_DAYS * 86400
    try:
        for marker in marker_dir.iterdir():
            try:
                if marker.is_file() and marker.stat().st_mtime < cutoff:
                    marker.unlink()
            except OSError:
                continue
    except OSError:
        pass


def stop_hook(
    payload: dict,
    cfg: scope_mod.ObsidianConfig | None = None,
    marker_dir: Path | None = None,
) -> tuple[int, str]:
    """Decide whether to prompt a harvest. Returns (exit_code, stderr_text).

    exit 2 asks the host to keep the assistant working; exit 0 lets the session end. The
    only side effect is the marker file, and it is written *before* returning 2 so a
    failure to record the prompt means no prompt at all — repeating it every turn would
    be far worse than skipping it.
    """
    cfg = cfg if cfg is not None else scope_mod.obsidian_config()
    marker_dir = marker_dir if marker_dir is not None else _marker_dir()

    # This hook's own exit 2 restarted the assistant; firing again would not terminate.
    if payload.get("stop_hook_active"):
        return 0, ""

    if not cfg.enabled or cfg.harvest != "on" or cfg.promote == "never":
        return 0, ""

    session_id = str(payload.get("session_id") or "")
    if not session_id:
        return 0, ""

    if _transcript_lines(str(payload.get("transcript_path") or "")) < cfg.harvest_min_lines:
        return 0, ""

    marker = marker_dir / _safe_name(session_id)
    try:
        marker_dir.mkdir(parents=True, exist_ok=True)
        # x mode: exists-check and create in one step, so two hooks racing at the end of
        # the same turn cannot both decide they are the first.
        with open(marker, "x"):
            pass
    except FileExistsError:
        return 0, ""
    except OSError:
        return 0, ""

    _sweep(marker_dir)
    return 2, HARVEST_MESSAGE
