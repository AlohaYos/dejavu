"""Every git worktree must share the main worktree's database.

The trap: `.dejavu/*.md` is tracked by git, so `.dejavu/` gets checked out into
each linked worktree too. Naively walking up for a `.dejavu/` directory therefore
lands on the worktree's own copy and creates a second, empty database — quietly breaking
the promise that any worktree can recall the same knowledge.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dejavu import scope as scope_mod
from dejavu.store import add_entry, connect, list_entries

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="requires git")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(cwd),
        },
    )


def test_worktree_shares_the_main_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEJAVU_HOME", str(tmp_path / "userhome"))

    main = tmp_path / "repo"
    kdir = main / scope_mod.DEJAVU_DIR
    kdir.mkdir(parents=True)

    _git(main, "init", "-q")
    # Reproduce exactly what `dejavu init` leaves behind: .md tracked, .db ignored.
    (kdir / "dejavu-triggers.md").write_text("# triggers\n", encoding="utf-8")
    (main / ".gitignore").write_text(".dejavu/knowledge.db*\n", encoding="utf-8")
    _git(main, "add", "-A")
    _git(main, "commit", "-qm", "init")

    main_scope = scope_mod.project_scope(main)
    assert main_scope is not None
    con = connect(main_scope)
    add_entry(con, title="検索実装のメモ", body="b", category="feature")
    con.close()

    wt = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", str(wt), "-b", "feature")
    assert (wt / scope_mod.DEJAVU_DIR).is_dir(), "precondition: .dejavu appears in worktrees"
    assert not (wt / scope_mod.DEJAVU_DIR / scope_mod.DB_NAME).exists()

    wt_scope = scope_mod.project_scope(wt)
    assert wt_scope is not None
    assert wt_scope.db_path == main_scope.db_path

    con = connect(wt_scope)
    titles = [e.title for e in list_entries(con, "project")]
    con.close()
    assert "検索実装のメモ" in titles, "the worktree cannot see the main knowledge base"


def test_plain_repository_uses_its_own_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEJAVU_HOME", str(tmp_path / "userhome"))
    repo = tmp_path / "repo"
    (repo / scope_mod.DEJAVU_DIR).mkdir(parents=True)
    _git(repo, "init", "-q")

    sc = scope_mod.project_scope(repo)
    assert sc is not None
    assert sc.db_path == repo / scope_mod.DEJAVU_DIR / scope_mod.DB_NAME
