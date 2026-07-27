from __future__ import annotations

import os
from pathlib import Path

import pytest

from dejavu import scope as scope_mod
from dejavu.store import connect


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A temporary project holding a .dejavu/ dir, with the user scope isolated too."""
    root = tmp_path / "proj"
    (root / scope_mod.DEJAVU_DIR).mkdir(parents=True)
    monkeypatch.setenv("DEJAVU_HOME", str(tmp_path / "userhome"))
    monkeypatch.chdir(root)
    yield root
    os.environ.pop("DEJAVU_HOME", None)


@pytest.fixture
def con(project: Path):
    scope = scope_mod.project_scope(project)
    assert scope is not None
    connection = connect(scope)
    yield connection
    connection.close()


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An Obsidian vault in a local folder, with the user scope isolated.

    Deliberately not under a synced path, so writes default to `full` and a test that
    wants append-only has to say so.
    """
    root = tmp_path / "Documents" / "Vault"
    for folder in ("Knowledge", "UserInfo", "Research"):
        (root / folder).mkdir(parents=True)
    (root / ".obsidian").mkdir()
    monkeypatch.setenv("DEJAVU_HOME", str(tmp_path / "userhome"))
    return root


def write_note(vault_root: Path, relative: str, text: str) -> Path:
    path = vault_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
