"""Starting the model, remembering that it is down, and catching up afterwards.

Nothing here launches anything. `subprocess.run` is replaced, and what the code *tried*
to run is the thing under test — which is the only part dejavu is responsible for.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import write_note

from dejavu import obsidian, progress, relate
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


@pytest.fixture
def indexed(vault: Path) -> Path:
    write_note(vault, "Knowledge/a.md", NOTE.format(title="A", body="本文である。" * 12))
    obsidian.sync_vault(configure(vault), force=True)
    return vault


# ---------------------------------------------------------------- finding it


def test_the_app_is_preferred_over_homebrew(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    (tmp_path / "Applications" / "Ollama.app").mkdir(parents=True)
    monkeypatch.setattr(relate.shutil, "which", lambda name: "/opt/homebrew/bin/" + name)

    install = relate.detect_install(home=tmp_path)

    assert install.method == "app"
    assert install.command == ["open", "-ga", "Ollama"]
    # The app is not a launch agent, so it makes no promise about future logins.
    assert install.permanent is False


def test_homebrew_is_the_fallback_and_is_marked_permanent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setattr(relate, "APP_PATH", tmp_path / "nowhere.app")
    monkeypatch.setattr(relate.shutil, "which", lambda name: "/opt/homebrew/bin/" + name)

    install = relate.detect_install(home=tmp_path)

    assert install.command == ["brew", "services", "start", "ollama"]
    assert install.permanent is True  # it writes a launch agent; the user must be told


def test_nothing_installed_means_nothing_is_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(relate, "APP_PATH", tmp_path / "nowhere.app")
    monkeypatch.setattr(relate.shutil, "which", lambda name: None)

    install = relate.detect_install(home=tmp_path)

    assert install.found is False
    assert install.command == []


def test_start_refuses_rather_than_guessing_when_nothing_is_installed(
    indexed: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setattr(relate, "APP_PATH", tmp_path / "nowhere.app")
    monkeypatch.setattr(relate.shutil, "which", lambda name: None)
    ran = []
    monkeypatch.setattr(relate.subprocess, "run", lambda *a, **k: ran.append(a))

    with pytest.raises(relate.OllamaUnavailable):
        relate.start(configure(indexed))
    assert ran == []


def test_start_runs_the_command_and_then_waits(
    indexed: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    (tmp_path / "Applications" / "Ollama.app").mkdir(parents=True)
    monkeypatch.setattr(relate, "APP_PATH", tmp_path / "Applications" / "Ollama.app")
    ran: list = []
    monkeypatch.setattr(relate.subprocess, "run", lambda cmd, **k: ran.append(cmd))
    waited: list = []
    monkeypatch.setattr(relate, "wait_until_ready", lambda cfg, progress=None: waited.append(1))

    install = relate.start(configure(indexed))

    assert ran == [["open", "-ga", "Ollama"]]
    assert waited == [1]  # starting without warming up just moves the timeout later
    assert install.method == "app"


# ---------------------------------------------------------------- remembering the outage


def test_a_known_outage_costs_no_connection_attempt(indexed: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = configure(indexed)
    relate.mark_down(cfg, "Connection refused")

    tried = []
    monkeypatch.setattr(relate, "embed", lambda *a, **k: tried.append(1))
    relate._LAST = None

    with pytest.raises(relate.OllamaUnavailable):
        relate._embed_one(cfg, "何か長めの本文。" * 5)
    assert tried == []  # the answer was already known


def test_the_memory_expires(indexed: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = configure(indexed)
    relate.mark_down(cfg, "Connection refused")
    assert relate.known_down(cfg)

    con = relate._open_state()
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    relate._set(con, "unreachable_until", past.isoformat())
    con.commit()
    con.close()

    assert relate.known_down(cfg) is None


def test_asking_for_a_start_forgets_the_outage_immediately(indexed: Path):
    """Otherwise the user says yes and then watches nothing happen for a minute."""
    cfg = configure(indexed)
    relate.mark_down(cfg, "Connection refused")

    relate.clear_down(cfg)

    assert relate.known_down(cfg) is None


def test_a_refusal_is_remembered(indexed: Path):
    cfg = configure(indexed)
    assert relate.consent(cfg) == "ask"

    relate.remember_refusal(cfg)

    assert relate.consent(cfg) == "never"


def test_always_skips_the_question(indexed: Path):
    assert relate.consent(configure(indexed, relate_autostart="always")) == "always"


# ---------------------------------------------------------------- keep_alive


def test_keep_alive_rides_along_in_the_request(monkeypatch: pytest.MonkeyPatch):
    """Not exported as an environment variable — see the docstring on `embed`."""
    sent = {}

    def capture(url, payload, timeout):
        sent.update(payload)
        return {"embeddings": [[1.0, 0.0]]}

    monkeypatch.setattr(relate, "_post", capture)
    relate.embed(["x"], model="bge-m3", host="http://h", timeout=1, keep_alive="24h")

    assert sent["keep_alive"] == "24h"


def test_no_keep_alive_means_no_such_field(monkeypatch: pytest.MonkeyPatch):
    sent = {}
    monkeypatch.setattr(
        relate, "_post", lambda u, p, t: (sent.update(p), {"embeddings": [[1.0, 0.0]]})[1]
    )
    relate.embed(["x"], model="m", host="http://h", timeout=1)

    assert "keep_alive" not in sent


# ---------------------------------------------------------------- progress output


def write_to(buffer, *, tty: bool, clock):
    return progress.Progress(buffer, clock=clock, isatty=tty)


class Buffer:
    def __init__(self) -> None:
        self.text = ""

    def write(self, chunk: str) -> None:
        self.text += chunk

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:  # pragma: no cover - explicit isatty is always passed
        return False


def test_a_wait_nobody_noticed_prints_nothing():
    now = [0.0]
    buffer = Buffer()
    bar = write_to(buffer, tty=True, clock=lambda: now[0])

    bar.step("Getting ready")
    now[0] = 0.2
    bar.tick()
    bar.done()

    assert buffer.text == ""


def test_a_long_wait_shows_the_seconds_ticking():
    now = [0.0]
    buffer = Buffer()
    bar = write_to(buffer, tty=True, clock=lambda: now[0])

    bar.step("Getting ready to link your notes")
    now[0] = 3.0
    bar.tick()

    assert "Getting ready to link your notes" in buffer.text
    assert "3s" in buffer.text  # a number that moves is the difference from a hang


def test_a_pipe_never_receives_a_carriage_return():
    """`\\r` down a pipe is not progress, it is corruption."""
    now = [0.0]
    buffer = Buffer()
    bar = write_to(buffer, tty=False, clock=lambda: now[0])

    now[0] = 3.0
    bar.step("Getting ready")
    bar.tick()
    bar.done()

    assert "\r" not in buffer.text
    assert buffer.text == "Getting ready\n"
