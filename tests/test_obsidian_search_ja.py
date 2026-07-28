"""Japanese search must work over the vault index exactly as it does over the database.

The index is built from `store.SCHEMA` verbatim so that `search.py` runs over it
unmodified — which is the only reason the LIKE fallback, and therefore two-character
Japanese search, applies to vault notes at all. If these go red, the index schema has
drifted from `entries` and search has silently been reimplemented.

The Japanese strings are the point of these tests, not decoration. Do not translate them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import write_note

from dejavu import obsidian
from dejavu import scope as scope_mod
from dejavu.search import search
from dejavu.store import add_entry, connect


@pytest.fixture
def indexed(vault: Path) -> Path:
    write_note(
        vault,
        "Knowledge/検索の実装メモ.md",
        "---\ntags: [fts5, sqlite]\nsource: dejavu\n---\n\n"
        "# 検索実装のメモ\n\n三段階検索は trigram と LIKE を併用する。\n",
    )
    write_note(
        vault,
        "Knowledge/認証.md",
        "---\ntags: [auth, jwt]\nsource: dejavu\n---\n\n"
        "# 認証まわりの設計判断\n\nJWT ではなくセッション Cookie を採用した。\n",
    )
    write_note(
        vault,
        "UserInfo/Profile.md",
        "# プロフィール\n\n1998年に Newton MessagePad 向けの日本語入力を開発した。\n",
    )
    obsidian.index_markdown_tree(
        scope_mod.obsidian_scope(), vault, ["Knowledge", "UserInfo", "Research"], storage="obsidian"
    )
    return vault


def _titles(query: str, **kw) -> list[str]:
    results = search([scope_mod.obsidian_scope()], query, **kw)
    return [hit.entry.title for hit, _ in results]


@pytest.mark.parametrize(
    ("query", "expected_fragment"),
    [
        ("検索", "検索実装"),  # two-char Japanese: unreachable via trigram
        ("認証", "認証まわり"),
        ("実装", "検索実装"),
        ("設計", "認証まわり"),
    ],
)
def test_two_char_terms_hit_vault_notes(indexed, query, expected_fragment):
    titles = _titles(query)
    assert any(expected_fragment in t for t in titles), f"{query!r} returned no results"


def test_tags_are_searchable_as_keywords(indexed):
    assert any("認証" in t for t in _titles("jwt"))
    assert any("検索実装" in t for t in _titles("sqlite"))


def test_body_text_is_searchable(indexed):
    # Named "Profile" after its file: the note has no `source: dejavu`, so its heading is
    # a heading rather than its title.
    assert any("Profile" in t for t in _titles("MessagePad"))


def test_no_match_returns_empty(indexed):
    assert _titles("まったく存在しない語彙xyz") == []


def test_vault_hits_report_the_obsidian_scope(indexed):
    results = search([scope_mod.obsidian_scope()], "認証")
    assert results
    assert all(sc.name == "obsidian" for _, sc in results)


def test_project_and_vault_are_searched_together(indexed, project: Path):
    scope = scope_mod.project_scope(project)
    assert scope is not None
    con = connect(scope)
    add_entry(
        con,
        title="認証まわりの実装メモ",
        body="このリポジトリでは Cookie を使う",
        category="decision",
        keywords=["auth"],
    )
    con.close()

    results = search([scope, scope_mod.obsidian_scope()], "認証")
    found = {sc.name for _, sc in results}

    assert found == {"project", "obsidian"}
