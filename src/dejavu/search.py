"""Three-tier search. Recall is prioritised over precision.

  Tier 1: FTS5 trigram full-text search (terms of 3+ chars, joined with OR — not AND)
  Tier 2: the keywords table
  Tier 3: LIKE fallback

Tier 3 is NOT a nicety. The trigram tokenizer never matches query terms shorter than
three characters, yet many common Japanese words are exactly two characters
(検索 / 認証 / 実装 / 設計 …). Remove the LIKE tier and Japanese search silently collapses
to zero results.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .scope import Scope
from .store import Entry, _keywords_of, _row_to_entry

MIN_TRIGRAM_LEN = 3

# Weights for the merged score. FTS leads; keyword and LIKE hits are additive boosts.
W_FTS = 1.0
W_KEYWORD = 0.5
W_LIKE = 0.25

# Fire the LIKE tier even for long terms when tiers 1+2 returned fewer than this many hits.
FALLBACK_THRESHOLD = 3


@dataclass
class Hit:
    entry: Entry
    score: float
    tiers: list[str]


def _tokenize(query: str) -> list[str]:
    return [t for t in query.split() if t]


def _fts_expr(terms: list[str]) -> str | None:
    """Build the FTS5 match expression, joining terms with OR rather than AND.

    Passing a space-separated query straight to FTS5 ANDs every term together, so a
    single mismatched word drops the result set to zero. Casting a wide net with OR and
    letting bm25 rank the results gives far better recall.
    """
    usable = [t for t in terms if len(t) >= MIN_TRIGRAM_LEN]
    if not usable:
        return None
    quoted = ['"' + t.replace('"', '""') + '"' for t in usable]
    return " OR ".join(quoted)


def _like_escape(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _search_one(
    con: sqlite3.Connection,
    scope_name: str,
    query: str,
    *,
    category: str | None,
    since: str | None,
    limit: int,
) -> list[Hit]:
    terms = _tokenize(query)
    if not terms:
        return []

    scores: dict[int, float] = {}
    tiers: dict[int, list[str]] = {}

    def bump(entry_id: int, amount: float, tier: str) -> None:
        scores[entry_id] = scores.get(entry_id, 0.0) + amount
        tiers.setdefault(entry_id, [])
        if tier not in tiers[entry_id]:
            tiers[entry_id].append(tier)

    # ---- Tier 1: FTS5 (trigram, OR) ----
    expr = _fts_expr(terms)
    if expr:
        rows = con.execute(
            """SELECT rowid AS id, bm25(entries_fts, 10.0, 1.0, 5.0) AS rank
                 FROM entries_fts
                WHERE entries_fts MATCH ?
                ORDER BY rank
                LIMIT 200""",
            (expr,),
        ).fetchall()
        # bm25 returns negative values where lower is better. Normalise to 0..1.
        if rows:
            ranks = [r["rank"] for r in rows]
            best, worst = min(ranks), max(ranks)
            span = (worst - best) or 1.0
            for r in rows:
                normalized = (worst - r["rank"]) / span  # best maps to 1.0
                bump(r["id"], W_FTS * (0.4 + 0.6 * normalized), "fts")

    # ---- Tier 2: keywords table ----
    for term in terms:
        low = term.lower()
        rows = con.execute(
            """SELECT DISTINCT entry_id AS id FROM keywords
                WHERE keyword = ? OR keyword LIKE ? ESCAPE '\\'""",
            (low, _like_escape(low) + "%"),
        ).fetchall()
        for r in rows:
            bump(r["id"], W_KEYWORD, "keyword")

    # ---- Tier 3: LIKE fallback ----
    has_short_term = any(len(t) < MIN_TRIGRAM_LEN for t in terms)
    if has_short_term or len(scores) < FALLBACK_THRESHOLD:
        for term in terms:
            pattern = f"%{_like_escape(term)}%"
            rows = con.execute(
                """SELECT id FROM entries
                    WHERE title LIKE ? ESCAPE '\\'
                       OR body  LIKE ? ESCAPE '\\'
                       OR kw    LIKE ? ESCAPE '\\'""",
                (pattern, pattern, pattern),
            ).fetchall()
            for r in rows:
                bump(r["id"], W_LIKE, "like")

    if not scores:
        return []

    placeholders = ",".join("?" * len(scores))
    sql = f"SELECT * FROM entries WHERE id IN ({placeholders})"
    args: list[object] = list(scores.keys())
    if category:
        sql += " AND category = ?"
        args.append(category)
    if since:
        sql += " AND updated_at >= ?"
        args.append(since)

    hits = [
        Hit(
            entry=_row_to_entry(row, _keywords_of(con, row["id"]), scope_name),
            score=scores[row["id"]],
            tiers=tiers[row["id"]],
        )
        for row in con.execute(sql, args).fetchall()
    ]
    # Sort by score, breaking ties with the most recently updated entry.
    hits.sort(key=lambda h: h.entry.updated_at, reverse=True)
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:limit]


def search(
    scopes: list[Scope],
    query: str,
    *,
    category: str | None = None,
    since: str | None = None,
    limit: int = 10,
) -> list[tuple[Hit, Scope]]:
    """Search across several scopes and merge the results by score."""
    from .store import connect  # imported here to avoid a circular import

    merged: list[tuple[Hit, Scope]] = []
    for scope in scopes:
        if not scope.db_path.exists():
            continue
        con = connect(scope)
        try:
            for hit in _search_one(
                con, scope.name, query, category=category, since=since, limit=limit
            ):
                merged.append((hit, scope))
        finally:
            con.close()

    merged.sort(key=lambda pair: pair[0].score, reverse=True)
    return merged[:limit]
