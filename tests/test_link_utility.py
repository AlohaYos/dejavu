"""The one feature that edits the user's own notes, and everything that makes that safe."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import write_note

from dejavu import link, obsidian, relate
from dejavu import scope as scope_mod

HUMAN = """---
tags: [tax]
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


def embedder(table: dict[str, list[float]]):
    """Similarity the test decides, rather than similarity the test hopes for."""

    def embed(texts, *, model, host, timeout, keep_alive=""):
        out = []
        for text in texts:
            match = next((v for k, v in table.items() if k in text), None)
            out.append(relate._normalize(match if match else [0.0, 0.0, 1.0]))
        return out

    return embed


@pytest.fixture
def inbox(vault: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Two notes about the same thing, one about something else. None written by dejavu."""
    write_note(
        vault,
        "Inbox/確定申告.md",
        HUMAN.format(title="確定申告の準備", body="経費と領収書をまとめる話。" * 6),
    )
    write_note(
        vault,
        "Inbox/領収書.md",
        HUMAN.format(title="領収書の整理術", body="経費の領収書を月ごとに分ける。" * 6),
    )
    write_note(
        vault,
        "Inbox/ハワイ.md",
        HUMAN.format(title="ハワイの珈琲", body="コナコーヒーの焙煎について。" * 6),
    )
    monkeypatch.setattr(
        relate,
        "embed",
        embedder(
            {
                "確定申告": [1.0, 0.02, 0.0],
                "領収書": [1.0, 0.0, 0.02],
                "ハワイ": [0.0, 1.0, 0.0],
            }
        ),
    )
    relate._LAST = None
    return vault


# ---------------------------------------------------------------- the block


def test_the_block_is_fenced_so_its_bytes_are_known():
    text = "本文です。\n"
    out = link.upsert_block(text, ["[[A]]", "[[B]]"])

    assert link.BLOCK_START in out and link.BLOCK_END in out
    assert out.startswith("本文です。")
    assert link.strip_block(out).strip() == "本文です。"


def test_a_second_run_replaces_rather_than_repeats():
    once = link.upsert_block("本文です。\n", ["[[A]]"])
    twice = link.upsert_block(once, ["[[B]]", "[[C]]"])

    assert twice.count(link.BLOCK_START) == 1
    assert "[[A]]" not in twice
    assert "[[C]]" in twice


def test_text_written_after_the_block_survives_removal():
    text = link.upsert_block("本文です。\n", ["[[A]]"]) + "\nあとから書いた文章。\n"

    assert "あとから書いた文章。" in link.strip_block(text)
    assert "[[A]]" not in link.strip_block(text)


def test_frontmatter_is_never_touched(inbox: Path):
    path = inbox / "Inbox/確定申告.md"
    before = obsidian.split_frontmatter(path.read_text())[0]

    path.write_text(link.upsert_block(path.read_text(), ["[[領収書]]"]), encoding="utf-8")

    assert obsidian.split_frontmatter(path.read_text())[0] == before


def test_the_dejavu_marker_is_never_added(inbox: Path):
    """Adding it would let append_to_note and replace_body edit the user's own writing."""
    path = inbox / "Inbox/確定申告.md"
    path.write_text(link.upsert_block(path.read_text(), ["[[領収書]]"]), encoding="utf-8")

    assert obsidian.is_dejavu_note(path.read_text()) is False


# ---------------------------------------------------------------- planning


def test_a_plan_writes_nothing(inbox: Path):
    cfg = configure(inbox)
    before = {p: p.read_bytes() for p in obsidian.iter_markdown(inbox)}

    made = link.plan(cfg, "Inbox")

    assert made.files
    assert {p: p.read_bytes() for p in obsidian.iter_markdown(inbox)} == before


def test_only_notes_that_agree_are_linked(inbox: Path):
    made = link.plan(configure(inbox), "Inbox")
    linked = {entry["path"] for entry in made.files}

    assert linked == {"Inbox/確定申告.md", "Inbox/領収書.md"}  # not ハワイ


def test_the_plan_counts_the_users_own_notes(inbox: Path):
    made = link.plan(configure(inbox), "Inbox")

    assert made.handwritten == len(made.files)  # every one of them, in this folder


def test_txt_files_are_offered_for_renaming(inbox: Path):
    (inbox / "Inbox/メモ.txt").write_text("何かのメモ。", encoding="utf-8")

    made = link.plan(configure(inbox), "Inbox")

    assert made.renames == [{"from": "Inbox/メモ.txt", "to": "Inbox/メモ.md"}]


def test_applying_without_a_plan_id_is_impossible(inbox: Path):
    with pytest.raises(link.LinkRefused):
        link.apply(configure(inbox), "nope")


def test_a_stale_plan_is_refused(inbox: Path):
    cfg = configure(inbox)
    made = link.plan(cfg, "Inbox")

    from dejavu.store import connect

    con = connect(scope_mod.obsidian_scope())
    long_ago = datetime.now(timezone.utc) - timedelta(minutes=link.PLAN_TTL_MINUTES + 1)
    con.execute("UPDATE link_plans SET created_at = ?", (long_ago.isoformat(),))
    con.commit()
    con.close()

    with pytest.raises(link.LinkRefused, match="out of date"):
        link.apply(cfg, made.plan_id)


def test_a_note_edited_since_the_plan_is_left_alone(inbox: Path):
    cfg = configure(inbox)
    made = link.plan(cfg, "Inbox")
    edited = inbox / "Inbox/確定申告.md"
    edited.write_text(edited.read_text() + "\nあとから足した行。\n", encoding="utf-8")

    result = link.apply(cfg, made.plan_id)

    assert "Inbox/確定申告.md" in result["skipped"]
    assert link.BLOCK_START not in edited.read_text()


# ---------------------------------------------------------------- applying and backups


def test_applying_copies_every_file_before_writing_any(inbox: Path):
    cfg = configure(inbox)
    made = link.plan(cfg, "Inbox")

    result = link.apply(cfg, made.plan_id)

    backup = Path(result["backup"])
    for entry in made.files:
        assert (backup / entry["path"]).is_file()
        assert (backup / entry["path"]).read_text() != (inbox / entry["path"]).read_text()


def test_a_failure_to_copy_leaves_the_vault_untouched(inbox: Path, monkeypatch):
    cfg = configure(inbox)
    made = link.plan(cfg, "Inbox")
    before = {p: p.read_bytes() for p in obsidian.iter_markdown(inbox)}

    def refuse(*args, **kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(link.shutil, "copy2", refuse)

    with pytest.raises(link.LinkRefused, match="Nothing was changed"):
        link.apply(cfg, made.plan_id)
    assert {p: p.read_bytes() for p in obsidian.iter_markdown(inbox)} == before


def test_the_manifest_records_what_it_left_behind(inbox: Path):
    cfg = configure(inbox)
    result = link.apply(cfg, link.plan(cfg, "Inbox").plan_id)

    manifest = json.loads((Path(result["backup"]) / "manifest.json").read_text())
    for record in manifest["files"]:
        assert record["after"] == link.file_hash(inbox / record["path"])
        assert record["links_added"]


def test_the_backup_lives_outside_the_vault(inbox: Path):
    """Inside it, every copy would be synced to every device the user owns."""
    cfg = configure(inbox)

    root = link.backup_root(cfg)

    assert inbox not in root.parents and root != inbox


def test_txt_files_are_renamed_and_can_be_renamed_back(inbox: Path):
    (inbox / "Inbox/メモ.txt").write_text("何かのメモ。", encoding="utf-8")
    cfg = configure(inbox)

    link.apply(cfg, link.plan(cfg, "Inbox").plan_id)
    assert (inbox / "Inbox/メモ.md").is_file()

    link.remove(cfg)
    assert (inbox / "Inbox/メモ.txt").is_file()
    assert not (inbox / "Inbox/メモ.md").exists()


# ---------------------------------------------------------------- undoing


def test_remove_takes_out_the_links_and_nothing_else(inbox: Path):
    cfg = configure(inbox)
    originals = {p: p.read_text() for p in obsidian.iter_markdown(inbox)}
    link.apply(cfg, link.plan(cfg, "Inbox").plan_id)

    result = link.remove(cfg)

    assert result["cleaned"] == 2
    for path, text in originals.items():
        assert path.read_text().strip() == text.strip()


def test_remove_keeps_what_the_user_wrote_afterwards(inbox: Path):
    cfg = configure(inbox)
    link.apply(cfg, link.plan(cfg, "Inbox").plan_id)
    edited = inbox / "Inbox/確定申告.md"
    edited.write_text(edited.read_text() + "\nあとから書いた大事な文章。\n", encoding="utf-8")

    link.remove(cfg)

    assert "あとから書いた大事な文章。" in edited.read_text()
    assert link.BLOCK_START not in edited.read_text()


def test_restore_refuses_to_discard_a_later_edit(inbox: Path):
    cfg = configure(inbox)
    link.apply(cfg, link.plan(cfg, "Inbox").plan_id)
    edited = inbox / "Inbox/確定申告.md"
    edited.write_text(edited.read_text() + "\nあとから書いた大事な文章。\n", encoding="utf-8")

    with pytest.raises(link.LinkRefused, match="edited since"):
        link.restore(cfg)
    assert "あとから書いた大事な文章。" in edited.read_text()


def test_restore_puts_untouched_files_back_exactly(inbox: Path):
    cfg = configure(inbox)
    originals = {p: p.read_bytes() for p in obsidian.iter_markdown(inbox)}
    link.apply(cfg, link.plan(cfg, "Inbox").plan_id)

    link.restore(cfg)

    assert {p: p.read_bytes() for p in obsidian.iter_markdown(inbox)} == originals


def test_an_undone_run_is_recorded_as_undone(inbox: Path):
    cfg = configure(inbox)
    link.apply(cfg, link.plan(cfg, "Inbox").plan_id)

    link.remove(cfg)

    assert link.runs(cfg)[0]["reverted_at"] is not None


def test_there_is_a_history(inbox: Path):
    cfg = configure(inbox)
    link.apply(cfg, link.plan(cfg, "Inbox").plan_id)

    history = link.runs(cfg)

    assert len(history) == 1
    assert history[0]["files"]


# ---------------------------------------------------------------- housekeeping


def test_old_runs_are_pruned_but_only_on_the_next_run(inbox: Path):
    cfg = configure(inbox, link_keep_runs=1, link_keep_days=0)
    root = link.backup_root(cfg)
    for day in ("2020-01-01T00-00-00Z-aaaa", "2020-01-02T00-00-00Z-bbbb"):
        (root / day).mkdir(parents=True)
        (root / day / "manifest.json").write_text(
            json.dumps({"run": day, "files": [], "reverted_at": None}), encoding="utf-8"
        )

    assert len(link.runs(cfg)) == 2
    assert link.prune(cfg) == 1
    assert [m["run"] for m in link.runs(cfg)] == ["2020-01-02T00-00-00Z-bbbb"]


def test_a_hub_note_is_left_out_and_reported(vault: Path, monkeypatch):
    """A table of contents resembles everything, and linking it everywhere buries the rest."""
    for n in range(12):
        write_note(
            vault,
            f"Inbox/note{n}.md",
            HUMAN.format(title=f"ノート{n}", body=f"話題{n // 2} についての文章。" * 6),
        )
    write_note(vault, "Inbox/目次.md", HUMAN.format(title="目次", body="全体の索引。" * 6))

    def embed(texts, *, model, host, timeout, keep_alive=""):
        out = []
        for text in texts:
            if "目次" in text:
                out.append(relate._normalize([1.0] * 6))  # equally near everything
                continue
            # Six pairs. Each note is identical to its partner and unrelated to the rest.
            topic = next(n for n in range(6) if f"話題{n} " in text)
            out.append(relate._normalize([1.0 if i == topic else 0.0 for i in range(6)]))
        return out

    monkeypatch.setattr(relate, "embed", embed)
    relate._LAST = None

    made = link.plan(configure(vault, relate_min_sim=0.3), "Inbox")

    assert made.hubs == ["Inbox/目次.md"]
    assert all(entry["path"] != "Inbox/目次.md" for entry in made.files)
    # The pairs still find each other; only the note that matched everything is gone.
    assert len(made.files) == 12


# ---------------------------------------------------------------- names


def test_the_file_name_is_the_title_not_the_first_heading(vault: Path):
    """A chapter opening with "Introduction" is not a note called "Introduction".

    Taking the heading would both misname the link and feed the same generic word to the
    model as the note's subject, so every document that opens the same way starts to
    resemble every other.
    """
    path = write_note(
        vault, "Inbox/VisionGestureとは.md", "# はじめに\n\n空間ジェスチャーの話。" * 4
    )

    title, body = link._text_of(path)

    assert title == "VisionGestureとは"
    assert "はじめに" in body  # left in the body, just not treated as the subject


def test_a_dejavu_note_keeps_using_its_own_heading(vault: Path):
    """dejavu puts that heading there deliberately, so for its own notes it is the title."""
    path = obsidian.create_note(vault / "Knowledge", "書いたメモ", "本文。" * 10)

    title, _ = link._text_of(path)

    assert title == "書いたメモ"


def test_duplicate_names_are_found_among_the_notes_being_linked(vault: Path):
    """These notes are usually outside the index, so the index cannot answer this."""
    a = write_note(vault, "Inbox/2023/はじめに.md", "本文。" * 10)
    b = write_note(vault, "Inbox/2024/はじめに.md", "別の本文。" * 10)
    c = write_note(vault, "Inbox/固有の名前.md", "また別の本文。" * 10)

    ambiguous = link._ambiguous_stems(vault, [a, b, c])

    assert ambiguous == {"はじめに"}


def test_an_ambiguous_link_is_written_with_its_folder(vault: Path):
    links = relate.format_links(
        [relate.Candidate(title="はじめに", rel_path="Inbox/2024/はじめに.md", score=1.0)],
        ambiguous={"はじめに"},
    )

    assert links == ["[[Inbox/2024/はじめに]]"]


def test_the_link_block_marker_does_not_survive_into_the_embedded_text():
    """Otherwise the same note hashes differently depending on which path last read it."""
    body = "本文。" * 10 + f"\n\n---\n\n{link.BLOCK_START}\n## Related\n\n- [[x]]\n"

    assert link.BLOCK_START not in relate.strip_related_block(body)
