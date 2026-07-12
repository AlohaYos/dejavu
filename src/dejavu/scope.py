"""Scope resolution.

- project scope: search upward from cwd for a .knowledge/ directory
- git worktree: every worktree shares the main worktree's DB (no configuration needed)
- user scope: ~/.config/dejavu/knowledge.db (automatic fallback when no project is found)
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

KNOWLEDGE_DIR = ".knowledge"
DB_NAME = "knowledge.db"
CONFIG_NAME = "config.toml"
TRIGGERS_NAME = "dejavu-triggers.md"

# Per-category defaults: (default storage, days before an entry is considered stale)
CATEGORIES: dict[str, tuple[str, int]] = {
    "context": ("local", 7),
    "plan": ("local", 14),
    "decision": ("shared", 30),
    "feature": ("local", 7),
    "convention": ("shared", 30),
    "note": ("local", 14),
}
DEFAULT_CATEGORY = "note"
STATUSES = ("proposed", "accepted", "done", "superseded")


@dataclass(frozen=True)
class Scope:
    name: str  # "project" | "user"
    db_path: Path
    root: Path | None  # for project: the root we are *in* (a worktree, possibly)
    stale_days: dict[str, int]

    @property
    def knowledge_dir(self) -> Path | None:
        return self.root / KNOWLEDGE_DIR if self.root else None


def user_home() -> Path:
    """User-scope directory. Overridable via DEJAVU_HOME (used by the test suite)."""
    override = os.environ.get("DEJAVU_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "dejavu"


def state_path() -> Path:
    return user_home() / "state.json"


def _git_common_dir(start: Path) -> Path | None:
    """Resolve the *main* .git directory, even from inside a linked worktree."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=start,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    raw = proc.stdout.strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = (start / path).resolve()
    return path


def main_worktree_root(start: Path | None = None) -> Path | None:
    """Root of the main worktree, or None when outside a git repository."""
    here = (start or Path.cwd()).resolve()
    common = _git_common_dir(here)
    if common is None:
        return None
    root = common.parent
    return root if root.is_dir() else None


def find_project_root(start: Path | None = None) -> Path | None:
    """Nearest ancestor directory containing .knowledge/, or None."""
    here = (start or Path.cwd()).resolve()

    for d in [here, *here.parents]:
        if (d / KNOWLEDGE_DIR).is_dir():
            return d

    # Inside a worktree where .knowledge/ has not been checked out: fall back to main.
    main = main_worktree_root(here)
    if main is not None and (main / KNOWLEDGE_DIR).is_dir():
        return main

    return None


def resolve_db_root(root: Path, start: Path | None = None) -> Path:
    """Return the directory whose .knowledge/ holds the database.

    Careful: .knowledge/*.md is tracked by git, so `.knowledge/` gets checked out into
    every linked worktree. Naively using root/.knowledge/knowledge.db would therefore
    create a SEPARATE database per worktree, breaking the "all worktrees share one
    knowledge base" guarantee. The DB always lives in the main worktree.
    """
    main = main_worktree_root(start or root)
    if main is not None and main != root and (main / KNOWLEDGE_DIR).is_dir():
        return main
    return root


_SECTION = re.compile(r"^\[(?P<name>[^\]]+)\]\s*$")
_INT_KV = re.compile(r"^(?P<key>[A-Za-z_][\w-]*)\s*=\s*(?P<value>\d+)\s*$")


def _load_stale_days(config_file: Path | None) -> dict[str, int]:
    """Read [stale_days] from config.toml.

    Only a handful of integer keys are needed, so we avoid tomllib (Python 3.11+).
    That keeps requires-python low and adds no dependency.
    A malformed config falls back to defaults: failing to open the knowledge base
    would be worse than silently ignoring a bad setting.
    """
    days = {cat: d for cat, (_, d) in CATEGORIES.items()}
    if config_file is None or not config_file.exists():
        return days

    try:
        text = config_file.read_text(encoding="utf-8")
    except OSError:
        return days

    section = ""
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if (m := _SECTION.match(line)) is not None:
            section = m.group("name")
            continue
        if section != "stale_days":
            continue
        if (m := _INT_KV.match(line)) is not None:
            key, value = m.group("key"), int(m.group("value"))
            if key in days and value > 0:
                days[key] = value
    return days


def user_scope() -> Scope:
    home = user_home()
    return Scope(
        name="user",
        db_path=home / DB_NAME,
        root=None,
        stale_days=_load_stale_days(home / CONFIG_NAME),
    )


def project_scope(start: Path | None = None) -> Scope | None:
    root = find_project_root(start)
    if root is None:
        return None
    db_root = resolve_db_root(root, start)  # worktrees share the main worktree's DB
    return Scope(
        name="project",
        db_path=db_root / KNOWLEDGE_DIR / DB_NAME,
        root=root,
        stale_days=_load_stale_days(root / KNOWLEDGE_DIR / CONFIG_NAME),
    )


def resolve_write(requested: str | None = None, start: Path | None = None) -> Scope:
    """Target scope for add/edit. Defaults to project, falling back to user."""
    if requested == "user":
        return user_scope()
    proj = project_scope(start)
    if requested == "project":
        if proj is None:
            raise FileNotFoundError("No project scope found. Run `dejavu init` first.")
        return proj
    return proj or user_scope()


def resolve_read(requested: str | None = None, start: Path | None = None) -> list[Scope]:
    """Scopes to read from for search/list. Defaults to both project and user."""
    if requested == "user":
        return [user_scope()]
    proj = project_scope(start)
    if requested == "project":
        if proj is None:
            raise FileNotFoundError("No project scope found. Run `dejavu init` first.")
        return [proj]
    return [s for s in (proj, user_scope()) if s is not None]
