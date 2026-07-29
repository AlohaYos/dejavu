"""Per-project external memory: the vault folder a project points at with
`dejavu obsidian project`, and the `--memory` / memory=true write path.

The setting lives in the project's own .dejavu/config.toml (not the user config), so it
travels with the repository. Writing with --memory routes a project-specific note into
the vault on purpose — the one case where "would this be true in another repo?" is
answered by the user, not the model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dejavu import mcp
from dejavu import scope as scope_mod
from dejavu.cli import main


@pytest.fixture
def wired(vault: Path, project: Path) -> tuple[Path, Path]:
    """A registered vault plus a project cwd — both share the isolated DEJAVU_HOME."""
    scope_mod.set_config_value(scope_mod.user_config_path(), "obsidian", "vault", str(vault))
    return vault, project


def _mcp(name, **args):
    resp = mcp.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }
    )
    result = resp["result"]
    if result.get("isError"):
        return json.loads(result["content"][0]["text"])
    return result["structuredContent"]


# ---------------------------------------------------------------- project_memory (config)


def test_project_memory_is_none_when_unset(project: Path):
    assert scope_mod.project_memory() is None


def test_project_memory_reads_the_project_config(project: Path):
    scope_mod.set_config_value(
        scope_mod.project_local_config_path(project), "obsidian", "memory", "dejavu"
    )
    assert scope_mod.project_memory() == "dejavu"


def test_project_memory_keeps_a_nested_path(project: Path):
    scope_mod.set_config_value(
        scope_mod.project_local_config_path(project), "obsidian", "memory", "Job/dejavu"
    )
    assert scope_mod.project_memory() == "Job/dejavu"


def test_project_memory_strips_stray_slashes(project: Path):
    scope_mod.set_config_value(
        scope_mod.project_local_config_path(project), "obsidian", "memory", "/Job/dejavu/"
    )
    assert scope_mod.project_memory() == "Job/dejavu"


def test_project_memory_is_none_outside_a_project(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert scope_mod.project_memory() is None


# ---------------------------------------------------------------- the setup command


def test_project_command_creates_the_folder_and_records_it(wired):
    vault, project = wired

    assert main(["obsidian", "project", "dejavu"]) == 0

    assert (vault / "Knowledge/dejavu").is_dir()
    assert scope_mod.project_memory() == "dejavu"


def test_project_command_records_to_the_local_config_not_the_tracked_one(wired):
    """The value points into this machine's vault, so it must never be committed."""
    vault, project = wired

    main(["obsidian", "project", "dejavu"])

    local = project / scope_mod.DEJAVU_DIR / scope_mod.LOCAL_CONFIG_NAME
    tracked = project / scope_mod.DEJAVU_DIR / scope_mod.CONFIG_NAME
    assert "memory" in local.read_text(encoding="utf-8")
    assert not tracked.exists() or "memory" not in tracked.read_text(encoding="utf-8")


def test_project_command_ignores_the_local_config_in_git(wired):
    vault, project = wired

    main(["obsidian", "project", "dejavu"])

    gitignore = project / scope_mod.DEJAVU_DIR / ".gitignore"
    assert scope_mod.LOCAL_CONFIG_NAME in gitignore.read_text(encoding="utf-8").split()


def test_project_command_does_not_duplicate_the_ignore_line(wired):
    vault, project = wired

    main(["obsidian", "project", "dejavu"])
    main(["obsidian", "project", "Job/dejavu"])

    gitignore = project / scope_mod.DEJAVU_DIR / ".gitignore"
    lines = [ln.strip() for ln in gitignore.read_text(encoding="utf-8").splitlines()]
    assert lines.count(scope_mod.LOCAL_CONFIG_NAME) == 1


def test_project_command_accepts_a_nested_path(wired):
    vault, project = wired

    assert main(["obsidian", "project", "Job/dejavu"]) == 0

    assert (vault / "Knowledge/Job/dejavu").is_dir()
    assert scope_mod.project_memory() == "Job/dejavu"


def test_project_command_is_happy_when_the_folder_already_exists(wired):
    vault, project = wired
    (vault / "Knowledge/dejavu").mkdir()

    assert main(["obsidian", "project", "dejavu"]) == 0
    assert scope_mod.project_memory() == "dejavu"


def test_project_command_rejects_a_folder_that_escapes(wired):
    with pytest.raises(SystemExit):
        main(["obsidian", "project", "../../secrets"])


# ---------------------------------------------------------------- writing with --memory


def test_add_memory_writes_into_the_project_folder(wired):
    vault, project = wired
    main(["obsidian", "project", "dejavu"])

    assert main(["obsidian", "add", "設計メモ", "--memory", "--body", "本文"]) == 0

    notes = list((vault / "Knowledge/dejavu").glob("*.md"))
    assert len(notes) == 1


def test_add_memory_reaches_a_nested_folder(wired):
    vault, project = wired
    main(["obsidian", "project", "Job/dejavu"])

    assert main(["obsidian", "add", "設計メモ", "--memory", "--body", "本文"]) == 0

    assert list((vault / "Knowledge/Job/dejavu").glob("*.md"))


def test_add_memory_errors_when_no_folder_is_configured(wired):
    with pytest.raises(SystemExit):
        main(["obsidian", "add", "設計メモ", "--memory", "--body", "本文"])


def test_add_memory_errors_when_the_folder_was_deleted(wired):
    vault, project = wired
    main(["obsidian", "project", "dejavu"])
    # The setting stays, but the folder is gone.
    (vault / "Knowledge/dejavu").rmdir()

    with pytest.raises(SystemExit):
        main(["obsidian", "add", "設計メモ", "--memory", "--body", "本文"])


def test_category_and_memory_cannot_be_combined(wired):
    main(["obsidian", "project", "dejavu"])
    with pytest.raises(SystemExit):
        main(["obsidian", "add", "x", "--memory", "--category", "API", "--body", "本文"])


# ---------------------------------------------------------------- doctor


def test_doctor_reports_the_memory_folder(wired, capsys):
    main(["obsidian", "project", "dejavu"])
    capsys.readouterr()

    assert main(["obsidian", "doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["project_memory"] == "dejavu"
    assert payload["project_memory_exists"] is True


# ---------------------------------------------------------------- MCP parity


def test_status_reports_project_memory(wired):
    main(["obsidian", "project", "dejavu"])

    payload = _mcp("obsidian_status")

    assert payload["project_memory"] == "dejavu"


def test_status_project_memory_is_none_when_unset(wired):
    payload = _mcp("obsidian_status")
    assert payload["project_memory"] is None


def test_mcp_add_with_memory_writes_into_the_project_folder(wired):
    vault, project = wired
    main(["obsidian", "project", "dejavu"])

    payload = _mcp("add_obsidian_knowledge", title="設計メモ", body="本文", memory=True)

    assert payload["file"] == "Knowledge/dejavu/設計メモ.md"
    assert (vault / payload["file"]).exists()


def test_mcp_add_with_memory_errors_when_unset(wired):
    payload = _mcp("add_obsidian_knowledge", title="設計メモ", body="本文", memory=True)
    assert "external memory" in payload["error"].lower()
