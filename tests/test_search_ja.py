"""The load-bearing tests for Japanese search.

The FTS5 trigram tokenizer never matches query terms shorter than three characters, and
many everyday Japanese words are exactly two (検索 / 認証 / 実装 / 設計). If the LIKE
fallback breaks, Japanese search silently returns nothing at all.

The Japanese strings below are the point of these tests, not decoration: they are the
only thing that proves the fallback still works. Do not translate them.
"""

from __future__ import annotations

import pytest

from dejavu import scope as scope_mod
from dejavu.search import _search_one
from dejavu.store import add_entry


@pytest.fixture
def seeded(con):
    add_entry(
        con,
        title="検索実装のメモ",
        body="search_entries() は src/db.rs で3段階検索を行う",
        category="feature",
        keywords=["fts5", "trigram", "search", "sqlite"],
    )
    add_entry(
        con,
        title="NEXT: user-scope markdown export/sync の続き",
        body="前回ここで終了。次は export のテストを書く",
        category="context",
        keywords=["user-scope", "markdown", "export", "next-steps"],
    )
    add_entry(
        con,
        title="認証まわりの設計判断",
        body="JWT ではなくセッション Cookie を採用した理由",
        category="decision",
        keywords=["auth", "jwt", "cookie", "adr"],
    )
    return con


def _titles(con, query, **kw):
    hits = _search_one(con, "project", query, category=None, since=None, limit=10, **kw)
    return [h.entry.title for h in hits]


@pytest.mark.parametrize(
    ("query", "expected_fragment"),
    [
        ("検索", "検索実装"),  # two-char Japanese: unreachable via trigram
        ("認証", "認証まわり"),
        ("実装", "検索実装"),
        ("db", "検索実装"),  # two-char ASCII, same problem
    ],
)
def test_two_char_terms_hit_via_like_fallback(seeded, query, expected_fragment):
    titles = _titles(seeded, query)
    assert any(expected_fragment in t for t in titles), f"{query!r} returned no results"


def test_multiword_query_uses_or_not_and(seeded):
    """Space-joining terms into FTS5 ANDs them, so one stray word zeroes out the results."""
    titles = _titles(seeded, "markdown export 存在しない語")
    assert any("markdown export" in t for t in titles)


def test_ascii_term_is_case_insensitive(seeded):
    assert any("認証" in t for t in _titles(seeded, "jwt"))
    assert any("認証" in t for t in _titles(seeded, "JWT"))


def test_keyword_tier_matches(seeded):
    assert any("検索実装" in t for t in _titles(seeded, "sqlite"))


def test_multiple_terms_return_multiple_entries(seeded):
    hits = _search_one(seeded, "project", "trigram cookie", category=None, since=None, limit=10)
    assert len(hits) >= 2


def test_no_match_returns_empty(seeded):
    assert _titles(seeded, "まったく存在しない語彙xyz") == []


def test_category_filter(seeded):
    hits = _search_one(seeded, "project", "続き", category="context", since=None, limit=10)
    assert len(hits) == 1
    assert hits[0].entry.category == "context"

    hits = _search_one(seeded, "project", "続き", category="decision", since=None, limit=10)
    assert hits == []


def test_search_spans_project_and_user_scopes(seeded, project):
    from dejavu.search import search
    from dejavu.store import connect

    user = scope_mod.user_scope()
    ucon = connect(user)
    add_entry(
        ucon,
        title="個人メモ: zsh の設定",
        body="fzf のキーバインドを変えた",
        category="note",
        keywords=["zsh", "fzf"],
    )
    ucon.close()

    scopes = scope_mod.resolve_read(None, project)
    assert {s.name for s in scopes} == {"project", "user"}

    results = search(scopes, "zsh")
    assert any(hit.entry.scope == "user" for hit, _ in results)
