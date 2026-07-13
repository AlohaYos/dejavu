"""`dejavu resume` and `dejavu recent`.

The point of `resume` is that it is *deterministic*: it returns the newest `context`
entry regardless of how that entry happens to be titled. Searching for words like
"next" or "continue" would miss a note called "作業ログ" or "handoff". These tests
pin that down — several deliberately use titles containing no recall keywords at all.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from dejavu import scope as scope_mod
from dejavu.cli import main
from dejavu.store import (
    ACTIVITY_CATEGORIES,
    add_entry,
    connect,
    iso,
    latest_context,
    now,
    recent_entries,
)


def _backdate(con, uid: str, days: int) -> None:
    ts = iso(now() - timedelta(days=days))
    con.execute("UPDATE entries SET updated_at = ?, created_at = ? WHERE uid = ?", (ts, ts, uid))
    con.commit()


# ---- resume ----


def test_resume_returns_the_newest_context_entry(con):
    old = add_entry(con, title="古い引き継ぎメモ", body="old", category="context")
    _backdate(con, old.uid, 5)
    newest = add_entry(con, title="作業ログ", body="new", category="context")

    found = latest_context(con, "project")
    assert found is not None
    assert found.uid == newest.uid


def test_resume_does_not_depend_on_the_title(con):
    """A handoff note titled with no recall keywords must still be found.

    This is exactly the case a keyword search would miss, and the reason `resume`
    exists as a separate command.
    """
    entry = add_entry(con, title="ぼちぼち", body="今日はここまで", category="context")
    found = latest_context(con, "project")
    assert found is not None and found.uid == entry.uid


def test_resume_ignores_other_categories(con):
    """A newer plan or decision must not shadow the latest context entry."""
    ctx = add_entry(con, title="handoff", body="ctx", category="context")
    add_entry(con, title="newer plan", body="p", category="plan")
    add_entry(con, title="newer decision", body="d", category="decision")

    found = latest_context(con, "project")
    assert found is not None
    assert found.uid == ctx.uid
    assert found.category == "context"


def test_resume_returns_none_when_there_is_no_context(con):
    add_entry(con, title="only a feature note", body="b", category="feature")
    assert latest_context(con, "project") is None


def test_resume_exits_2_when_nothing_to_resume(project, capsys):
    assert main(["resume"]) == 2
    assert "No handoff note" in capsys.readouterr().err


def test_resume_prints_the_body_in_full(project, con, capsys):
    body = "## Done\n- " + "x" * 400 + "\n\n## Next\n- write the export tests"
    add_entry(con, title="NEXT: export", body=body, category="context")
    con.close()

    assert main(["resume"]) == 0
    out = capsys.readouterr().out
    assert "write the export tests" in out  # the tail survived
    assert "…" not in out  # not snippet-trimmed


def test_resume_reports_a_human_readable_age(project, con, capsys):
    entry = add_entry(con, title="handoff", body="b", category="context")
    _backdate(con, entry.uid, 3)
    con.close()

    main(["resume"])
    assert "3 days ago" in capsys.readouterr().out


# ---- recent ----


def test_recent_defaults_to_activity_categories_only(con):
    """Research caches would bury an activity log in noise, so they are excluded."""
    add_entry(con, title="ctx", category="context")
    add_entry(con, title="plan", category="plan")
    add_entry(con, title="decision", category="decision")
    add_entry(con, title="feature", category="feature")
    add_entry(con, title="note", category="note")

    since = iso(now() - timedelta(days=2))
    got = {e.category for e in recent_entries(con, "project", since=since)}
    assert got == set(ACTIVITY_CATEGORIES)
    assert "feature" not in got and "note" not in got


def test_recent_can_be_asked_for_an_excluded_category(con):
    add_entry(con, title="feature", category="feature")
    since = iso(now() - timedelta(days=2))
    got = recent_entries(con, "project", since=since, category="feature")
    assert [e.title for e in got] == ["feature"]


def test_recent_respects_the_since_window(con):
    inside = add_entry(con, title="yesterday", category="context")
    _backdate(con, inside.uid, 1)
    outside = add_entry(con, title="last week", category="context")
    _backdate(con, outside.uid, 7)

    since = iso(now() - timedelta(days=2))
    titles = [e.title for e in recent_entries(con, "project", since=since)]
    assert titles == ["yesterday"]


@pytest.mark.parametrize("days,expected", [(0, "today"), (1, "yesterday"), (4, "4 days ago")])
def test_age_phrase(con, days, expected):
    entry = add_entry(con, title="t", category="context")
    _backdate(con, entry.uid, days)
    refreshed = latest_context(con, "project")
    assert refreshed is not None
    assert refreshed.age_phrase == expected


def test_recent_default_window_is_two_days(project, con, capsys):
    old = add_entry(con, title="three days ago", category="context")
    _backdate(con, old.uid, 3)
    add_entry(con, title="today's work", category="context")
    con.close()

    assert main(["recent"]) == 0
    out = capsys.readouterr().out
    assert "today's work" in out
    assert "three days ago" not in out


def test_recent_groups_by_day(project, con, capsys):
    a = add_entry(con, title="entry A", category="context")
    _backdate(con, a.uid, 1)
    add_entry(con, title="entry B", category="plan")
    con.close()

    main(["recent"])
    out = capsys.readouterr().out
    assert "(today)" in out
    assert "(yesterday)" in out


def test_recent_spans_project_and_user_scopes(project, con):
    add_entry(con, title="project ctx", category="context")
    con.close()

    ucon = connect(scope_mod.user_scope())
    add_entry(ucon, title="user ctx", category="context")
    ucon.close()

    assert main(["recent"]) == 0
