"""Indexing a vault: what gets stored, what gets skipped, and what survives a re-sync."""

from __future__ import annotations

import time
from pathlib import Path

from conftest import write_note

from dejavu import obsidian
from dejavu import scope as scope_mod
from dejavu.store import connect

NOTE_WITH_FM = """---
category: decision
tags: [swiftui, layout]
source: dejavu
---

# ignoresSafeArea の落とし穴

safeAreaInsets.bottom が 0 になる。
"""

NOTE_WITHOUT_FM = """# 素のノート

frontmatter は無い。
"""


def _index(vault: Path) -> obsidian.IndexStats:
    return obsidian.index_markdown_tree(
        scope_mod.obsidian_scope(),
        vault,
        ["Knowledge", "UserInfo", "Research"],
        storage="obsidian",
    )


def _rows() -> list[dict]:
    scope = scope_mod.obsidian_scope()
    con = connect(scope)
    try:
        return [dict(r) for r in con.execute("SELECT * FROM entries ORDER BY source_path")]
    finally:
        con.close()


def test_first_index_stores_title_body_and_keywords(vault: Path):
    write_note(vault, "Knowledge/patterns.md", NOTE_WITH_FM)

    stats = _index(vault)

    assert (stats.added, stats.updated, stats.removed, stats.total) == (1, 0, 0, 1)
    row = _rows()[0]
    assert row["title"] == "ignoresSafeArea の落とし穴"
    assert "safeAreaInsets" in row["body"]
    assert row["storage"] == "obsidian"
    assert row["source_path"] == "Knowledge/patterns.md"
    # tags, the frontmatter category and the containing folder all become searchable.
    assert set(row["kw"].split()) == {"swiftui", "layout", "decision", "knowledge"}


def test_frontmatter_category_is_used_only_when_dejavu_knows_it(vault: Path):
    write_note(vault, "Knowledge/known.md", NOTE_WITH_FM)  # category: decision
    write_note(
        vault,
        "Knowledge/unknown.md",
        "---\ncategory: pattern\n---\n\n# 別のノート\n\n本文\n",
    )

    _index(vault)

    by_path = {r["source_path"]: r for r in _rows()}
    assert by_path["Knowledge/known.md"]["category"] == "decision"
    # `pattern` is not a dejavu category, so the row stays filterable as a plain note …
    assert by_path["Knowledge/unknown.md"]["category"] == "note"
    # … but the word itself is still searchable.
    assert "pattern" in by_path["Knowledge/unknown.md"]["kw"]


def test_a_note_dejavu_did_not_write_is_named_by_its_file(vault: Path):
    """Obsidian's convention, and the only one that holds for someone else's notes.

    A heading like "Introduction" is not the name of a note; taking it would name the note
    after a word that says nothing and hand that same word to the embedding model as the
    note's subject.
    """
    write_note(vault, "Knowledge/plain.md", NOTE_WITHOUT_FM)

    _index(vault)

    row = _rows()[0]
    assert row["title"] == "plain"
    assert "素のノート" in row["body"]  # the heading stays where the author put it


def test_a_note_dejavu_wrote_is_named_by_its_heading(vault: Path):
    """dejavu puts that line there itself, so for its own notes it really is the title."""
    write_note(
        vault,
        "Knowledge/mine.md",
        "---\nsource: dejavu\n---\n\n# 書いたメモ\n\n本文。\n",
    )

    _index(vault)

    assert _rows()[0]["title"] == "書いたメモ"


def test_title_falls_back_to_the_filename_when_there_is_no_heading(vault: Path):
    write_note(vault, "Knowledge/名前だけ.md", "本文しかない\n")

    _index(vault)

    assert _rows()[0]["title"] == "名前だけ"


def test_resync_touches_only_what_changed(vault: Path):
    write_note(vault, "Knowledge/a.md", NOTE_WITH_FM)
    write_note(vault, "Knowledge/b.md", NOTE_WITHOUT_FM)
    _index(vault)

    unchanged = _index(vault)
    assert (unchanged.added, unchanged.updated, unchanged.removed) == (0, 0, 0)

    time.sleep(0.01)
    write_note(vault, "Knowledge/b.md", NOTE_WITHOUT_FM + "\n追記した。\n")
    after = _index(vault)

    assert (after.added, after.updated, after.removed) == (0, 1, 0)
    assert "追記した。" in {r["source_path"]: r["body"] for r in _rows()}["Knowledge/b.md"]


def test_deleted_notes_leave_the_index(vault: Path):
    write_note(vault, "Knowledge/gone.md", NOTE_WITH_FM)
    _index(vault)

    (vault / "Knowledge" / "gone.md").unlink()
    stats = _index(vault)

    assert (stats.removed, stats.total) == (1, 0)


def test_uid_is_derived_from_the_path_so_reindexing_never_renumbers(vault: Path):
    write_note(vault, "Knowledge/stable.md", NOTE_WITH_FM)
    _index(vault)
    first = _rows()[0]["uid"]

    time.sleep(0.01)
    write_note(vault, "Knowledge/stable.md", NOTE_WITH_FM + "\n変更。\n")
    _index(vault)

    assert _rows()[0]["uid"] == first
    assert obsidian.stable_uid("Knowledge/stable.md") == first
    assert any(c in "abcdef" for c in first), "must never look like a numeric id"


def test_folders_outside_include_and_dotfolders_are_skipped(vault: Path):
    write_note(vault, "Knowledge/kept.md", NOTE_WITH_FM)
    write_note(vault, "Apple Notes/private.md", "# 個人メモ\n\nハワイ旅行\n")
    write_note(vault, ".obsidian/plugins/readme.md", "# プラグイン\n")

    _index(vault)

    assert [r["source_path"] for r in _rows()] == ["Knowledge/kept.md"]


def test_leading_heading_becomes_the_title_and_leaves_the_body(vault: Path):
    write_note(vault, "Knowledge/h1.md", NOTE_WITH_FM)

    _index(vault)

    row = _rows()[0]
    assert row["title"] == "ignoresSafeArea の落とし穴"
    # Repeating the title inside the snippet would be pure noise in a context window.
    assert not row["body"].startswith("#")
    assert row["body"] == "safeAreaInsets.bottom が 0 になる。"


def test_an_index_format_bump_rebuilds_rows_whose_files_never_changed(vault: Path):
    write_note(vault, "Knowledge/a.md", NOTE_WITH_FM)
    _index(vault)

    scope = scope_mod.obsidian_scope()
    con = connect(scope)
    # Simulate an upgrade: rows were written by an older set of rules, the file did not move.
    con.execute("PRAGMA application_id = 0")
    con.execute("UPDATE entries SET title = 'stale title'")
    con.commit()
    con.close()

    stats = _index(vault)

    assert stats.updated == 1
    assert _rows()[0]["title"] == "ignoresSafeArea の落とし穴"


def test_index_is_disposable(vault: Path):
    write_note(vault, "Knowledge/a.md", NOTE_WITH_FM)
    _index(vault)

    scope_mod.obsidian_scope().db_path.unlink()
    rebuilt = _index(vault)

    assert (rebuilt.added, rebuilt.total) == (1, 1)


def test_indexed_notes_are_never_reported_as_stale(vault: Path):
    write_note(vault, "Knowledge/old.md", NOTE_WITH_FM)
    old = vault / "Knowledge" / "old.md"
    import os

    ancient = time.time() - 400 * 86400
    os.utime(old, (ancient, ancient))
    _index(vault)

    scope = scope_mod.obsidian_scope()
    con = connect(scope)
    try:
        from dejavu.store import _keywords_of, _row_to_entry

        row = con.execute("SELECT * FROM entries").fetchone()
        entry = _row_to_entry(row, _keywords_of(con, row["id"]), scope.name)
    finally:
        con.close()

    assert entry.stale_days(scope.stale_days) is None
