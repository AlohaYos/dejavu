"""Linking by meaning.

Ollama is never actually contacted. `relate.embed` is replaced by a fake that returns
vectors chosen by hand, which makes similarity a thing the test decides rather than a
thing the test hopes for.
"""

from __future__ import annotations

import json
import urllib.error
from array import array
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import write_note

from dejavu import obsidian, relate
from dejavu import scope as scope_mod

NOTE = """---
tags: [swiftui]
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


def fake_embedder(table: dict[str, list[float]], *, calls: list | None = None):
    """Return the vector whose key appears in the text; default to something orthogonal."""

    def embedder(texts, *, model, host, timeout, keep_alive=""):
        if calls is not None:
            calls.append(list(texts))
        out = []
        for text in texts:
            match = next((v for k, v in table.items() if k in text), None)
            out.append(relate._normalize(match if match else [0.0, 0.0, 1.0]))
        return out

    return embedder


@pytest.fixture
def vault_with_vectors(vault: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    write_note(
        vault,
        "Knowledge/near.md",
        NOTE.format(title="ほぼ同じ話", body="レイアウトの提案サイズについて。" * 4),
    )
    write_note(
        vault,
        "Knowledge/far.md",
        NOTE.format(title="まったく別の話", body="ハワイの珈琲について。" * 4),
    )
    cfg = configure(vault)
    obsidian.sync_vault(cfg, force=True)

    monkeypatch.setattr(
        relate,
        "embed",
        fake_embedder({"ほぼ同じ話": [1.0, 0.0, 0.0], "まったく別の話": [0.0, 1.0, 0.0]}),
    )
    relate._LAST = None
    relate.backfill(cfg)
    return vault


# ---------------------------------------------------------------- the text that is embedded


def test_the_related_section_is_not_part_of_what_a_note_means():
    body = "本文。" * 10 + "\n\n---\n\n## Related\n\n- [[somewhere]]\n"
    material = relate.embed_text_for("タイトル", body)
    assert "Related" not in material
    assert "somewhere" not in material


def test_code_blocks_are_left_out():
    body = "説明の文章。\n\n```swift\nlet x = ignoresSafeArea()\n```\n\n続きの文章。"
    material = relate.embed_text_for("タイトル", body)
    assert "ignoresSafeArea" not in material
    assert "続きの文章" in material


def test_text_is_truncated():
    material = relate.embed_text_for("t", "あ" * 10_000)
    assert len(material) == relate.MAX_EMBED_CHARS


def test_the_hash_follows_the_meaning_not_the_file():
    body = "本文です。" * 10
    before = relate.text_hash(relate.embed_text_for("タイトル", body))
    after = relate.text_hash(
        relate.embed_text_for("タイトル", body + "\n\n---\n\n## Related\n\n- [[x]]\n")
    )
    assert before == after


def test_bumping_the_version_changes_every_hash(monkeypatch: pytest.MonkeyPatch):
    before = relate.text_hash("同じテキスト")
    monkeypatch.setattr(relate, "EMBED_VERSION", relate.EMBED_VERSION + 1)
    assert relate.text_hash("同じテキスト") != before


# ---------------------------------------------------------------- talking to Ollama


def test_a_dead_ollama_raises_rather_than_returning_junk(monkeypatch: pytest.MonkeyPatch):
    def refuse(url, payload, timeout):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(relate, "_post", refuse)
    with pytest.raises(relate.OllamaUnavailable):
        relate.embed(["x"], model="bge-m3", host="http://localhost:11434", timeout=1)


def test_a_missing_model_raises(monkeypatch: pytest.MonkeyPatch):
    def not_found(url, payload, timeout):
        raise urllib.error.HTTPError(url, 500, "no such model", {}, None)

    monkeypatch.setattr(relate, "_post", not_found)
    with pytest.raises(relate.OllamaUnavailable):
        relate.embed(["x"], model="nope", host="http://localhost:11434", timeout=1)


def test_an_old_ollama_falls_back_to_the_single_prompt_endpoint(monkeypatch: pytest.MonkeyPatch):
    seen = []

    def dispatch(url, payload, timeout):
        seen.append(url)
        if url.endswith(relate.EMBED_PATH):
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)
        return {"embedding": [3.0, 4.0]}

    monkeypatch.setattr(relate, "_post", dispatch)
    vectors = relate.embed(["x"], model="bge-m3", host="http://localhost:11434", timeout=1)

    assert seen[-1].endswith(relate.LEGACY_EMBED_PATH)
    assert vectors[0] == array("f", [0.6, 0.8])  # normalised


def test_vectors_come_back_normalised(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(relate, "_post", lambda *a, **k: {"embeddings": [[3.0, 4.0]]})
    vec = relate.embed(["x"], model="m", host="h", timeout=1)[0]
    assert abs(sum(v * v for v in vec) - 1.0) < 1e-6


def test_a_short_answer_is_refused(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(relate, "_post", lambda *a, **k: {"embeddings": [[1.0, 0.0]]})
    with pytest.raises(relate.OllamaUnavailable):
        relate.embed(["a", "b"], model="m", host="h", timeout=1)


def test_the_request_body_is_what_ollama_expects(monkeypatch: pytest.MonkeyPatch):
    sent = {}

    class FakeResponse:
        def read(self):
            return json.dumps({"embeddings": [[1.0, 0.0]]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout):
        sent["url"] = request.full_url
        sent["payload"] = json.loads(request.data)
        return FakeResponse()

    monkeypatch.setattr(relate.urllib.request, "urlopen", urlopen)
    relate.embed(["hello"], model="bge-m3", host="http://localhost:11434/", timeout=1)

    assert sent["url"] == "http://localhost:11434/api/embed"
    assert sent["payload"] == {"model": "bge-m3", "input": ["hello"]}


# ---------------------------------------------------------------- choosing by meaning


def test_the_closest_note_wins(vault_with_vectors: Path):
    cands = relate._by_vector(
        configure(vault_with_vectors),
        title="ほぼ同じ話",
        body="レイアウトの提案サイズについて。" * 4,
        exclude_paths=set(),
        exclude_targets=set(),
    )
    assert [c.rel_path for c in cands] == ["Knowledge/near.md"]


def test_min_sim_drops_everything_that_is_not_close(vault_with_vectors: Path):
    cands = relate._by_vector(
        configure(vault_with_vectors, relate_min_sim=0.99),
        title="半分だけ似た話",
        body="どちらにも少しだけ似ている。" * 4,
        exclude_paths=set(),
        exclude_targets=set(),
    )
    assert cands == []


def test_the_note_itself_is_excluded(vault_with_vectors: Path):
    cands = relate._by_vector(
        configure(vault_with_vectors),
        title="ほぼ同じ話",
        body="レイアウトの提案サイズについて。" * 4,
        exclude_paths={"Knowledge/near.md"},
        exclude_targets=set(),
    )
    assert cands == []


def test_an_unreachable_ollama_defers_instead_of_guessing(
    vault_with_vectors: Path, monkeypatch: pytest.MonkeyPatch
):
    """No fallback to words here — see the comment in `_candidates` for why."""

    def refuse(*args, **kwargs):
        raise relate.OllamaUnavailable("cannot reach Ollama")

    monkeypatch.setattr(relate, "embed", refuse)
    relate._LAST = None

    cands = relate._candidates(
        configure(vault_with_vectors),
        title="ほぼ同じ話",
        keywords=["swiftui"],
        body="レイアウトの提案サイズについて。" * 4,
        exclude_paths=set(),
        exclude_targets=set(),
    )
    assert cands == []


# ---------------------------------------------------------------- storing vectors


def test_backfill_embeds_every_note_once(vault: Path, monkeypatch: pytest.MonkeyPatch):
    write_note(vault, "Knowledge/a.md", NOTE.format(title="A", body="本文である。" * 12))
    write_note(vault, "Knowledge/b.md", NOTE.format(title="B", body="別の本文である。" * 12))
    cfg = configure(vault)
    obsidian.sync_vault(cfg, force=True)

    calls: list = []
    monkeypatch.setattr(relate, "embed", fake_embedder({}, calls=calls))
    relate._LAST = None

    embedded, total = relate.backfill(cfg)
    assert (embedded, total) == (2, 2)
    assert sum(len(c) for c in calls) == 2

    # A second run has nothing to do: the text has not changed.
    calls.clear()
    assert relate.backfill(cfg)[0] == 0
    assert calls == []


def test_rebuild_starts_again_from_nothing(vault: Path, monkeypatch: pytest.MonkeyPatch):
    write_note(vault, "Knowledge/a.md", NOTE.format(title="A", body="本文である。" * 12))
    cfg = configure(vault)
    obsidian.sync_vault(cfg, force=True)
    monkeypatch.setattr(relate, "embed", fake_embedder({}))
    relate._LAST = None
    relate.backfill(cfg)

    assert relate.backfill(cfg, rebuild=True)[0] == 1


def test_a_deleted_note_takes_its_vector_with_it(vault: Path, monkeypatch: pytest.MonkeyPatch):
    path = write_note(vault, "Knowledge/a.md", NOTE.format(title="A", body="本文である。" * 12))
    write_note(vault, "Knowledge/b.md", NOTE.format(title="B", body="別の本文である。" * 12))
    cfg = configure(vault)
    obsidian.sync_vault(cfg, force=True)
    monkeypatch.setattr(relate, "embed", fake_embedder({}))
    relate._LAST = None
    relate.backfill(cfg)
    assert relate.vector_counts(cfg) == (2, 2)

    path.unlink()
    obsidian.sync_vault(cfg, force=True)

    assert relate.vector_counts(cfg) == (1, 1)


def test_a_new_note_is_embedded_without_a_second_model_call(
    vault: Path, monkeypatch: pytest.MonkeyPatch
):
    """`suggest_for_new` runs before the file exists, `remember` right after. One call."""
    cfg = configure(vault)
    obsidian.sync_vault(cfg, force=True)

    calls: list = []
    monkeypatch.setattr(relate, "embed", fake_embedder({}, calls=calls))
    relate._LAST = None

    body = "新しいノートの本文。" * 5
    relate.suggest_for_new(cfg, title="新しいノート", body=body, keywords=["swiftui"])
    path = obsidian.create_note(vault / "Knowledge", "新しいノート", body)
    obsidian.sync_vault(cfg, force=True)

    assert relate.remember(cfg, path, vault=vault) == "stored"
    assert sum(len(c) for c in calls) == 1
    assert relate.vector_counts(cfg)[0] == 1


def test_remember_is_quiet_when_ollama_is_down(vault: Path, monkeypatch: pytest.MonkeyPatch):
    path = write_note(vault, "Knowledge/a.md", NOTE.format(title="A", body="本文である。" * 12))
    cfg = configure(vault)
    obsidian.sync_vault(cfg, force=True)

    def refuse(*args, **kwargs):
        raise relate.OllamaUnavailable("down")

    monkeypatch.setattr(relate, "embed", refuse)
    relate._LAST = None

    assert relate.remember(cfg, path, vault=vault) == "deferred"
    assert relate.vector_counts(cfg)[0] == 0
    assert [row["rel_path"] for row in relate.pending(cfg)] == ["Knowledge/a.md"]
