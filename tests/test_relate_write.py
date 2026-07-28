"""Where the links are written, and everything that must survive the writing."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from conftest import write_note

from dejavu import obsidian, relate
from dejavu import scope as scope_mod

TARGET = """---
tags: [swiftui, layout]
source: dejavu
---

# SwiftUI のレイアウト順序

親から子へサイズが提案される。
"""

SUBJECT = """---
autolink:
  - "[[手で貼ったリンク]]"
tags: [swiftui, layout]
source: dejavu
---

# SwiftUI のレイアウトでハマった件

レイアウトの提案サイズが想定と違っていた。safeArea の扱いも絡む。
"""

HUMAN = """---
tags: [swiftui, layout]
---

# 人が書いたレイアウトのメモ

これは dejavu が書いたものではない。レイアウトの話。
"""


def configure(vault: Path, **overrides):
    cfg = replace(
        scope_mod.obsidian_config(),
        vault=vault,
        include=["Knowledge", "UserInfo", "Research"],
        relate="search",
    )
    return replace(cfg, **overrides) if overrides else cfg


@pytest.fixture
def linkable(vault: Path) -> Path:
    write_note(vault, "Knowledge/layout-order.md", TARGET)
    obsidian.index_markdown_tree(
        scope_mod.obsidian_scope(), vault, ["Knowledge"], storage="obsidian"
    )
    return vault


# ---------------------------------------------------------------- new notes


def test_a_new_note_carries_its_links_in_the_frontmatter(vault: Path):
    path = obsidian.create_note(
        vault / "Knowledge",
        "新しいメモ",
        "本文。",
        tags=["swiftui"],
        related=["[[layout-order]]"],
    )
    fields = obsidian.parse_frontmatter(obsidian.split_frontmatter(path.read_text())[0])
    assert fields["related"] == ["[[layout-order]]"]
    assert fields["source"] == "dejavu"


def test_the_key_name_is_configurable(vault: Path):
    path = obsidian.create_note(
        vault / "Knowledge", "メモ", "本文。", related=["[[a]]"], related_key="autolink"
    )
    fields = obsidian.parse_frontmatter(obsidian.split_frontmatter(path.read_text())[0])
    assert fields["autolink"] == ["[[a]]"]
    assert "related" not in fields


# ---------------------------------------------------------------- existing notes


def test_full_mode_splices_the_key_and_leaves_autolink_alone(linkable: Path):
    path = write_note(linkable, "Knowledge/subject.md", SUBJECT)

    links = relate.apply_to_existing(configure(linkable), path, vault=linkable, mode="full")

    assert links
    text = path.read_text()
    fields = obsidian.parse_frontmatter(obsidian.split_frontmatter(text)[0])
    assert fields["related"] == links
    assert fields["autolink"] == ["[[手で貼ったリンク]]"]
    assert fields["tags"] == ["swiftui", "layout"]
    assert relate.RELATED_HEADING not in text  # the body is untouched in full mode


def test_append_only_adds_a_rule_and_a_section(linkable: Path):
    path = write_note(linkable, "Knowledge/subject.md", SUBJECT)

    links = relate.apply_to_existing(configure(linkable), path, vault=linkable, mode="append-only")

    assert links
    text = path.read_text()
    assert text.rstrip().endswith(f"- {links[-1]}")
    assert "\n---\n\n## Related\n" in text
    # The frontmatter was not rewritten at all.
    assert obsidian.split_frontmatter(text)[0] == obsidian.split_frontmatter(SUBJECT)[0]


def test_a_second_pass_does_not_add_a_second_section(linkable: Path):
    path = write_note(linkable, "Knowledge/subject.md", SUBJECT)
    cfg = configure(linkable)

    relate.apply_to_existing(cfg, path, vault=linkable, mode="append-only")
    once = path.read_text()
    assert relate.apply_to_existing(cfg, path, vault=linkable, mode="append-only") == []
    assert path.read_text() == once
    assert once.count(relate.RELATED_HEADING) == 1


def test_deleting_the_rule_by_hand_does_not_bring_the_section_back(linkable: Path):
    path = write_note(linkable, "Knowledge/subject.md", SUBJECT)
    cfg = configure(linkable)
    relate.apply_to_existing(cfg, path, vault=linkable, mode="append-only")

    # The user tidies up the rule but keeps the links.
    path.write_text(path.read_text().replace("\n---\n\n## Related", "\n## Related"), "utf-8")
    before = path.read_text()

    assert relate.apply_to_existing(cfg, path, vault=linkable, mode="append-only") == []
    assert path.read_text() == before


def test_later_appends_land_below_the_section_on_a_synced_vault(linkable: Path):
    """A known limitation, pinned here so it cannot change by accident.

    On an append-only vault the only tool available is "add bytes at the end", so text
    appended after the section is written ends up below it. Moving the section back to the
    bottom would mean rewriting the whole file, which is exactly what append-only exists
    to forbid. Untidy beats risking someone else's edit.
    """
    path = write_note(linkable, "Knowledge/subject.md", SUBJECT)
    cfg = configure(linkable)
    relate.apply_to_existing(cfg, path, vault=linkable, mode="append-only")

    obsidian.append_to_note(path, "あとから足した本文。")
    text = path.read_text()

    assert text.index(relate.RELATED_HEADING) < text.index("あとから足した本文。")
    assert text.count(relate.RELATED_HEADING) == 1


def test_a_note_dejavu_did_not_write_is_never_touched(linkable: Path):
    path = write_note(linkable, "Knowledge/human.md", HUMAN)

    assert relate.apply_to_existing(configure(linkable), path, vault=linkable, mode="full") == []
    assert path.read_text() == HUMAN


def test_off_writes_nothing(linkable: Path):
    path = write_note(linkable, "Knowledge/subject.md", SUBJECT)
    cfg = configure(linkable, relate="off")

    assert relate.apply_to_existing(cfg, path, vault=linkable, mode="full") == []
    assert path.read_text() == SUBJECT


def test_nothing_to_link_means_nothing_written(linkable: Path):
    path = write_note(
        linkable,
        "Knowledge/unrelated.md",
        "---\ntags: [tax]\nsource: dejavu\n---\n\n# 確定申告\n\n" + "領収書をまとめる。" * 5,
    )
    before = path.read_text()

    assert relate.apply_to_existing(configure(linkable), path, vault=linkable, mode="full") == []
    assert path.read_text() == before


# ---------------------------------------------------------------- block helpers


def test_the_heading_alone_decides_whether_a_section_exists():
    assert relate.has_related_block("body\n\n---\n\n## Related\n\n- [[a]]\n")
    assert relate.has_related_block("body\n\n## Related\n\n- [[a]]\n")
    assert not relate.has_related_block("body\n\n## Related notes\n")


def test_stripping_takes_the_rule_with_it():
    body = "本文。\n\n---\n\n## Related\n\n- [[a]]\n"
    assert relate.strip_related_block(body).strip() == "本文。"


def test_stripping_a_note_without_a_section_changes_nothing():
    body = "本文。\n\n---\n\nまだ続く。\n"
    assert relate.strip_related_block(body) == body


def test_splicing_replaces_a_block_list_without_touching_its_neighbours():
    raw = 'autolink:\n  - "[[x]]"\ntags: [a]\nsource: dejavu'
    out = obsidian.splice_frontmatter(raw, "autolink", ["[[y]]"])
    assert out == 'autolink: ["[[y]]"]\ntags: [a]\nsource: dejavu'


def test_splicing_a_missing_key_appends_it():
    raw = "tags: [a]\nsource: dejavu"
    out = obsidian.splice_frontmatter(raw, "related", ["[[y]]"])
    assert out.splitlines()[-1] == 'related: ["[[y]]"]'


def test_frontmatter_cannot_be_rewritten_on_a_synced_vault(vault: Path):
    path = write_note(vault, "Knowledge/subject.md", SUBJECT)
    with pytest.raises(obsidian.WriteRefused):
        obsidian.set_frontmatter_key(path, "related", ["[[a]]"], mode="append-only")
