"""The session-end harvest hook.

Two failure modes matter more than the feature working. One: firing every turn, which
turns a helpful prompt into a session that will not end. Two: silently editing a
settings.json the user hand-tuned. Most of what follows is about those.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from dejavu import hooks
from dejavu import scope as scope_mod
from dejavu.cli import install_stop_hook, main


@pytest.fixture
def cfg(tmp_path: Path) -> scope_mod.ObsidianConfig:
    """A configuration where the harvest is expected to fire."""
    return replace(scope_mod.obsidian_config(tmp_path / "absent.toml"), vault=tmp_path / "Vault")


@pytest.fixture
def transcript(tmp_path: Path) -> Path:
    """Long enough to clear harvest_min_lines."""
    path = tmp_path / "transcript.jsonl"
    path.write_text("{}\n" * 100, encoding="utf-8")
    return path


@pytest.fixture
def markers(tmp_path: Path) -> Path:
    return tmp_path / "markers"


def payload(transcript: Path, **overrides) -> dict:
    base = {
        "session_id": "sess-1",
        "transcript_path": str(transcript),
        "stop_hook_active": False,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------- stop_hook


def test_it_fires_on_a_real_session(cfg, transcript, markers):
    code, message = hooks.stop_hook(payload(transcript), cfg, markers)

    assert code == 2  # exit 2 is what hands the message to the assistant
    assert "dejavu obsidian add" in message


def test_it_fires_only_once_per_session(cfg, transcript, markers):
    assert hooks.stop_hook(payload(transcript), cfg, markers)[0] == 2
    assert hooks.stop_hook(payload(transcript), cfg, markers) == (0, "")


def test_a_second_session_still_fires(cfg, transcript, markers):
    assert hooks.stop_hook(payload(transcript), cfg, markers)[0] == 2
    assert hooks.stop_hook(payload(transcript, session_id="sess-2"), cfg, markers)[0] == 2


def test_it_does_not_fire_on_its_own_restart(cfg, transcript, markers):
    """Without this the exit 2 re-triggers the hook, and the session cannot end."""
    assert hooks.stop_hook(payload(transcript, stop_hook_active=True), cfg, markers) == (0, "")


def test_a_short_session_is_skipped(cfg, tmp_path, markers):
    short = tmp_path / "short.jsonl"
    short.write_text("{}\n" * 3, encoding="utf-8")

    assert hooks.stop_hook(payload(short), cfg, markers) == (0, "")


def test_a_missing_transcript_is_skipped(cfg, tmp_path, markers):
    assert hooks.stop_hook(payload(tmp_path / "gone.jsonl"), cfg, markers) == (0, "")


def test_it_stays_quiet_without_a_vault(cfg, transcript, markers):
    """There is nowhere to file anything, so asking would be noise."""
    assert hooks.stop_hook(payload(transcript), replace(cfg, vault=None), markers) == (0, "")


def test_harvest_off_is_respected(cfg, transcript, markers):
    assert hooks.stop_hook(payload(transcript), replace(cfg, harvest="off"), markers) == (0, "")


def test_promote_never_is_respected(cfg, transcript, markers):
    """Someone who refused promotion prompts did not ask for them at session end either."""
    assert hooks.stop_hook(payload(transcript), replace(cfg, promote="never"), markers) == (0, "")


def test_it_stays_quiet_when_the_marker_cannot_be_written(cfg, transcript, tmp_path):
    """Prompting without recording it would repeat the prompt on every single turn."""
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")

    assert hooks.stop_hook(payload(transcript), cfg, blocked) == (0, "")


def test_a_session_id_cannot_escape_the_marker_directory(cfg, transcript, markers):
    hostile = payload(transcript, session_id="../../etc/passwd")

    assert hooks.stop_hook(hostile, cfg, markers)[0] == 2
    assert [p.name for p in markers.iterdir()] == ["______etc_passwd"]


# ---------------------------------------------------------------- installation


@pytest.fixture
def settings(tmp_path: Path) -> Path:
    return tmp_path / "settings.json"


def test_it_registers_the_hook(project, settings):
    install_stop_hook(settings)

    written = json.loads(settings.read_text(encoding="utf-8"))
    entry = written["hooks"]["Stop"][0]["hooks"][0]
    assert entry["command"].endswith("hook stop")
    assert "timeout" in entry


def test_other_hooks_keep_running(project, settings):
    existing = {
        "hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "say hi"}]}]},
        "theme": "dark",
    }
    settings.write_text(json.dumps(existing), encoding="utf-8")

    install_stop_hook(settings)

    written = json.loads(settings.read_text(encoding="utf-8"))
    assert written["theme"] == "dark"
    commands = [h["command"] for m in written["hooks"]["Stop"] for h in m["hooks"]]
    assert commands[0] == "say hi"  # still first, still there
    assert len(commands) == 2


def test_installing_twice_does_not_duplicate_it(project, settings):
    install_stop_hook(settings)
    install_stop_hook(settings)

    written = json.loads(settings.read_text(encoding="utf-8"))
    commands = [h["command"] for m in written["hooks"]["Stop"] for h in m["hooks"]]
    assert len(commands) == 1


def test_it_backs_up_before_editing(project, settings, tmp_path):
    settings.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")

    install_stop_hook(settings)

    backups = list(tmp_path.glob("settings.json.bak.*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == {"theme": "dark"}


def test_it_refuses_to_clobber_settings_it_cannot_parse(project, settings, capsys):
    settings.write_text("{ not json", encoding="utf-8")

    with pytest.raises(SystemExit):
        install_stop_hook(settings)

    assert settings.read_text(encoding="utf-8") == "{ not json"
    assert "not valid JSON" in capsys.readouterr().err


# ---------------------------------------------------------------- the CLI entry point


def test_the_cli_exits_zero_on_an_unreadable_payload(project, monkeypatch, capsys):
    """A malformed payload must not wedge the session."""
    monkeypatch.setattr("sys.stdin", _Stdin("not json"))

    assert main(["hook", "stop"]) == 0


def test_the_cli_reports_the_harvest_on_stderr(project, transcript, monkeypatch, capsys):
    monkeypatch.setattr("dejavu.hooks.stop_hook", lambda *_args, **_kw: (2, hooks.HARVEST_MESSAGE))
    monkeypatch.setattr("sys.stdin", _Stdin(json.dumps(payload(transcript))))

    assert main(["hook", "stop"]) == 2
    assert "[dejavu] Session harvest." in capsys.readouterr().err


class _Stdin:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text
