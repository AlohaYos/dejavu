"""SQLite schema and CRUD.

Key design points:
- Markdown is the source of truth for shared knowledge (phase 4). SQLite is only a
  search index that can be thrown away and rebuilt at any time.
- UIDs are globally unique across the project and user scopes. Numeric IDs are kept
  for backwards compatibility and are meaningful only within the project scope.
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .scope import CATEGORIES, Scope

UTC = timezone.utc

SCHEMA_VERSION = 1
MAX_KEYWORDS = 15

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
  id          INTEGER PRIMARY KEY,
  uid         TEXT    NOT NULL UNIQUE,
  title       TEXT    NOT NULL,
  body        TEXT    NOT NULL DEFAULT '',
  -- Keywords joined by spaces (denormalised, for FTS).
  -- The column name MUST match the one in entries_fts: an FTS5 external-content table
  -- reads same-named columns from its content table, so a mismatch makes `rebuild`
  -- fail with "no such column: T.kw".
  kw          TEXT    NOT NULL DEFAULT '',
  category    TEXT    NOT NULL,
  storage     TEXT    NOT NULL DEFAULT 'local',
  status      TEXT,
  source_path TEXT,
  source_hash TEXT,
  created_at  TEXT    NOT NULL,
  updated_at  TEXT    NOT NULL,   -- bumped when the content changes
  checked_at  TEXT    NOT NULL    -- bumped when verified against current code (drives staleness)
);

CREATE TABLE IF NOT EXISTS keywords (
  entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
  keyword  TEXT    NOT NULL,
  PRIMARY KEY (entry_id, keyword)
);
CREATE INDEX IF NOT EXISTS idx_keywords_kw ON keywords(keyword);

CREATE TABLE IF NOT EXISTS links (
  from_uid TEXT NOT NULL,
  to_uid   TEXT NOT NULL,
  rel      TEXT NOT NULL,
  PRIMARY KEY (from_uid, to_uid, rel)
);

CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
  title, body, kw,
  content='entries', content_rowid='id',
  tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
  INSERT INTO entries_fts(rowid, title, body, kw)
    VALUES (new.id, new.title, new.body, new.kw);
END;

CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
  INSERT INTO entries_fts(entries_fts, rowid, title, body, kw)
    VALUES ('delete', old.id, old.title, old.body, old.kw);
END;

CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
  INSERT INTO entries_fts(entries_fts, rowid, title, body, kw)
    VALUES ('delete', old.id, old.title, old.body, old.kw);
  INSERT INTO entries_fts(rowid, title, body, kw)
    VALUES (new.id, new.title, new.body, new.kw);
END;
"""


@dataclass
class Entry:
    uid: str
    id: int
    title: str
    body: str
    category: str
    storage: str
    status: str | None
    keywords: list[str]
    created_at: str
    updated_at: str
    checked_at: str
    scope: str = "project"

    def stale_days(self, stale_days: dict[str, int]) -> int | None:
        """Age in days if the entry is stale, otherwise None."""
        threshold = stale_days.get(self.category, 14)
        age = (now() - _parse(self.checked_at)).days
        return age if age > threshold else None


def now() -> datetime:
    return datetime.now(UTC)


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def iso(dt: datetime | None = None) -> str:
    return (dt or now()).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_uid() -> str:
    """12 hex chars, always containing at least one a-f so it cannot be read as a numeric ID."""
    while True:
        uid = secrets.token_hex(6)
        if any(c in "abcdef" for c in uid):
            return uid


def connect(scope: Scope) -> sqlite3.Connection:
    scope.db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(scope.db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode = WAL")  # parallel worktrees / concurrent sessions
    con.execute("PRAGMA busy_timeout = 3000")
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    con.commit()
    return con


def normalize_keywords(raw: list[str] | str | None) -> list[str]:
    if raw is None:
        return []
    items = raw.split(",") if isinstance(raw, str) else list(raw)
    seen: list[str] = []
    for item in items:
        kw = item.strip().lower()
        if kw and kw not in seen:
            seen.append(kw)
    return seen[:MAX_KEYWORDS]


def _row_to_entry(row: sqlite3.Row, keywords: list[str], scope_name: str) -> Entry:
    return Entry(
        uid=row["uid"],
        id=row["id"],
        title=row["title"],
        body=row["body"],
        category=row["category"],
        storage=row["storage"],
        status=row["status"],
        keywords=keywords,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        checked_at=row["checked_at"],
        scope=scope_name,
    )


def _keywords_of(con: sqlite3.Connection, entry_id: int) -> list[str]:
    rows = con.execute(
        "SELECT keyword FROM keywords WHERE entry_id = ? ORDER BY rowid", (entry_id,)
    ).fetchall()
    return [r["keyword"] for r in rows]


def _write_keywords(con: sqlite3.Connection, entry_id: int, keywords: list[str]) -> None:
    con.execute("DELETE FROM keywords WHERE entry_id = ?", (entry_id,))
    con.executemany(
        "INSERT OR IGNORE INTO keywords(entry_id, keyword) VALUES (?, ?)",
        [(entry_id, kw) for kw in keywords],
    )
    con.execute("UPDATE entries SET kw = ? WHERE id = ?", (" ".join(keywords), entry_id))


def add_entry(
    con: sqlite3.Connection,
    *,
    title: str,
    body: str = "",
    category: str = "note",
    keywords: list[str] | None = None,
    status: str | None = None,
    storage: str | None = None,
) -> Entry:
    if category not in CATEGORIES:
        raise ValueError(f"Unknown category: {category} (expected one of: {', '.join(CATEGORIES)})")
    keywords = normalize_keywords(keywords)
    storage = storage or CATEGORIES[category][0]
    ts = iso()
    uid = new_uid()

    cur = con.execute(
        """INSERT INTO entries
             (uid, title, body, kw, category, storage, status,
              created_at, updated_at, checked_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (uid, title, body, " ".join(keywords), category, storage, status, ts, ts, ts),
    )
    entry_id = int(cur.lastrowid)
    _write_keywords(con, entry_id, keywords)
    con.commit()
    return get_entry(con, uid) or _raise_missing(uid)


def _raise_missing(ref: str) -> Entry:  # pragma: no cover - should be unreachable
    raise LookupError(f"Entry not found: {ref}")


def get_entry(con: sqlite3.Connection, ref: str, scope_name: str = "project") -> Entry | None:
    """`ref` is a UID, or a numeric ID within the project scope."""
    if ref.isdigit():
        row = con.execute("SELECT * FROM entries WHERE id = ?", (int(ref),)).fetchone()
    else:
        row = con.execute("SELECT * FROM entries WHERE uid = ?", (ref,)).fetchone()
    if row is None:
        return None
    return _row_to_entry(row, _keywords_of(con, row["id"]), scope_name)


def update_entry(
    con: sqlite3.Connection,
    entry: Entry,
    *,
    title: str | None = None,
    body: str | None = None,
    append: str | None = None,
    keywords: list[str] | None = None,
    status: str | None = None,
    storage: str | None = None,
) -> Entry:
    new_body = entry.body
    if body is not None:
        new_body = body
    if append:
        new_body = f"{new_body.rstrip()}\n\n{append}" if new_body.strip() else append

    ts = iso()
    con.execute(
        """UPDATE entries
              SET title = ?, body = ?, status = ?, storage = ?,
                  updated_at = ?, checked_at = ?
            WHERE id = ?""",
        (
            title if title is not None else entry.title,
            new_body,
            status if status is not None else entry.status,
            storage if storage is not None else entry.storage,
            ts,
            ts,  # editing implies the entry now matches reality, so reset freshness too
            entry.id,
        ),
    )
    if keywords is not None:
        _write_keywords(con, entry.id, normalize_keywords(keywords))
    con.commit()
    return get_entry(con, entry.uid, entry.scope) or _raise_missing(entry.uid)


def touch_entry(con: sqlite3.Connection, entry: Entry) -> Entry:
    """Bump checked_at only: "I verified this against the code and it is still correct"."""
    con.execute("UPDATE entries SET checked_at = ? WHERE id = ?", (iso(), entry.id))
    con.commit()
    return get_entry(con, entry.uid, entry.scope) or _raise_missing(entry.uid)


def delete_entry(con: sqlite3.Connection, entry: Entry) -> None:
    con.execute("DELETE FROM entries WHERE id = ?", (entry.id,))
    con.commit()


def list_entries(
    con: sqlite3.Connection,
    scope_name: str,
    *,
    category: str | None = None,
    status: str | None = None,
    since: str | None = None,
    limit: int | None = None,
) -> list[Entry]:
    sql = "SELECT * FROM entries WHERE 1=1"
    args: list[object] = []
    if category:
        sql += " AND category = ?"
        args.append(category)
    if status:
        sql += " AND status = ?"
        args.append(status)
    if since:
        sql += " AND updated_at >= ?"
        args.append(since)
    sql += " ORDER BY updated_at DESC"
    if limit:
        sql += " LIMIT ?"
        args.append(limit)

    rows = con.execute(sql, args).fetchall()
    return [_row_to_entry(r, _keywords_of(con, r["id"]), scope_name) for r in rows]


def rebuild_fts(con: sqlite3.Connection) -> None:
    con.execute("INSERT INTO entries_fts(entries_fts) VALUES ('rebuild')")
    con.commit()


def db_exists(path: Path) -> bool:
    return path.exists()
