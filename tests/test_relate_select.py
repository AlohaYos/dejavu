"""Which notes get linked, and how the link is spelled."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from conftest import write_note

from dejavu import obsidian, relate
from dejavu import scope as scope_mod


def configure(vault: Path, **overrides):
    cfg = replace(
        scope_mod.obsidian_config(),
        vault=vault,
        include=["Knowledge", "UserInfo", "Research"],
        relate="search",
    )
    return replace(cfg, **overrides) if overrides else cfg


def index(vault: Path) -> None:
    obsidian.index_markdown_tree(
        scope_mod.obsidian_scope(),
        vault,
        ["Knowledge", "UserInfo", "Research"],
        storage="obsidian",
    )


def note(title: str, body: str, tags: str = "") -> str:
    head = f"tags: [{tags}]\n" if tags else ""
    return f"---\n{head}source: dejavu\n---\n\n# {title}\n\n{body}\n"


@pytest.fixture
def populated(vault: Path) -> Path:
    write_note(
        vault,
        "Knowledge/ignoresSafeArea.md",
        note("ignoresSafeArea の落とし穴", "safeAreaInsets が 0 になる話。", "swiftui,layout"),
    )
    write_note(
        vault,
        "Knowledge/layout-order.md",
        note("SwiftUI のレイアウト順序", "親から子へサイズが提案される。", "swiftui,layout"),
    )
    write_note(
        vault,
        "Knowledge/hawaii.md",
        note("ハワイの珈琲", "コナコーヒーの話。まったく関係がない。", "coffee"),
    )
    index(vault)
    return vault


def test_links_to_notes_that_share_words(populated: Path):
    links = relate.suggest_for_new(
        configure(populated),
        title="SwiftUI のレイアウトでハマった件",
        body="レイアウトの提案サイズが想定と違っていた。" * 3,
        keywords=["swiftui", "layout"],
    )
    assert links
    assert any("layout-order" in link for link in links)
    assert not any("hawaii" in link for link in links)


def test_an_unrelated_note_is_not_linked(populated: Path):
    links = relate.suggest_for_new(
        configure(populated),
        title="確定申告の準備",
        body="領収書をまとめて経費を計算する。" * 3,
        keywords=["tax"],
    )
    assert links == []


def test_top_k_caps_the_list(populated: Path):
    links = relate.suggest_for_new(
        configure(populated, relate_top_k=1),
        title="SwiftUI のレイアウト調査",
        body="レイアウトと safeArea の関係を調べた。" * 3,
        keywords=["swiftui", "layout"],
    )
    assert len(links) == 1


def test_a_note_shorter_than_min_chars_is_left_alone(populated: Path):
    links = relate.suggest_for_new(
        configure(populated),
        title="SwiftUI のレイアウト",
        body="短い。",
        keywords=["swiftui", "layout"],
    )
    assert links == []


def test_off_means_off(populated: Path):
    links = relate.suggest_for_new(
        configure(populated, relate="off"),
        title="SwiftUI のレイアウト調査",
        body="レイアウトと safeArea の関係を調べた。" * 3,
        keywords=["swiftui", "layout"],
    )
    assert links == []


def test_notes_already_linked_by_hand_are_not_linked_again(populated: Path):
    body = "レイアウトの話。すでに [[layout-order]] は自分で貼ってある。" * 3
    links = relate.suggest_for_new(
        configure(populated),
        title="SwiftUI のレイアウト調査",
        body=body,
        keywords=["swiftui", "layout"],
    )
    assert not any("layout-order" in link for link in links)


def test_the_note_itself_is_never_a_candidate(populated: Path):
    path = populated / "Knowledge/layout-order.md"
    cands = relate._candidates(
        configure(populated),
        title="SwiftUI のレイアウト順序",
        keywords=["swiftui", "layout"],
        body="親から子へサイズが提案される。",
        exclude_paths={"Knowledge/layout-order.md"},
        exclude_targets=set(),
    )
    assert path.exists()
    assert all(c.rel_path != "Knowledge/layout-order.md" for c in cands)


def test_a_duplicated_filename_is_linked_by_path(vault: Path):
    write_note(vault, "Knowledge/notes.md", note("認証まわり", "OAuth の話。" * 5, "auth"))
    write_note(vault, "Research/notes.md", note("別の notes", "無関係。" * 5, "misc"))
    index(vault)

    ambiguous = relate._ambiguous_stems(scope_mod.obsidian_scope())
    assert ambiguous == {"notes"}

    links = relate.format_links(
        [relate.Candidate(title="認証まわり", rel_path="Knowledge/notes.md", score=1.0)],
        ambiguous=ambiguous,
    )
    assert links == ["[[Knowledge/notes|認証まわり]]"]


def test_a_unique_filename_is_linked_bare(vault: Path):
    links = relate.format_links(
        [relate.Candidate(title="layout-order", rel_path="Knowledge/layout-order.md", score=1.0)],
        ambiguous=set(),
    )
    assert links == ["[[layout-order]]"]


def test_the_title_becomes_the_display_text_when_it_differs(vault: Path):
    links = relate.format_links(
        [relate.Candidate(title="SwiftUI のレイアウト順序", rel_path="Knowledge/lo.md", score=1.0)],
        ambiguous=set(),
    )
    assert links == ["[[lo|SwiftUI のレイアウト順序]]"]


def test_two_character_japanese_still_finds_notes(vault: Path):
    """The LIKE tier is the only one that can match 検索. Dropping weak hits must not
    drop this case — that is the guarantee the whole project is built on."""
    write_note(vault, "Knowledge/search-impl.md", note("検索の実装", "三段構えで引く。" * 5))
    index(vault)

    cands = relate._candidates(
        configure(vault),
        title="検索",
        keywords=None,
        body="検索まわりの調べもの。" * 5,
        exclude_paths=set(),
        exclude_targets=set(),
    )
    assert [c.rel_path for c in cands] == ["Knowledge/search-impl.md"]
