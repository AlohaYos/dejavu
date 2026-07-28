"""The regression test for the failure this feature could most easily cause.

Writing a link changes a note. A changed note gets re-indexed. If re-indexing could
trigger linking, dejavu would rewrite the same note forever. These tests pin down that it
cannot: indexing never writes, and running the write path twice is a no-op.
"""

from __future__ import annotations

import hashlib
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
tags: [swiftui, layout]
source: dejavu
---

# SwiftUI のレイアウトでハマった件

レイアウトの提案サイズが想定と違っていた。safeArea の扱いも絡む。
"""


def digest(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def configure(vault: Path, **overrides):
    cfg = replace(
        scope_mod.obsidian_config(),
        vault=vault,
        include=["Knowledge", "UserInfo", "Research"],
        relate="search",
    )
    return replace(cfg, **overrides) if overrides else cfg


@pytest.fixture
def pair(vault: Path) -> tuple[Path, Path]:
    write_note(vault, "Knowledge/layout-order.md", TARGET)
    subject = write_note(vault, "Knowledge/subject.md", SUBJECT)
    obsidian.sync_vault(configure(vault), force=True)
    return vault, subject


@pytest.mark.parametrize("mode", ["append-only", "full"])
def test_write_sync_write_leaves_the_file_byte_identical(pair: tuple[Path, Path], mode: str):
    vault, subject = pair
    cfg = configure(vault)

    assert relate.apply_to_existing(cfg, subject, vault=vault, mode=mode)
    obsidian.sync_vault(cfg, force=True)
    after_first = digest(subject)

    relate.apply_to_existing(cfg, subject, vault=vault, mode=mode)
    obsidian.sync_vault(cfg, force=True)

    assert digest(subject) == after_first


def test_indexing_never_writes_to_the_vault(pair: tuple[Path, Path]):
    vault, subject = pair
    cfg = configure(vault)
    relate.apply_to_existing(cfg, subject, vault=vault, mode="append-only")

    before = {p: digest(p) for p in obsidian.iter_markdown(vault)}
    for _ in range(3):
        obsidian.sync_vault(cfg, force=True)

    assert {p: digest(p) for p in obsidian.iter_markdown(vault)} == before


def test_the_links_it_wrote_do_not_feed_back_into_the_next_query(pair: tuple[Path, Path]):
    """The section is stripped before the note becomes a query.

    Left in, `[[layout-order]]` would itself become a search term, and the note would keep
    finding the notes it already links to — a slow drift nobody would notice.
    """
    vault, subject = pair
    cfg = configure(vault)
    relate.apply_to_existing(cfg, subject, vault=vault, mode="append-only")
    obsidian.sync_vault(cfg, force=True)

    text = subject.read_text()
    body = obsidian.split_frontmatter(text)[1]
    assert relate.RELATED_HEADING in body
    assert relate.RELATED_HEADING not in relate.strip_related_block(body)
    assert "layout-order" not in relate.strip_related_block(body)
