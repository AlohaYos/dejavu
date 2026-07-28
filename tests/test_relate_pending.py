"""The queue that makes an outage cost a delay instead of a permanent gap.

The damage from a missing vector is not the missing link. It is that the note stays out of
every future comparison, silently, forever. These tests are about that being temporary.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import write_note

from dejavu import obsidian, relate
from dejavu import scope as scope_mod

NOTE = """---
tags: [swiftui, layout]
source: dejavu
---

# {title}

{body}
"""


def configure(vault: Path, **overrides):
    cfg = replace(
        scope_mod.obsidian_config(),
        vault=vault,
        include=["Knowledge", "UserInfo", "Research"],
        relate="embed",
    )
    return replace(cfg, **overrides) if overrides else cfg


def working(calls: list | None = None):
    def embedder(texts, *, model, host, timeout, keep_alive=""):
        if calls is not None:
            calls.append(list(texts))
        return [relate._normalize([float(len(t) % 7) + 1.0, 2.0, 3.0]) for t in texts]

    return embedder


def broken(*args, **kwargs):
    raise relate.OllamaUnavailable("Connection refused")


@pytest.fixture
def two_notes(vault: Path) -> Path:
    write_note(
        vault,
        "Knowledge/layout.md",
        NOTE.format(title="レイアウトの提案サイズ", body="safeArea と提案サイズの話。" * 6),
    )
    write_note(
        vault,
        "Knowledge/layout-2.md",
        NOTE.format(title="レイアウトの続き", body="提案サイズをもう一度整理する。" * 6),
    )
    obsidian.sync_vault(configure(vault), force=True)
    return vault


# ---------------------------------------------------------------- filling the queue


def test_a_failed_embedding_becomes_a_queue_entry(two_notes: Path, monkeypatch):
    cfg = configure(two_notes)
    monkeypatch.setattr(relate, "embed", broken)
    relate._LAST = None

    assert relate.remember(cfg, two_notes / "Knowledge/layout.md", vault=two_notes) == "deferred"
    assert [row["rel_path"] for row in relate.pending(cfg)] == ["Knowledge/layout.md"]


def test_the_note_is_still_saved_and_simply_has_no_links_yet(two_notes: Path, monkeypatch):
    """A model server being down is not a reason to lose someone's writing."""
    cfg = configure(two_notes)
    monkeypatch.setattr(relate, "embed", broken)
    relate._LAST = None

    path = write_note(
        two_notes,
        "Knowledge/fresh.md",
        NOTE.format(title="新しいノート", body="レイアウトの提案サイズの続き。" * 6),
    )
    before = path.read_text()

    links = relate.apply_to_existing(cfg, path, vault=two_notes, mode="full")

    assert links == []
    assert path.read_text() == before  # nothing written, nothing damaged


def test_words_are_not_quietly_substituted_for_meaning(two_notes: Path, monkeypatch):
    """On a synced vault a word-link can never be corrected, so it is not written."""
    cfg = configure(two_notes)
    monkeypatch.setattr(relate, "embed", broken)
    relate._LAST = None

    links = relate.suggest_for_new(
        cfg,
        title="レイアウトの提案サイズについて",
        body="safeArea と提案サイズをもう一度整理する。" * 6,
        keywords=["swiftui", "layout"],
    )

    assert links == []


# ---------------------------------------------------------------- emptying it


def test_draining_stores_the_vector_and_writes_the_links(two_notes: Path, monkeypatch):
    cfg = configure(two_notes)
    monkeypatch.setattr(relate, "embed", broken)
    relate._LAST = None
    relate.remember(cfg, two_notes / "Knowledge/layout.md", vault=two_notes)
    relate.remember(cfg, two_notes / "Knowledge/layout-2.md", vault=two_notes)
    assert len(relate.pending(cfg)) == 2

    monkeypatch.setattr(relate, "embed", working())
    relate._LAST = None
    relate.clear_down(cfg)

    resolved, failed = relate.drain(cfg)

    assert (resolved, failed) == (2, 0)
    assert relate.pending(cfg) == []
    assert relate.vector_counts(cfg)[0] == 2


def test_a_write_drains_a_few_without_being_asked(two_notes: Path, monkeypatch):
    """The backlog disappears while the user does something else entirely."""
    cfg = configure(two_notes)
    monkeypatch.setattr(relate, "embed", broken)
    relate._LAST = None
    relate.remember(cfg, two_notes / "Knowledge/layout.md", vault=two_notes)

    monkeypatch.setattr(relate, "embed", working())
    relate._LAST = None
    relate.clear_down(cfg)

    resolved, _ = relate.catch_up(cfg)

    assert resolved == 1
    assert relate.pending(cfg) == []


def test_a_write_during_an_outage_does_not_try_to_drain(two_notes: Path, monkeypatch):
    cfg = configure(two_notes)
    monkeypatch.setattr(relate, "embed", broken)
    relate._LAST = None
    relate.remember(cfg, two_notes / "Knowledge/layout.md", vault=two_notes)

    calls: list = []
    monkeypatch.setattr(relate, "embed", working(calls))
    relate._LAST = None
    # `mark_down` is still in force from the failure above.

    relate.catch_up(cfg)

    assert calls == []  # no point paying a timeout for an answer already known


def test_the_drain_on_a_write_is_bounded(two_notes: Path, monkeypatch):
    """Saving a note must not turn into clearing a hundred-note backlog."""
    cfg = configure(two_notes)
    for n in range(8):
        write_note(
            two_notes,
            f"Knowledge/n{n}.md",
            NOTE.format(title=f"ノート{n}", body="レイアウトの話をする。" * 6),
        )
    obsidian.sync_vault(cfg, force=True)
    monkeypatch.setattr(relate, "embed", broken)
    relate._LAST = None
    for n in range(8):
        relate.remember(cfg, two_notes / f"Knowledge/n{n}.md", vault=two_notes)
    assert len(relate.pending(cfg)) == 8

    monkeypatch.setattr(relate, "embed", working())
    relate._LAST = None
    relate.clear_down(cfg)

    resolved, _ = relate.catch_up(cfg)

    assert resolved == relate.DRAIN_ON_WRITE
    assert len(relate.pending(cfg)) == 8 - relate.DRAIN_ON_WRITE


def test_a_note_that_keeps_failing_leaves_the_queue(two_notes: Path, monkeypatch):
    """A queue that can never empty is the same as no signal at all."""
    cfg = configure(two_notes)
    monkeypatch.setattr(relate, "embed", broken)
    relate._LAST = None
    path = two_notes / "Knowledge/layout.md"
    for _ in range(relate.MAX_ATTEMPTS + 1):
        relate.clear_down(cfg)
        relate.remember(cfg, path, vault=two_notes)

    relate.clear_down(cfg)
    relate.drain(cfg)

    assert relate.pending(cfg) == []


# ---------------------------------------------------------------- the deadline


def test_waiting_too_long_falls_back_to_words(two_notes: Path, monkeypatch):
    """Deferring is a bet that the model comes back. The bet has a deadline."""
    cfg = configure(two_notes)
    monkeypatch.setattr(relate, "embed", broken)
    relate._LAST = None
    path = two_notes / "Knowledge/layout.md"
    relate.remember(cfg, path, vault=two_notes)

    con = relate._open_state()
    long_ago = datetime.now(timezone.utc) - timedelta(days=cfg.relate_defer_days + 1)
    con.execute("UPDATE pending_relate SET queued_at = ?", (long_ago.isoformat(),))
    con.commit()
    con.close()

    assert relate.expire_deferred(cfg) == 1
    fields = obsidian.parse_frontmatter(obsidian.split_frontmatter(path.read_text())[0])
    assert fields.get("related")  # linked by words rather than left with nothing


def test_a_fresh_entry_is_not_expired(two_notes: Path, monkeypatch):
    cfg = configure(two_notes)
    monkeypatch.setattr(relate, "embed", broken)
    relate._LAST = None
    relate.remember(cfg, two_notes / "Knowledge/layout.md", vault=two_notes)

    assert relate.expire_deferred(cfg) == 0


def test_search_mode_has_nothing_to_do_with_any_of_this(two_notes: Path):
    cfg = configure(two_notes, relate="search")

    assert relate.catch_up(cfg) == (0, 0)
    assert relate.drain(cfg) == (0, 0)
