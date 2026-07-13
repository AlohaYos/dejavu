"""The MCP server.

Two things are being protected here.

1. **Protocol conformance.** The server is hand-written rather than built on the official
   SDK, so nothing else checks that `initialize`, `tools/list` and `tools/call` say what
   the spec requires. If these tests are loose, a host will simply refuse to connect and
   the failure will look like "dejavu doesn't work in Cowork".

2. **Parity with the CLI.** The MCP layer must call the same functions the CLI calls. The
   dangerous version of this bug is silent: the secret detector running on one path but
   not the other would leak a credential into the database while every other test stayed
   green. `test_add_refuses_secrets` is the one that would catch it.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from dejavu import mcp
from dejavu import scope as scope_mod
from dejavu.store import add_entry, connect


@pytest.fixture
def initialised(project):
    """A project with a knowledge base, plus its absolute path."""
    scope = scope_mod.project_scope(project)
    con = connect(scope)
    add_entry(
        con,
        title="検索実装のメモ",
        body="search_entries() は3段階検索を行う",
        category="feature",
        keywords=["fts5", "trigram"],
    )
    add_entry(con, title="NEXT: export のテストを書く", body="前回ここまで", category="context")
    con.close()
    return str(project)


def _call(name, **args):
    response = mcp.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": name, "arguments": args}}
    )
    return response["result"]


def _payload(result):
    """The structured payload, or the error dict for a failed tool call."""
    if result.get("isError"):
        return json.loads(result["content"][0]["text"])
    return result["structuredContent"]


# ---- protocol ----


def test_initialize_echoes_the_clients_protocol_version(project):
    res = mcp.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-03-26", "capabilities": {}}}
    )["result"]

    assert res["protocolVersion"] == "2025-03-26"  # do not strand a host one revision behind
    assert res["capabilities"]["tools"] is not None
    assert res["serverInfo"]["name"] == "dejavu"
    assert "resume_knowledge" in res["instructions"]


def test_notifications_are_never_answered(project):
    """A response to a notification corrupts the stream. It must return nothing."""
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_ping(project):
    assert mcp.handle({"jsonrpc": "2.0", "id": 7, "method": "ping"})["result"] == {}


def test_tools_list_is_well_formed(project):
    tools = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]

    names = {t["name"] for t in tools}
    assert names == {
        "search_knowledge", "resume_knowledge", "recent_knowledge",
        "add_knowledge", "update_knowledge", "get_knowledge",
    }
    for tool in tools:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"


def test_unknown_method_is_a_protocol_error(project):
    err = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "nope/nope"})["error"]
    assert err["code"] == -32601


def test_unknown_tool_is_a_protocol_error(project):
    res = mcp.handle(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "bogus", "arguments": {}}}
    )
    assert res["error"]["code"] == -32602


def test_results_carry_both_text_and_structured_content(initialised):
    res = _call("search_knowledge", query="検索", project_path=initialised)
    assert res["content"][0]["type"] == "text"
    assert json.loads(res["content"][0]["text"]) == res["structuredContent"]


def test_tool_failures_are_results_not_transport_errors(project):
    """A missing entry is the model's problem to solve, not a broken connection."""
    res = _call("get_knowledge", uid="ffffffffffff")
    assert res["isError"] is True
    assert "error" in _payload(res)


# ---- tools ----


def test_search_finds_two_character_japanese(initialised):
    """The same load-bearing check as the CLI: trigram cannot match 検索, LIKE must."""
    payload = _payload(_call("search_knowledge", query="検索", project_path=initialised))
    assert any("検索実装" in r["title"] for r in payload["results"])


def test_search_trims_bodies(initialised):
    long_body = "x" * 500
    scope = scope_mod.project_scope(Path(initialised))
    con = connect(scope)
    add_entry(con, title="a long one", body=long_body, category="note", keywords=["zzz"])
    con.close()

    payload = _payload(_call("search_knowledge", query="zzz", project_path=initialised))
    hit = next(r for r in payload["results"] if r["title"] == "a long one")
    assert len(hit["body"]) < 200  # trimmed, so recall does not flood the context


def test_resume_returns_the_body_in_full(initialised):
    payload = _payload(_call("resume_knowledge", project_path=initialised))
    assert payload["title"].startswith("NEXT:")
    assert payload["body"] == "前回ここまで"
    assert payload["age"] == "today"


def test_resume_without_a_note_is_an_error_result(project):
    res = _call("resume_knowledge")
    assert res["isError"] is True


def test_get_returns_the_full_body(initialised):
    found = _payload(_call("search_knowledge", query="検索", project_path=initialised))
    uid = found["results"][0]["uid"]

    payload = _payload(_call("get_knowledge", uid=uid, project_path=initialised))
    assert payload["body"] == "search_entries() は3段階検索を行う"


def test_add_and_update(initialised):
    added = _payload(
        _call(
            "add_knowledge",
            title="UIKit を選んだ理由",
            body="SwiftUI は却下",
            category="decision",
            keywords=["uikit", "swiftui"],
            project_path=initialised,
        )
    )
    assert added["scope"] == "project"

    updated = _payload(
        _call("update_knowledge", uid=added["uid"], append="追記", project_path=initialised)
    )
    assert "SwiftUI は却下" in updated["body"] and "追記" in updated["body"]


def test_add_refuses_secrets(initialised):
    """The guard that must never diverge from the CLI's."""
    res = _call(
        "add_knowledge",
        title="deploy key",
        body="export TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123",
        project_path=initialised,
    )
    assert res["isError"] is True
    assert "credential" in _payload(res)["error"].lower()


def test_add_refuses_near_duplicates(initialised):
    res = _call(
        "add_knowledge", title="検索実装のメモ", body="dup",
        category="feature", project_path=initialised,
    )
    assert res["isError"] is True
    assert "update_knowledge" in _payload(res)["error"]


def test_recent_excludes_research_caches(initialised):
    payload = _payload(_call("recent_knowledge", project_path=initialised))
    categories = {r["category"] for r in payload["results"]}
    assert "context" in categories
    assert "feature" not in categories  # a research cache is not "what I worked on"


# ---- scopes ----


def test_without_a_project_path_only_the_user_scope_is_used(initialised):
    """The project entries must be invisible when no path is given."""
    payload = _payload(_call("search_knowledge", query="検索"))
    assert payload["count"] == 0


def test_add_without_a_project_path_goes_to_the_user_scope(project):
    payload = _payload(_call("add_knowledge", title="いつも squash merge する", body="全PJ共通"))
    assert payload["scope"] == "user"


def test_scope_user_overrides_the_project_path(initialised):
    payload = _payload(
        _call("add_knowledge", title="個人の好み", scope="user", project_path=initialised)
    )
    assert payload["scope"] == "user"


def test_an_uninitialised_project_path_is_an_error(tmp_path, project):
    res = _call("search_knowledge", query="x", project_path=str(tmp_path / "nowhere"))
    assert res["isError"] is True
    assert "dejavu init" in _payload(res)["error"]


# ---- the stdio loop ----


def test_serve_reads_and_writes_newline_delimited_json(project):
    stdin = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
    )
    stdout = io.StringIO()

    assert mcp.serve(stdin, stdout) == 0

    lines = stdout.getvalue().strip().split("\n")
    assert len(lines) == 2  # the notification produced no output
    assert json.loads(lines[0])["id"] == 1
    assert json.loads(lines[1])["result"]["tools"]

    for line in lines:
        assert "\n" not in line  # messages must not contain embedded newlines


def test_malformed_json_does_not_kill_the_server(project):
    stdin = io.StringIO(
        "{not json\n"
        + json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping"}) + "\n"
    )
    stdout = io.StringIO()

    assert mcp.serve(stdin, stdout) == 0

    lines = [json.loads(ln) for ln in stdout.getvalue().strip().split("\n")]
    assert lines[0]["error"]["code"] == -32700  # parse error
    assert lines[1]["id"] == 9  # and it kept going
