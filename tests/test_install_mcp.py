"""`dejavu install-mcp`.

The failure this is really guarding against is a slow one: a config that works today and
breaks silently on the next `brew upgrade`, months later, for no reason the user could
connect to anything they did.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dejavu.cli import _mcp_binary, main


@pytest.fixture
def config(tmp_path: Path) -> Path:
    return tmp_path / "claude_desktop_config.json"


def test_writes_a_registration(project, config, capsys):
    assert main(["install-mcp", "--config", str(config)]) == 0

    written = json.loads(config.read_text(encoding="utf-8"))
    server = written["mcpServers"]["dejavu"]
    assert server["args"] == ["mcp"]
    assert Path(server["command"]).is_absolute()  # the host has no PATH of yours


def test_the_command_path_survives_a_brew_upgrade(project, config, monkeypatch, tmp_path):
    """Homebrew's bin/dejavu is a symlink into a version-stamped Cellar directory.

    Resolving it would pin the config to `.../Cellar/dejavu/0.3.0/bin/dejavu`, which
    ceases to exist the moment the user upgrades. The stable symlink must be written.
    """
    stable = tmp_path / "bin" / "dejavu"
    cellar = tmp_path / "Cellar" / "dejavu" / "0.3.0" / "bin" / "dejavu"
    cellar.parent.mkdir(parents=True)
    cellar.write_text("#!/bin/sh\n")
    stable.parent.mkdir(parents=True)
    stable.symlink_to(cellar)

    monkeypatch.setattr("sys.argv", [str(stable)])
    monkeypatch.setenv("PATH", str(stable.parent))

    assert _mcp_binary() == stable  # not the Cellar path it points at


def test_existing_registrations_are_preserved(project, config):
    config.write_text(
        json.dumps({"mcpServers": {"other": {"command": "/bin/true"}}, "theme": "dark"}),
        encoding="utf-8",
    )

    assert main(["install-mcp", "--config", str(config)]) == 0

    written = json.loads(config.read_text(encoding="utf-8"))
    assert written["theme"] == "dark"  # untouched
    assert set(written["mcpServers"]) == {"other", "dejavu"}


def test_it_refuses_to_overwrite_without_force(project, config, capsys):
    assert main(["install-mcp", "--config", str(config)]) == 0
    assert main(["install-mcp", "--config", str(config)]) == 1
    assert "already registered" in capsys.readouterr().err

    assert main(["install-mcp", "--config", str(config), "--force"]) == 0


def test_it_refuses_to_clobber_a_config_it_cannot_parse(project, config, capsys):
    """Overwriting a config we failed to read would destroy the user's other servers."""
    config.write_text("{ this is not json", encoding="utf-8")

    with pytest.raises(SystemExit):
        main(["install-mcp", "--config", str(config)])

    assert config.read_text(encoding="utf-8") == "{ this is not json"  # left alone
    assert "not valid JSON" in capsys.readouterr().err
