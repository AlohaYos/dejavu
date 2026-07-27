"""Frontmatter handling, write-mode detection, and the guards that protect human notes."""

from __future__ import annotations

from pathlib import Path

import pytest

from dejavu import obsidian

AUTOLINK_NOTE = """---
autolink:
  - "[[関連ノート A]]"
  - "[[関連ノート B]]"
tags: [swiftui, layout]
source: dejavu
---

# ignoresSafeArea の落とし穴

safeAreaInsets.bottom が 0 になる。
"""

HUMAN_NOTE = """---
tags: [hawaii]
---

# 手書きのメモ

これは人間が書いた。
"""


# ---------------------------------------------------------------- frontmatter


def test_parses_block_lists_inline_lists_and_scalars():
    raw, body = obsidian.split_frontmatter(AUTOLINK_NOTE)
    fields = obsidian.parse_frontmatter(raw)

    assert fields["autolink"] == ["[[関連ノート A]]", "[[関連ノート B]]"]
    assert fields["tags"] == ["swiftui", "layout"]
    assert fields["source"] == "dejavu"
    assert body.startswith("\n# ignoresSafeArea")


def test_note_without_frontmatter_is_all_body():
    raw, body = obsidian.split_frontmatter("# タイトル\n\n本文\n")
    assert raw is None
    assert body == "# タイトル\n\n本文\n"


def test_marker_distinguishes_dejavu_notes_from_human_ones():
    assert obsidian.is_dejavu_note(AUTOLINK_NOTE)
    assert not obsidian.is_dejavu_note(HUMAN_NOTE)


def test_appending_preserves_the_autolink_block(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text(AUTOLINK_NOTE, encoding="utf-8")

    obsidian.append_to_note(note, "## 追記\n\nタブバーは約83pt。")

    text = note.read_text(encoding="utf-8")
    assert '- "[[関連ノート A]]"' in text
    assert '- "[[関連ノート B]]"' in text
    assert "タブバーは約83pt。" in text
    # The frontmatter block itself must be untouched, not re-serialised.
    assert text.startswith(AUTOLINK_NOTE.split("---\n\n")[0])


def test_refuses_to_append_to_a_note_a_human_wrote(tmp_path: Path):
    note = tmp_path / "human.md"
    note.write_text(HUMAN_NOTE, encoding="utf-8")

    with pytest.raises(obsidian.WriteRefused, match="not written by dejavu"):
        obsidian.append_to_note(note, "勝手に足された行")

    assert note.read_text(encoding="utf-8") == HUMAN_NOTE


def test_created_notes_carry_the_marker_and_round_trip(tmp_path: Path):
    path = obsidian.create_note(
        tmp_path / "Knowledge",
        "ignoresSafeArea の落とし穴",
        "safeAreaInsets が 0 になる。",
        category="note",
        tags=["swiftui", "layout"],
        project="GiLens",
    )
    text = path.read_text(encoding="utf-8")
    fields = obsidian.parse_frontmatter(obsidian.split_frontmatter(text)[0])

    assert obsidian.is_dejavu_note(text)
    assert fields["tags"] == ["swiftui", "layout"]
    assert fields["project"] == "GiLens"
    assert path.name == "ignoresSafeArea の落とし穴.md"


def test_a_second_note_with_the_same_title_never_overwrites(tmp_path: Path):
    first = obsidian.create_note(tmp_path, "同じ題", "一つ目")
    second = obsidian.create_note(tmp_path, "同じ題", "二つ目")

    assert first != second
    assert "一つ目" in first.read_text(encoding="utf-8")
    assert "二つ目" in second.read_text(encoding="utf-8")


def test_notes_land_in_a_category_folder_only_when_it_already_exists(tmp_path: Path):
    (tmp_path / "Patterns").mkdir()

    inside = obsidian.create_note(obsidian._category_dir(tmp_path, "patterns"), "A", "x")
    outside = obsidian.create_note(obsidian._category_dir(tmp_path, "architecture"), "B", "x")

    assert inside.parent.name == "Patterns"
    assert outside.parent == tmp_path


def test_slug_keeps_japanese_and_drops_path_separators():
    assert obsidian.slugify("認証/実装: メモ") == "認証-実装- メモ"
    assert obsidian.slugify("   ") == "note"


# ---------------------------------------------------------------- write mode


@pytest.mark.parametrize(
    ("relative", "expected_reason"),
    [
        ("Library/Mobile Documents/iCloud~md~obsidian/Documents/Vault", "iCloud Drive"),
        ("Library/CloudStorage/GoogleDrive-me/Vault", "cloud storage provider"),
        ("Dropbox/Vault", "Dropbox"),
    ],
)
def test_synced_locations_are_append_only(tmp_path: Path, relative: str, expected_reason: str):
    vault = tmp_path / relative
    vault.mkdir(parents=True)

    mode, reason = obsidian.detect_write_mode(vault, home=tmp_path)

    assert mode == "append-only"
    assert expected_reason in reason


def test_obsidian_sync_is_detected_even_in_a_local_folder(tmp_path: Path):
    vault = tmp_path / "Documents" / "Vault"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / ".obsidian" / "sync.json").write_text("{}", encoding="utf-8")

    mode, reason = obsidian.detect_write_mode(vault, home=tmp_path)

    assert mode == "append-only"
    assert "Obsidian Sync" in reason


def test_a_plain_local_folder_allows_full_writes(tmp_path: Path):
    vault = tmp_path / "Documents" / "Vault"
    vault.mkdir(parents=True)

    mode, reason = obsidian.detect_write_mode(vault, home=tmp_path)

    assert mode == "full"
    assert "no sync" in reason


def test_configured_mode_overrides_detection(tmp_path: Path):
    vault = tmp_path / "Dropbox" / "Vault"
    vault.mkdir(parents=True)

    mode, reason = obsidian.effective_write_mode(vault, "full", home=tmp_path)

    assert mode == "full"
    assert "config.toml" in reason


def test_body_replacement_is_refused_on_a_synced_vault(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text(AUTOLINK_NOTE, encoding="utf-8")

    with pytest.raises(obsidian.WriteRefused, match="syncs to other devices"):
        obsidian.replace_body(note, "新しい本文", mode="append-only")

    assert "safeAreaInsets" in note.read_text(encoding="utf-8")


def test_body_replacement_keeps_frontmatter_and_honours_the_mtime_guard(tmp_path: Path):
    note = tmp_path / "note.md"
    note.write_text(AUTOLINK_NOTE, encoding="utf-8")
    stamp = note.stat().st_mtime_ns

    obsidian.replace_body(note, "新しい本文", mode="full", expected_mtime_ns=stamp)
    text = note.read_text(encoding="utf-8")
    assert '- "[[関連ノート A]]"' in text
    assert "新しい本文" in text
    assert "safeAreaInsets" not in text

    with pytest.raises(obsidian.WriteRefused, match="changed on disk"):
        obsidian.replace_body(note, "さらに別の本文", mode="full", expected_mtime_ns=stamp - 1)
