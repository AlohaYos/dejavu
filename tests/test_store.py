from __future__ import annotations

import pytest

from dejavu import safety
from dejavu import scope as scope_mod
from dejavu.store import (
    add_entry,
    delete_entry,
    get_entry,
    iso,
    list_entries,
    new_uid,
    normalize_keywords,
    now,
    rebuild_fts,
    touch_entry,
    update_entry,
)


def test_uid_always_contains_a_hex_letter():
    """The invariant that stops a UID from being mistaken for a numeric ID."""
    for _ in range(500):
        uid = new_uid()
        assert len(uid) == 12
        assert any(c in "abcdef" for c in uid), uid
        assert not uid.isdigit()


def test_keywords_are_normalized_deduped_and_capped():
    kws = normalize_keywords("  FTS5 , fts5, Search ,, " + ",".join(f"k{i}" for i in range(20)))
    assert kws[:2] == ["fts5", "search"]
    assert len(kws) == 15  # MAX_KEYWORDS


def test_add_and_get_by_uid_and_numeric_id(con):
    entry = add_entry(con, title="t", body="b", category="note", keywords=["x"])
    assert get_entry(con, entry.uid).title == "t"
    assert get_entry(con, str(entry.id)).uid == entry.uid


def test_update_bumps_updated_and_resets_checked(con):
    entry = add_entry(con, title="t", body="old", category="note")
    updated = update_entry(con, entry, append="added")
    assert "old" in updated.body and "added" in updated.body
    assert updated.updated_at >= entry.updated_at
    assert updated.checked_at >= entry.checked_at


def test_touch_changes_checked_but_not_updated(con):
    entry = add_entry(con, title="t", body="b", category="note")
    con.execute(
        "UPDATE entries SET updated_at = ?, checked_at = ? WHERE id = ?",
        ("2020-01-01T00:00:00Z", "2020-01-01T00:00:00Z", entry.id),
    )
    con.commit()

    touched = touch_entry(con, get_entry(con, entry.uid))
    assert touched.updated_at == "2020-01-01T00:00:00Z"  # content untouched
    assert touched.checked_at > "2020-01-01T00:00:00Z"  # freshness reset


def test_staleness_is_derived_from_checked_at_not_updated_at(con, project):
    entry = add_entry(con, title="t", body="b", category="feature")  # 7-day threshold
    scope = scope_mod.project_scope(project)
    assert entry.stale_days(scope.stale_days) is None

    con.execute(
        "UPDATE entries SET checked_at = ? WHERE id = ?",
        (iso(now().replace(year=now().year - 1)), entry.id),
    )
    con.commit()
    old = get_entry(con, entry.uid)
    assert old.stale_days(scope.stale_days) is not None
    assert old.stale_days(scope.stale_days) > 7


def test_delete_removes_the_row_from_fts(con):
    entry = add_entry(con, title="doomed entry", body="body", category="note")
    delete_entry(con, entry)
    assert get_entry(con, entry.uid) is None
    assert con.execute("SELECT count(*) AS n FROM entries_fts").fetchone()["n"] == 0


def test_fts_rebuild_works(con):
    """An external-content FTS table whose column names drift from the content table
    fails with "no such column". Trigger-driven writes pass explicit values and so never
    surface the bug; only a rebuild does. Pin the behaviour here.
    """
    add_entry(con, title="検索実装のメモ", body="body", category="feature", keywords=["fts5"])
    rebuild_fts(con)

    row = con.execute(
        "SELECT count(*) AS n FROM entries_fts WHERE entries_fts MATCH ?", ('"検索実装"',)
    ).fetchone()
    assert row["n"] == 1


def test_unknown_category_is_rejected(con):
    with pytest.raises(ValueError):
        add_entry(con, title="t", category="bogus")


def test_list_filters(con):
    add_entry(con, title="a", category="plan", status="proposed")
    add_entry(con, title="b", category="plan", status="done")
    add_entry(con, title="c", category="note")

    assert len(list_entries(con, "project", category="plan")) == 2
    assert len(list_entries(con, "project", status="proposed")) == 1


# ---- safety ----


@pytest.mark.parametrize(
    "text",
    [
        "key is sk-abcdefghijklmnopqrstuvwxyz123456",
        "token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123",
        "AWS AKIAIOSFODNN7EXAMPLE here",
        "-----BEGIN RSA PRIVATE KEY-----",
        'password = "hunter2hunter2hunter2"',
        "curl -H 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz'",
    ],
)
def test_secrets_are_detected(text):
    assert safety.find_secrets(text)


def test_ordinary_text_is_not_flagged():
    assert safety.find_secrets("search_entries() は src/db.rs で3段階検索を行う") == []
    assert safety.find_secrets("API rate limit is 100 req/min") == []


def test_duplicate_detection():
    candidates = [("a1b2c3d4e5f6", "検索実装のメモ"), ("f6e5d4c3b2a1", "認証の設計")]
    assert safety.find_duplicate("検索実装のメモ", candidates) is not None
    assert safety.find_duplicate("まったく別の話題", candidates) is None
