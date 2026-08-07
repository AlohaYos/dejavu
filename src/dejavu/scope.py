"""Scope resolution.

- project scope: search upward from cwd for a .dejavu/ directory
- git worktree: every worktree shares the main worktree's DB (no configuration needed)
- user scope: ~/.config/dejavu/knowledge.db (automatic fallback when no project is found)
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

DEJAVU_DIR = ".dejavu"
DB_NAME = "knowledge.db"
OBSIDIAN_DB_NAME = "obsidian.db"
SHARED_DB_NAME = "shared.db"
CONFIG_NAME = "config.toml"
# Per-machine project settings that must never be committed. `config.toml` is shared and
# git-tracked (stale thresholds a team agrees on); anything that points into *this*
# machine's Obsidian vault belongs here instead, where .dejavu/.gitignore keeps it local.
LOCAL_CONFIG_NAME = "config.local.toml"
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
        return self.root / DEJAVU_DIR if self.root else None


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
    """Nearest ancestor directory containing .dejavu/, or None."""
    here = (start or Path.cwd()).resolve()

    for d in [here, *here.parents]:
        if (d / DEJAVU_DIR).is_dir():
            return d

    # Inside a worktree where .dejavu/ has not been checked out: fall back to main.
    main = main_worktree_root(here)
    if main is not None and (main / DEJAVU_DIR).is_dir():
        return main

    return None


def resolve_db_root(root: Path, start: Path | None = None) -> Path:
    """Return the directory whose .dejavu/ holds the database.

    Careful: .dejavu/*.md is tracked by git, so `.dejavu/` gets checked out into
    every linked worktree. Naively using root/.dejavu/knowledge.db would therefore
    create a SEPARATE database per worktree, breaking the "all worktrees share one
    knowledge base" guarantee. The DB always lives in the main worktree.
    """
    main = main_worktree_root(start or root)
    if main is not None and main != root and (main / DEJAVU_DIR).is_dir():
        return main
    return root


_SECTION = re.compile(r"^\[(?P<name>[^\]]+)\]\s*$")
_KV = re.compile(r"^(?P<key>[A-Za-z_][\w-]*)\s*=\s*(?P<value>.+?)\s*$")

ConfigValue = str | int | list[str]


def _parse_value(raw: str) -> ConfigValue | None:
    """Parse the right-hand side of a config line.

    Deliberately tiny: quoted strings, string arrays, and integers. That is the whole
    vocabulary dejavu's config needs, and it is why tomllib (Python 3.11+) is not
    imported here — requires-python stays at 3.10 and the dependency count stays at zero.
    """
    if not raw:
        return None
    if raw[0] == '"' and raw.endswith('"') and len(raw) >= 2:
        return raw[1:-1]
    if raw[0] == "'" and raw.endswith("'") and len(raw) >= 2:
        return raw[1:-1]
    if raw[0] == "[" and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        items: list[str] = []
        for chunk in inner.split(","):
            item = chunk.strip()
            if len(item) >= 2 and item[0] in "\"'" and item[-1] == item[0]:
                item = item[1:-1]
            if item:
                items.append(item)
        return items
    if raw.isdigit():
        return int(raw)
    return raw


def load_config(config_file: Path | None) -> dict[str, dict[str, ConfigValue]]:
    """Read a config.toml into {section: {key: value}}.

    A malformed config yields whatever parsed cleanly rather than raising: failing to
    open the knowledge base would be worse than silently ignoring a bad setting.
    """
    data: dict[str, dict[str, ConfigValue]] = {}
    if config_file is None or not config_file.exists():
        return data
    try:
        text = config_file.read_text(encoding="utf-8")
    except OSError:
        return data

    section = ""
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if (m := _SECTION.match(line)) is not None:
            section = m.group("name")
            data.setdefault(section, {})
            continue
        if not section:
            continue
        if (m := _KV.match(line)) is not None:
            value = _parse_value(m.group("value"))
            if value is not None:
                data.setdefault(section, {})[m.group("key")] = value
    return data


def _load_stale_days(config_file: Path | None) -> dict[str, int]:
    """Read [stale_days] from config.toml."""
    days = {cat: d for cat, (_, d) in CATEGORIES.items()}
    for key, value in load_config(config_file).get("stale_days", {}).items():
        if key in days and isinstance(value, int) and value > 0:
            days[key] = value
    return days


def set_config_value(config_file: Path, section: str, key: str, value: str) -> None:
    """Write one key back, line by line, leaving every comment and blank line intact.

    Regenerating the file from the parsed dict would silently delete the explanatory
    comments shipped in assets/config.toml — which are most of that file's value.
    """
    lines = config_file.read_text(encoding="utf-8").splitlines() if config_file.exists() else []
    rendered = f'{key} = "{value}"'

    in_section = False
    section_end = -1
    for i, raw in enumerate(lines):
        stripped = raw.split("#", 1)[0].strip()
        if (m := _SECTION.match(stripped)) is not None:
            if in_section:
                break
            in_section = m.group("name") == section
            if in_section:
                section_end = i
            continue
        if not in_section:
            continue
        if stripped:
            # Blank and comment-only lines are skipped so a new key lands directly after
            # the last real setting, not after the blank line that separates sections.
            section_end = i
        if (m := _KV.match(stripped)) is not None and m.group("key") == key:
            lines[i] = rendered
            config_file.parent.mkdir(parents=True, exist_ok=True)
            config_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return

    if in_section or section_end >= 0:
        lines.insert(section_end + 1, rendered)
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([f"[{section}]", rendered])

    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def user_config_path() -> Path:
    """Where [obsidian] lives. A vault is a property of the machine, not of a repository."""
    return user_home() / CONFIG_NAME


# Markdown files on disk are never out of date with themselves, so index scopes must not
# report staleness. Every category is listed explicitly because Entry.stale_days falls
# back to 14 for keys this dict does not contain.
NEVER_STALE = {cat: 36500 for cat in CATEGORIES}


@dataclass(frozen=True)
class ObsidianConfig:
    vault: Path | None
    include: list[str]
    knowledge_dir: str
    knowledge_other_dir: str
    userinfo_dir: str
    research_dir: str
    write_mode: str  # auto | full | append-only
    research: str  # all | findings | manual
    promote: str  # ask | always | never
    harvest: str  # on | off
    harvest_min_lines: int
    relate: str  # off | search | embed
    relate_key: str
    relate_top_k: int
    relate_min_chars: int
    relate_model: str
    relate_host: str
    relate_min_sim: float
    relate_autostart: str  # ask | always | never
    relate_keep_alive: str
    relate_defer_days: int
    link_keep_runs: int
    link_keep_days: int

    @property
    def enabled(self) -> bool:
        return self.vault is not None


OBSIDIAN_DEFAULTS: dict[str, str] = {
    "knowledge_dir": "Knowledge",
    "knowledge_other_dir": "Other",
    "userinfo_dir": "UserInfo",
    "research_dir": "Research",
    "write_mode": "auto",
    "research": "findings",
    "promote": "ask",
    "harvest": "on",
    "relate": "off",
    "relate_key": "related",
    "relate_model": "bge-m3",
    "relate_host": "http://localhost:11434",
    "relate_autostart": "ask",
    # Sent with every request rather than exported as OLLAMA_KEEP_ALIVE: an environment
    # variable would have to be made persistent somewhere on the user's machine, and a
    # change left behind is a change someone has to be told how to undo.
    "relate_keep_alive": "24h",
}
OBSIDIAN_INT_DEFAULTS: dict[str, int] = {
    # A session shorter than this produced nothing worth filing. The unit is lines of the
    # host's transcript, which is one JSON object per turn — so this is "about 40 turns",
    # not a character count.
    "harvest_min_lines": 40,
    "relate_top_k": 5,
    "relate_min_chars": 40,
    "relate_defer_days": 7,
    "link_keep_runs": 10,
    "link_keep_days": 30,
}
OBSIDIAN_FLOAT_DEFAULTS: dict[str, float] = {
    # Settled by running it over two real vaults rather than by reasoning about it. At
    # 0.6 a 500-note vault filled `relate_top_k` for almost every note, which means the
    # cap was choosing the links rather than the similarity. 0.65 leaves both a small
    # folder of technical articles and a large pile of personal notes at a density where
    # the score is doing the work.
    "relate_min_sim": 0.65,
}
OBSIDIAN_CHOICES: dict[str, tuple[str, ...]] = {
    "write_mode": ("auto", "full", "append-only"),
    "research": ("all", "findings", "manual"),
    "promote": ("ask", "always", "never"),
    "harvest": ("on", "off"),
    "relate": ("off", "search", "embed"),
    "relate_autostart": ("ask", "always", "never"),
}


def obsidian_config(config_file: Path | None = None) -> ObsidianConfig:
    section = load_config(config_file or user_config_path()).get("obsidian", {})

    raw_vault = section.get("vault")
    vault = Path(str(raw_vault)).expanduser() if isinstance(raw_vault, str) and raw_vault else None

    raw_include = section.get("include")
    include = [str(x) for x in raw_include] if isinstance(raw_include, list) else []

    def pick(key: str) -> str:
        value = section.get(key)
        text = str(value) if isinstance(value, str) and value else OBSIDIAN_DEFAULTS[key]
        allowed = OBSIDIAN_CHOICES.get(key)
        return text if allowed is None or text in allowed else OBSIDIAN_DEFAULTS[key]

    def pick_int(key: str) -> int:
        """Fall back to the default rather than raising: a typo in config.toml must not
        stop dejavu from saving a note."""
        value = section.get(key)
        try:
            number = int(str(value))
        except (TypeError, ValueError):
            return OBSIDIAN_INT_DEFAULTS[key]
        return number if number > 0 else OBSIDIAN_INT_DEFAULTS[key]

    def pick_float(key: str) -> float:
        value = section.get(key)
        try:
            number = float(str(value))
        except (TypeError, ValueError):
            return OBSIDIAN_FLOAT_DEFAULTS[key]
        return number if 0.0 <= number <= 1.0 else OBSIDIAN_FLOAT_DEFAULTS[key]

    cfg = ObsidianConfig(
        vault=vault,
        include=include,
        knowledge_dir=pick("knowledge_dir"),
        knowledge_other_dir=pick("knowledge_other_dir"),
        userinfo_dir=pick("userinfo_dir"),
        research_dir=pick("research_dir"),
        write_mode=pick("write_mode"),
        research=pick("research"),
        promote=pick("promote"),
        harvest=pick("harvest"),
        harvest_min_lines=pick_int("harvest_min_lines"),
        relate=pick("relate"),
        relate_key=pick("relate_key"),
        relate_top_k=pick_int("relate_top_k"),
        relate_min_chars=pick_int("relate_min_chars"),
        relate_model=pick("relate_model"),
        relate_host=pick("relate_host"),
        relate_min_sim=pick_float("relate_min_sim"),
        relate_autostart=pick("relate_autostart"),
        relate_keep_alive=pick("relate_keep_alive"),
        relate_defer_days=pick_int("relate_defer_days"),
        link_keep_runs=pick_int("link_keep_runs"),
        link_keep_days=pick_int("link_keep_days"),
    )
    if not cfg.include:
        cfg = replace(
            cfg, include=[cfg.knowledge_dir, cfg.userinfo_dir, cfg.research_dir]
        )
    return cfg


def project_local_config_path(root: Path) -> Path:
    """Per-machine, never-committed project settings (see LOCAL_CONFIG_NAME)."""
    return root / DEJAVU_DIR / LOCAL_CONFIG_NAME


def project_memory(start: Path | None = None) -> str | None:
    """The vault subfolder (under knowledge_dir) this project uses as its external memory.

    Stored in .dejavu/config.local.toml as `[obsidian] memory` — **not** the tracked
    config.toml. Which folder of *this machine's* vault a project is shelved in is a
    property of the user's own vault layout, not of the repository: a teammate who cloned
    it would have no "Job/dejavu" folder, so committing the value would break --memory for
    them. A path relative to knowledge_dir, so it may be nested, e.g. "Job/dejavu".
    Returns None when the project has not set one.
    """
    root = find_project_root(start)
    if root is None:
        return None
    section = load_config(project_local_config_path(root)).get("obsidian", {})
    value = section.get("memory")
    if not isinstance(value, str):
        return None
    cleaned = value.strip().strip("/").strip()
    return cleaned or None


def obsidian_scope() -> Scope:
    """Read-only index of the Obsidian vault. A separate file from knowledge.db.

    Mixing hundreds of vault notes into knowledge.db would drown `list`, `recent` and
    `resume`, which answer "what have I been working on" — a question the vault has no
    part in. Keeping it separate also makes the index disposable: delete it and
    `dejavu obsidian sync` rebuilds it.
    """
    return Scope(
        name="obsidian",
        db_path=user_home() / OBSIDIAN_DB_NAME,
        root=None,
        stale_days=NEVER_STALE,
    )


def shared_scope(root: Path) -> Scope:
    """Read-only index of <repo>/docs/knowledge/*.md — the team-shared, git-tracked layer."""
    return Scope(
        name="shared",
        db_path=resolve_db_root(root) / DEJAVU_DIR / SHARED_DB_NAME,
        root=root,
        stale_days=NEVER_STALE,
    )


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
        db_path=db_root / DEJAVU_DIR / DB_NAME,
        root=root,
        stale_days=_load_stale_days(root / DEJAVU_DIR / CONFIG_NAME),
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
