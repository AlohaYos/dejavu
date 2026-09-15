"""Linking by meaning.

Ollama is never actually contacted. `relate.embed` is replaced by a fake that returns
vectors chosen by hand, which makes similarity a thing the test decides rather than a
thing the test hopes for.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
from array import array
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
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


def test_a_reply_that_never_comes_is_a_slow_model_not_a_dead_one(
    monkeypatch: pytest.MonkeyPatch,
):
    def hang(url, payload, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(relate, "_post", hang)
    with pytest.raises(relate.OllamaUnavailable) as caught:
        relate.embed(["x"], model="m", host="h", timeout=1)
    assert caught.value.slow


def test_a_refused_connection_is_not_called_slow(monkeypatch: pytest.MonkeyPatch):
    def refuse(url, payload, timeout):
        raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))

    monkeypatch.setattr(relate, "_post", refuse)
    with pytest.raises(relate.OllamaUnavailable) as caught:
        relate.embed(["x"], model="m", host="h", timeout=1)
    assert not caught.value.slow


def test_doctor_says_running_when_only_the_model_is_slow(
    vault: Path, monkeypatch: pytest.MonkeyPatch
):
    def slow(*args, **kwargs):
        raise relate.OllamaUnavailable(relate.SLOW_REASON, slow=True)

    monkeypatch.setattr(relate, "embed", slow)
    ok, why = relate.reachable(configure(vault))
    assert not ok
    assert why.startswith("running at")


# ---------------------------------------------------------------- waiting for the port


@pytest.fixture
def tags_server():
    """A local server whose answer to /api/tags the test chooses, per method."""
    replies: dict[str, int] = {}

    class Handler(BaseHTTPRequestHandler):
        def _answer(self):
            self.send_response(replies.get(self.command, 405))
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        do_GET = do_POST = _answer

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", replies
    server.shutdown()
    server.server_close()


def _wait(host: str, monkeypatch: pytest.MonkeyPatch, *, port_timeout: float = 5.0):
    warmed: list = []
    monkeypatch.setattr(relate, "embed", lambda texts, **kw: warmed.append(texts))
    cfg = replace(scope_mod.obsidian_config(), relate_host=host)
    started = time.monotonic()
    relate.wait_until_ready(cfg, port_timeout=port_timeout)
    return warmed, time.monotonic() - started


@pytest.mark.parametrize(
    "replies",
    [
        {"POST": 405},  # Ollama 0.34: POST refused. GET is what we send, but either way
        {"GET": 200},  # the port answered, so the warm-up must run
        {"GET": 500},
    ],
)
def test_any_http_answer_means_the_port_is_open(
    tags_server, replies, monkeypatch: pytest.MonkeyPatch
):
    host, table = tags_server
    table.update(replies)

    warmed, elapsed = _wait(host, monkeypatch)

    assert warmed == [["warm"]]
    assert elapsed < 1.0


def test_the_port_check_is_a_get(tags_server, monkeypatch: pytest.MonkeyPatch):
    host, table = tags_server
    table.update({"GET": 200, "POST": 405})
    seen: list[str] = []
    real = relate.urllib.request.urlopen

    def spy(request, timeout):
        seen.append(request if isinstance(request, str) else request.get_method())
        return real(request, timeout=timeout)

    monkeypatch.setattr(relate.urllib.request, "urlopen", spy)
    _wait(host, monkeypatch)

    assert seen == [host + "/api/tags"]  # a bare URL is a GET


def test_a_closed_port_still_gives_up(monkeypatch: pytest.MonkeyPatch):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]  # closed again once the block ends

    with pytest.raises(relate.OllamaUnavailable, match="did not start in time"):
        _wait(f"http://127.0.0.1:{port}", monkeypatch, port_timeout=0.6)


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
    assert relate.pending(cfg)[0]["reason"] == "ollama-down"


def test_a_slow_model_is_queued_as_slow(vault: Path, monkeypatch: pytest.MonkeyPatch):
    path = write_note(vault, "Knowledge/a.md", NOTE.format(title="A", body="本文である。" * 12))
    cfg = configure(vault)
    obsidian.sync_vault(cfg, force=True)

    def slow(*args, **kwargs):
        raise relate.OllamaUnavailable(relate.SLOW_REASON, slow=True)

    monkeypatch.setattr(relate, "embed", slow)
    relate._LAST = None

    assert relate.remember(cfg, path, vault=vault) == "deferred"
    assert relate.pending(cfg)[0]["reason"] == "ollama-slow"

    # The next write trusts the remembered outage without calling Ollama — and still
    # knows it was a slow model rather than a dead one.
    with pytest.raises(relate.OllamaUnavailable) as caught:
        relate._embed_one(cfg, "別の本文")
    assert caught.value.slow
