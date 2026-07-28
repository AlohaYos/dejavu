"""The vault tools over MCP.

These matter more than the CLI equivalents. Claude Desktop chat and Cowork have no
filesystem access at all, so this server is the *only* way they can reach the vault —
if a tool here is wrong, the feature simply does not exist on those surfaces.

Parity is the other concern: the secret detector and the human-note guard must fire here
exactly as they do in the CLI, or one path becomes a hole the other's tests cannot see.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import write_note

from dejavu import mcp, obsidian
from dejavu import scope as scope_mod


def _call(name, **args):
    response = mcp.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }
    )
    return response["result"]


def _payload(result):
    if result.get("isError"):
        return json.loads(result["content"][0]["text"])
    return result["structuredContent"]


@pytest.fixture
def connected(vault: Path) -> Path:
    scope_mod.set_config_value(scope_mod.user_config_path(), "obsidian", "vault", str(vault))
    obsidian.sync_vault(scope_mod.obsidian_config(), force=True)
    return vault


# ---------------------------------------------------------------- status


def test_status_says_when_no_vault_is_set_up(vault: Path):
    payload = _payload(_call("obsidian_status"))

    assert payload["configured"] is False
    assert "dejavu obsidian init" in payload["hint"]


def test_status_reports_the_write_mode_and_policies(connected: Path):
    payload = _payload(_call("obsidian_status"))

    assert payload["configured"] is True
    assert payload["vault"] == str(connected)
    assert payload["write_mode"] == "full"  # the fixture vault is a plain local folder
    assert payload["research"] == "findings"
    assert set(payload["by_folder"]) == {"Knowledge", "UserInfo", "Research"}


# ---------------------------------------------------------------- writing


def test_knowledge_lands_in_the_vault_and_is_immediately_searchable(connected: Path):
    payload = _payload(
        _call(
            "add_obsidian_knowledge",
            title="ignoresSafeArea の落とし穴",
            body="safeAreaInsets.bottom が 0 になる。",
            tags=["swiftui", "layout"],
        )
    )

    assert payload["action"] == "created"
    assert payload["file"] == "Knowledge/ignoresSafeArea の落とし穴.md"
    assert (connected / payload["file"]).exists()

    hits = _payload(_call("search_knowledge", query="認識できない語 safeAreaInsets"))["results"]
    assert any(h["source"] == "obsidian" for h in hits)


def test_a_second_call_with_the_same_title_appends_instead_of_duplicating(connected: Path):
    _call("add_obsidian_knowledge", title="同じ題", body="一つ目")
    payload = _payload(_call("add_obsidian_knowledge", title="同じ題", body="二つ目"))

    assert payload["action"] == "appended"
    text = (connected / payload["file"]).read_text(encoding="utf-8")
    assert "一つ目" in text and "二つ目" in text
    assert len(list((connected / "Knowledge").glob("*.md"))) == 1


def test_a_note_the_user_wrote_is_never_touched(connected: Path):
    original = "---\ntags: [hawaii]\n---\n\n# 手書きのメモ\n\n人間が書いた。\n"
    write_note(connected, "Knowledge/手書きのメモ.md", original)

    payload = _payload(_call("add_obsidian_knowledge", title="手書きのメモ", body="勝手に足す"))

    assert "not written by dejavu" in payload["error"]
    assert (connected / "Knowledge/手書きのメモ.md").read_text(encoding="utf-8") == original


def test_secrets_are_refused_exactly_as_in_the_cli(connected: Path):
    payload = _payload(
        _call(
            "add_obsidian_knowledge",
            title="deploy key",
            body="export TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123",
        )
    )

    assert "secret" in payload["error"].lower()
    assert not list((connected / "Knowledge").glob("*.md"))


def test_research_is_filed_by_project_and_date(connected: Path, project: Path):
    payload = _payload(
        _call(
            "add_research",
            title="AFM セッション劣化の計測",
            body="session 使い回しで推論時間が単調増加する。",
            project_path=str(project),
        )
    )

    assert payload["project"] == project.name
    assert payload["file"].startswith(f"Research/{project.name}/")
    assert payload["file"].endswith("-AFM セッション劣化の計測.md")
    assert (connected / payload["file"]).exists()


def test_research_needs_to_know_which_project(connected: Path):
    payload = _payload(_call("add_research", title="どこにも属さない調査", body="x"))

    assert "project" in payload["error"]


def test_vault_tools_explain_themselves_when_no_vault_exists(vault: Path):
    payload = _payload(_call("add_obsidian_knowledge", title="どこにも保存できない", body="x"))

    assert "dejavu obsidian init" in payload["error"]


# ---------------------------------------------------------------- conflicts


def test_a_project_hit_and_a_vault_hit_are_flagged_as_a_possible_conflict(
    connected: Path, project: Path
):
    from dejavu.store import add_entry, connect

    scope = scope_mod.project_scope(project)
    assert scope is not None
    con = connect(scope)
    add_entry(
        con,
        title="認証まわりの設計判断",
        body="このリポジトリでは Cookie を使う",
        category="decision",
        keywords=["auth"],
    )
    con.close()
    _call("add_obsidian_knowledge", title="認証の共通方針", body="全プロジェクトで JWT を使う")

    payload = _payload(_call("search_knowledge", query="認証", project_path=str(project)))

    sources = {c["source"] for c in payload["conflict_candidates"]}
    assert sources == {"project", "obsidian"}
    assert "ask" in payload["conflict_instruction"]


def test_no_conflict_is_reported_when_only_one_side_answers(connected: Path, project: Path):
    _call("add_obsidian_knowledge", title="独自の話題", body="vault にしかない知識")

    payload = _payload(_call("search_knowledge", query="独自", project_path=str(project)))

    assert payload["results"]
    assert "conflict_candidates" not in payload


# ---------------------------------------------------------------- automatic linking


def test_the_start_tool_is_hidden_when_linking_is_off(connected):
    """A tool that can do nothing still costs context on every turn."""
    names = {tool["name"] for tool in mcp.visible_tools()}
    assert "enable_autolink" not in names


def test_the_start_tool_appears_once_linking_is_on(connected, monkeypatch):
    embedding = replace(scope_mod.obsidian_config(), relate="embed")
    monkeypatch.setattr(scope_mod, "obsidian_config", lambda *a, **k: embedding)

    names = {tool["name"] for tool in mcp.visible_tools()}

    assert "enable_autolink" in names


def test_starting_without_the_user_agreeing_is_refused(connected, monkeypatch):
    """The confirmation belongs to the user, not to the model."""
    embedding = replace(scope_mod.obsidian_config(), relate="embed")
    monkeypatch.setattr(scope_mod, "obsidian_config", lambda *a, **k: embedding)

    with pytest.raises(ValueError, match="Ask the user first"):
        mcp.call_tool("enable_autolink", {"confirmed": False})
