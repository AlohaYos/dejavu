"""Obsidian vault integration.

Why this exists
---------------
dejavu remembers *the project*. An Obsidian vault remembers *the user*: knowledge that
outlives one repository, and that a human actually reads back. Those are different
things, and forcing both into one SQLite file serves neither.

The problem is reach. A vault is a folder of Markdown, which Claude Code and Xcode's
agent can read directly — but Claude Desktop chat cannot see the filesystem at all, and
Cowork only sees folders the user attaches by hand, every session. dejavu already solved
that for its own database by shipping an MCP server. Pointing the same server at the
vault extends the fix to the vault, which is the entire justification for this module.

Two rules hold everything together
----------------------------------
**Markdown is the truth; the index is disposable.** Notes are indexed into a *separate*
database (`~/.config/dejavu/obsidian.db`) built from `store.SCHEMA` verbatim. Because the
rows look exactly like `entries` rows, `search.py` runs over them unmodified — including
the LIKE tier that is the only reason two-character Japanese queries work. No search code
is duplicated here, so the two paths cannot drift apart. Delete the file and
`dejavu obsidian sync` rebuilds it.

**Never damage a note a human wrote.** Every note dejavu creates carries `source: dejavu`
in its frontmatter, and nothing without that marker is ever modified. Frontmatter edits
splice single lines rather than re-serialising the block, so keys dejavu knows nothing
about — `autolink:` lists written by an embedding script, say — survive untouched.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .scope import CATEGORIES, Scope
from .store import connect, iso, normalize_keywords

UTC = timezone.utc

MARKER_KEY = "source"
MARKER_VALUE = "dejavu"

# Directories that are never part of the knowledge in a vault.
SKIP_DIRS = frozenset({".obsidian", ".trash", ".git", ".smart-env", "node_modules", "__pycache__"})

# Filesystem-hostile characters. Unicode is deliberately left alone: Japanese note titles
# are normal here, and mangling them into ASCII would make the vault unreadable.
_UNSAFE = re.compile(r'[/\\:*?"<>|\x00-\x1f]')

FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*\r?\n?", re.DOTALL)

MAX_SLUG = 80

# Bump whenever a change here would produce different rows for identical files — a new
# title rule, a different keyword set. Files are normally skipped when their mtime and
# size are unchanged, so without this an upgraded dejavu would keep serving rows built by
# the previous version's rules, and `dejavu obsidian sync` would report nothing to do.
INDEX_VERSION = 2

# Embeddings live beside the index they describe, keyed by the same `uid`. That uid is
# derived from the note's path, so a re-index never orphans a vector — and when a note is
# deleted or renamed, one DELETE at the end of a sync clears the row it left behind.
# Kept in a separate table rather than a column so that `store.SCHEMA` stays untouched and
# `search.py` keeps working over these rows without knowing embeddings exist.
VECTORS_SCHEMA = """
CREATE TABLE IF NOT EXISTS vectors (
  uid        TEXT PRIMARY KEY,
  model      TEXT    NOT NULL,
  dim        INTEGER NOT NULL,
  text_hash  TEXT    NOT NULL,
  vec        BLOB    NOT NULL,
  created_at TEXT    NOT NULL,
  -- 'index' for notes inside the indexed folders, 'link' for anything embedded by the
  -- bulk linking utility. The orphan sweep below only touches 'index' rows: a note the
  -- user pointed the utility at has no index row to be orphaned from, and deleting its
  -- vector on an unrelated sync would silently make every later run slower.
  origin     TEXT    NOT NULL DEFAULT 'index'
);
"""


def ensure_vectors(con: sqlite3.Connection) -> None:
    con.executescript(VECTORS_SCHEMA)
    columns = {row["name"] for row in con.execute("PRAGMA table_info(vectors)").fetchall()}
    if "origin" not in columns:
        # Vectors are derived data: rebuilding them costs a backfill, and carrying a
        # migration for a table that can be regenerated is not worth the code.
        con.executescript("DROP TABLE vectors;" + VECTORS_SCHEMA)


def _has_vectors(con: sqlite3.Connection) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'vectors'"
    ).fetchone()
    return row is not None


class WriteRefused(RuntimeError):
    """A write was blocked to protect a note or avoid a sync conflict."""


# ---------------------------------------------------------------- frontmatter


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (raw frontmatter, body). The raw block is kept verbatim for splicing."""
    m = FM_RE.match(text)
    if m is None:
        return None, text
    return m.group(1), text[m.end() :]


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
        return value[1:-1]
    return value


def parse_frontmatter(raw: str | None) -> dict[str, str | list[str]]:
    """Parse the handful of YAML shapes a note actually uses.

    Scalars, inline arrays (`tags: [a, b]`) and block lists (`- item` on following
    lines). Anything else is ignored rather than guessed at — a full YAML parser would
    mean a dependency, and dejavu ships with none.
    """
    data: dict[str, str | list[str]] = {}
    if not raw:
        return data
    key: str | None = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        if line[:1] in " \t":
            item = line.strip()
            if key is not None and item.startswith("-"):
                bucket = data.get(key)
                if not isinstance(bucket, list):
                    bucket = []
                    data[key] = bucket
                bucket.append(_unquote(item[1:]))
            continue
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        key = name.strip()
        value = value.strip()
        if not value:
            data[key] = []
        elif value.startswith("[") and value.endswith("]"):
            data[key] = [_unquote(x) for x in value[1:-1].split(",") if x.strip()]
        else:
            data[key] = _unquote(value)
    return data


def _scalar(value: str) -> str:
    if value == "" or value[0] in "[{\"'#&*!|>%@`" or re.search(r'[:#"]|^\s|\s$', value):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def render_frontmatter(fields: dict[str, str | list[str]]) -> str:
    """Serialise frontmatter for a *new* note. Existing notes are spliced, never re-rendered."""
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, list):
            if not value:
                continue
            lines.append(f"{key}: [{', '.join(_scalar(v) for v in value)}]")
        elif value:
            lines.append(f"{key}: {_scalar(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def splice_frontmatter(raw: str, key: str, value: list[str]) -> str:
    """Replace one key inside a frontmatter block, leaving every other line byte-identical.

    Re-serialising the whole block would be simpler and would also destroy keys dejavu
    does not understand — `autolink:` lists written by another script, comments, ordering
    a human chose. So the replacement is done line by line: the key's own line goes, any
    indented continuation of it goes with it, and nothing else is touched.
    """
    rendered = f"{key}: [{', '.join(_scalar(v) for v in value)}]"
    lines = raw.splitlines()
    out: list[str] = []
    i = 0
    replaced = False
    while i < len(lines):
        line = lines[i]
        name = line.partition(":")[0].strip()
        if not line[:1].isspace() and name == key:
            out.append(rendered)
            replaced = True
            i += 1
            # Drop the block-list form (`- item` lines) that belonged to this key.
            while i < len(lines) and (lines[i][:1].isspace() or lines[i].lstrip().startswith("-")):
                i += 1
            continue
        out.append(line)
        i += 1
    if not replaced:
        out.append(rendered)
    return "\n".join(out)


def set_frontmatter_key(
    path: Path,
    key: str,
    value: list[str],
    *,
    mode: str,
    expected_mtime_ns: int | None = None,
) -> None:
    """Rewrite a single frontmatter key in place.

    Refused on synced vaults for the same reason `replace_body` is: the file is rewritten
    whole, and another device may be mid-edit.
    """
    if mode != "full":
        raise WriteRefused(
            "The vault syncs to other devices, so rewriting frontmatter could discard an "
            "edit made elsewhere."
        )
    text = path.read_text(encoding="utf-8")
    if not is_dejavu_note(text):
        raise WriteRefused(f"{path.name} was not written by dejavu, so it will not be modified.")
    if expected_mtime_ns is not None and path.stat().st_mtime_ns != expected_mtime_ns:
        raise WriteRefused(f"{path.name} changed on disk since it was read.")
    raw, body = split_frontmatter(text)
    if raw is None:  # pragma: no cover - is_dejavu_note already implies frontmatter
        raise WriteRefused(f"{path.name} has no frontmatter.")
    path.write_text(f"---\n{splice_frontmatter(raw, key, value)}\n---\n{body}", encoding="utf-8")


def is_dejavu_note(text: str) -> bool:
    raw, _ = split_frontmatter(text)
    return parse_frontmatter(raw).get(MARKER_KEY) == MARKER_VALUE


# ---------------------------------------------------------------- write mode

SYNC_ROOTS: tuple[tuple[str, str], ...] = (
    ("Library/Mobile Documents", "iCloud Drive"),
    ("Library/CloudStorage", "a cloud storage provider (Google Drive / OneDrive / Box)"),
    ("Dropbox", "Dropbox"),
)


def detect_write_mode(vault: Path, home: Path | None = None) -> tuple[str, str]:
    """Decide how boldly dejavu may write, and say why.

    A vault that syncs to other devices can be edited from a phone mid-write, and the
    loser of that race becomes an iCloud conflict copy. Appending survives that; replacing
    a body does not. Detection covers the path-based providers plus Obsidian's own Sync,
    which leaves no trace in the path and so must be found in `.obsidian/sync.json`.
    """
    here = vault.expanduser()
    root = (home or Path.home()).expanduser()
    try:
        here = here.resolve()
        root = root.resolve()
    except OSError:  # pragma: no cover - resolve() is non-strict
        pass

    for rel, label in SYNC_ROOTS:
        base = root / rel
        try:
            base = base.resolve()
        except OSError:  # pragma: no cover
            continue
        if here == base or base in here.parents:
            return "append-only", f"the vault is inside {label}"

    if (here / ".obsidian" / "sync.json").exists():
        return "append-only", "Obsidian Sync is configured (.obsidian/sync.json)"

    return "full", "the vault is a local folder and no sync was detected"


def effective_write_mode(vault: Path, configured: str, home: Path | None = None) -> tuple[str, str]:
    if configured in ("full", "append-only"):
        return configured, f"write_mode = \"{configured}\" is set in config.toml"
    return detect_write_mode(vault, home)


# ---------------------------------------------------------------- note files


def slugify(title: str) -> str:
    slug = _UNSAFE.sub("-", title).strip().strip(".")
    slug = re.sub(r"\s+", " ", slug).strip()
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug[:MAX_SLUG].rstrip() or "note")


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for n in range(2, 1000):
        candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise WriteRefused(f"Too many notes named like {path.name}")


def subfolders(base: Path) -> list[str]:
    """Folder names directly under `base`, so callers can pick one that exists."""
    if not base.is_dir():
        return []
    return sorted(c.name for c in base.iterdir() if c.is_dir() and not c.name.startswith("."))


def _find_child(base: Path, name: str) -> Path | None:
    wanted = name.strip().lower()
    for child in sorted(base.iterdir()):
        if child.is_dir() and child.name.lower() == wanted:
            return child
    return None


def _category_dir(base: Path, category: str | None, other: str = "") -> Path:
    """Use a subfolder only when the user already made one.

    Vault layouts are personal — PARA, Zettelkasten, a flat pile. Inventing folders would
    impose dejavu's taxonomy on a vault the user has already organised their own way.

    `other` is the catch-all for notes that match no folder. Without it, a vault whose
    owner has sorted their knowledge into folders slowly accumulates loose notes beside
    those folders, until the folders are hard to see at all. It is used only when a folder
    by that name already exists, which keeps the rule above intact: someone who wants a
    flat pile does not make the folder and nothing changes for them.
    """
    if not base.is_dir():
        return base
    if category and (found := _find_child(base, category)) is not None:
        return found
    if other and (fallback := _find_child(base, other)) is not None:
        return fallback
    return base


def create_note(
    directory: Path,
    title: str,
    body: str,
    *,
    category: str | None = None,
    tags: list[str] | None = None,
    project: str | None = None,
    filename: str | None = None,
    related: list[str] | None = None,
    related_key: str = "related",
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    fields: dict[str, str | list[str]] = {}
    if category:
        fields["category"] = category
    if tags:
        fields["tags"] = tags
    fields[MARKER_KEY] = MARKER_VALUE
    if project:
        fields["project"] = project
    # Links go in at creation time rather than in a second write: one file operation
    # instead of two, and nothing to refuse on an append-only vault.
    if related:
        fields[related_key] = related
    fields["created"] = datetime.now().astimezone().strftime("%Y-%m-%d")

    path = _unique(directory / f"{filename or slugify(title)}.md")
    text = render_frontmatter(fields) + f"\n# {title}\n\n{body.strip()}\n"
    path.write_text(text, encoding="utf-8")
    return path


def append_to_note(path: Path, text: str) -> None:
    """Append to a dejavu-authored note. Safe under every sync provider."""
    existing = path.read_text(encoding="utf-8")
    if not is_dejavu_note(existing):
        raise WriteRefused(
            f"{path.name} was not written by dejavu (no `{MARKER_KEY}: {MARKER_VALUE}` in its "
            f"frontmatter). Notes you wrote by hand are never modified."
        )
    joiner = "" if existing.endswith("\n") else "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"{joiner}\n{text.strip()}\n")


def replace_body(path: Path, body: str, *, mode: str, expected_mtime_ns: int | None = None) -> None:
    """Replace a note's body, keeping its frontmatter byte-for-byte.

    Refused on synced vaults: another device may hold an edit this would silently drop.
    """
    if mode != "full":
        raise WriteRefused(
            "The vault syncs to other devices, so replacing a note body could discard an "
            "edit made elsewhere. Append instead, or set write_mode = \"full\"."
        )
    existing = path.read_text(encoding="utf-8")
    if not is_dejavu_note(existing):
        raise WriteRefused(
            f"{path.name} was not written by dejavu, so its body will not be replaced."
        )
    if expected_mtime_ns is not None and path.stat().st_mtime_ns != expected_mtime_ns:
        raise WriteRefused(
            f"{path.name} changed on disk since it was read. Re-read it before replacing."
        )
    raw, _ = split_frontmatter(existing)
    head = f"---\n{raw}\n---\n" if raw is not None else ""
    path.write_text(head + f"\n{body.strip()}\n", encoding="utf-8")


def find_note(root: Path, title: str) -> Path | None:
    """Locate an existing dejavu note by title, anywhere under `root`."""
    target = slugify(title).lower()
    for path in iter_markdown(root):
        if path.stem.lower() == target:
            return path
    return None


# ---------------------------------------------------------------- indexing


@dataclass
class IndexStats:
    added: int = 0
    updated: int = 0
    removed: int = 0
    total: int = 0
    scanned_dirs: list[str] | None = None

    def as_dict(self) -> dict:
        return {
            "added": self.added,
            "updated": self.updated,
            "removed": self.removed,
            "total": self.total,
            "folders": self.scanned_dirs or [],
        }


def iter_markdown(root: Path):
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        yield path


def stable_uid(rel_path: str) -> str:
    """A UID derived from the path, so re-indexing never renumbers a note.

    `store.new_uid` guarantees at least one a-f so a UID can never be mistaken for a
    numeric ID; the same guarantee is reproduced here by re-hashing when it does not hold.
    """
    salt = 0
    while True:
        seed = rel_path if salt == 0 else f"{rel_path}#{salt}"
        uid = hashlib.blake2b(seed.encode("utf-8"), digest_size=6).hexdigest()
        if any(c in "abcdef" for c in uid):
            return uid
        salt += 1


def split_title(body: str, path: Path) -> tuple[str, str]:
    """Lift the leading `# heading` out of the body and use it as the title.

    Leaving it in place would make every search snippet open with a copy of the title it
    is printed under — pure noise in a context window.
    """
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if line.startswith("# "):
            title = line[2:].strip()
            if title:
                return title, "\n".join(lines[i + 1 :]).strip()
        break
    return path.stem, body.strip()


def title_and_body(text: str, body: str, path: Path) -> tuple[str, str]:
    """What to call a note, and what is left of it once the name is taken out.

    dejavu writes `# <title>` as the first line of every note it creates, so for its own
    notes that heading is the title. Nobody else's notes work that way: a chapter opening
    with "Introduction" is not a note called "Introduction", and treating it as one names
    the note after a word that says nothing and feeds that same word to the embedding
    model as the note's subject — which is how a vault ends up with a dozen documents that
    all look alike because they all begin the same way.

    Obsidian's own convention is that the file name is the title, so that is what is used
    for everything dejavu did not write.
    """
    if is_dejavu_note(text):
        return split_title(body, path)
    return path.stem, body.strip()


def _keywords_for(fields: dict[str, str | list[str]], rel: Path) -> list[str]:
    words: list[str] = []
    tags = fields.get("tags")
    if isinstance(tags, list):
        words.extend(str(t).lstrip("#") for t in tags)
    elif isinstance(tags, str):
        words.extend(t.lstrip("#") for t in tags.replace(",", " ").split())
    raw_category = fields.get("category")
    if isinstance(raw_category, str) and raw_category:
        words.append(raw_category)
    words.extend(part for part in rel.parts[:-1])
    return normalize_keywords(words)


def _write_row(
    con: sqlite3.Connection,
    *,
    uid: str,
    title: str,
    body: str,
    keywords: list[str],
    category: str,
    storage: str,
    rel_path: str,
    file_hash: str,
    stamp: str,
    existing_id: int | None,
) -> None:
    kw = " ".join(keywords)
    if existing_id is None:
        cur = con.execute(
            """INSERT INTO entries
                 (uid, title, body, kw, category, storage, status, source_path, source_hash,
                  created_at, updated_at, checked_at)
               VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)""",
            (uid, title, body, kw, category, storage, rel_path, file_hash, stamp, stamp, stamp),
        )
        entry_id = int(cur.lastrowid)
    else:
        entry_id = existing_id
        con.execute(
            """UPDATE entries
                  SET title = ?, body = ?, kw = ?, category = ?, source_path = ?,
                      source_hash = ?, updated_at = ?, checked_at = ?
                WHERE id = ?""",
            (title, body, kw, category, rel_path, file_hash, stamp, stamp, entry_id),
        )
    con.execute("DELETE FROM keywords WHERE entry_id = ?", (entry_id,))
    con.executemany(
        "INSERT OR IGNORE INTO keywords(entry_id, keyword) VALUES (?, ?)",
        [(entry_id, kw_item) for kw_item in keywords],
    )


def index_markdown_tree(
    scope: Scope,
    root: Path,
    include: list[str] | None,
    *,
    storage: str,
) -> IndexStats:
    """Refresh the index from Markdown on disk, touching only what changed.

    Unchanged files are recognised by mtime+size, so a routine sync over a vault of a few
    hundred notes is a stat() each and nothing more.
    """
    stats = IndexStats(scanned_dirs=list(include) if include else ["."])
    con = connect(scope)
    try:
        reindex_all = int(con.execute("PRAGMA application_id").fetchone()[0]) != INDEX_VERSION
        if reindex_all:
            con.execute(f"PRAGMA application_id = {INDEX_VERSION}")

        known: dict[str, tuple[int, str]] = {
            row["source_path"]: (row["id"], row["source_hash"])
            for row in con.execute(
                "SELECT id, source_path, source_hash FROM entries WHERE storage = ?",
                (storage,),
            ).fetchall()
            if row["source_path"]
        }
        seen: set[str] = set()

        roots = [root / d for d in include] if include else [root]
        for base in roots:
            for path in iter_markdown(base):
                rel = path.relative_to(root)
                rel_path = rel.as_posix()
                seen.add(rel_path)
                try:
                    stat = path.stat()
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue

                file_hash = f"{stat.st_mtime_ns}:{stat.st_size}"
                previous = known.get(rel_path)
                if previous is not None and previous[1] == file_hash and not reindex_all:
                    continue

                raw, body = split_frontmatter(text)
                fields = parse_frontmatter(raw)
                raw_category = fields.get("category")
                category = (
                    raw_category
                    if isinstance(raw_category, str) and raw_category in CATEGORIES
                    else "note"
                )
                title, body = title_and_body(text, body, path)
                _write_row(
                    con,
                    uid=stable_uid(rel_path),
                    title=title,
                    body=body,
                    keywords=_keywords_for(fields, rel),
                    category=category,
                    storage=storage,
                    rel_path=rel_path,
                    file_hash=file_hash,
                    stamp=iso(datetime.fromtimestamp(stat.st_mtime, UTC)),
                    existing_id=previous[0] if previous else None,
                )
                if previous is None:
                    stats.added += 1
                else:
                    stats.updated += 1

        for rel_path, (entry_id, _) in known.items():
            if rel_path not in seen:
                con.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
                stats.removed += 1

        if stats.removed and _has_vectors(con):
            # The note is gone, so its embedding describes nothing. This is the only
            # place vectors are deleted, and it is deliberately not a JOIN on every sync:
            # nothing was removed, nothing can be orphaned.
            con.execute(
                "DELETE FROM vectors WHERE origin = 'index' "
                "AND uid NOT IN (SELECT uid FROM entries)"
            )

        con.commit()
        stats.total = int(
            con.execute(
                "SELECT COUNT(*) FROM entries WHERE storage = ?", (storage,)
            ).fetchone()[0]
        )
    finally:
        con.close()
    return stats


# The team-shared layer: Markdown that lives in the repository and travels through git.
# v0.4.0 only *reads* it — writing it out (`dejavu export` / `promote`) is still in the
# backlog, and inventing a second writer before that lands would create two sources of truth.
SHARED_DIR = "docs/knowledge"


def sync_vault(cfg, *, force: bool = False) -> IndexStats | None:
    """Refresh the vault index. Returns None when no vault is configured."""
    from . import scope as scope_mod

    if not cfg.enabled or cfg.vault is None or not cfg.vault.is_dir():
        return None
    scope = scope_mod.obsidian_scope()
    if not force and not scope.db_path.exists():
        # Never index a vault behind the user's back: `dejavu obsidian init` is what
        # opts in, and it passes force=True.
        return None
    return index_markdown_tree(scope, cfg.vault, cfg.include, storage="obsidian")


def sync_shared(root: Path) -> IndexStats | None:
    """Refresh the index of <repo>/docs/knowledge/*.md."""
    from . import scope as scope_mod

    if not (root / SHARED_DIR).is_dir():
        return None
    return index_markdown_tree(scope_mod.shared_scope(root), root, [SHARED_DIR], storage="shared")


def with_indexes(scopes: list[Scope], project_root: Path | None, cfg=None) -> list[Scope]:
    """Append the file-backed indexes to a search, refreshing them first.

    Only `search` gets these. `list`, `recent` and `resume` answer "what have I been
    working on", and hundreds of vault notes would bury that answer.
    """
    from . import scope as scope_mod

    extra: list[Scope] = []
    if project_root is not None and sync_shared(project_root) is not None:
        extra.append(scope_mod.shared_scope(project_root))
    if sync_vault(cfg if cfg is not None else scope_mod.obsidian_config()) is not None:
        extra.append(scope_mod.obsidian_scope())
    return scopes + extra


def count_in_folder(scope: Scope, folder: str) -> int:
    if not scope.db_path.exists():
        return 0
    con = connect(scope)
    try:
        return int(
            con.execute(
                "SELECT COUNT(*) FROM entries WHERE source_path LIKE ?", (f"{folder}/%",)
            ).fetchone()[0]
        )
    finally:
        con.close()
