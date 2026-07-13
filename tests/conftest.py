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
