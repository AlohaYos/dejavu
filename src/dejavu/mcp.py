"""MCP server — a thin shell over the same functions the CLI calls.

Why this exists
---------------
The CLI reaches any agent that can run shell commands in the same filesystem as the
database: terminal Claude Code, and Xcode's built-in Claude Agent. It cannot reach
Claude Desktop or Cowork, whose shells run in an isolated sandbox with no access to
`~/.config/dejavu/` or a project's `.dejavu/`. Those hosts *do* launch MCP servers as
local subprocesses on the real machine — which is the one door left open.

Reaching those hosts is the entire justification for this file. It is not "the agent
will use dejavu more"; the instructions already achieve that where the CLI is reachable.

Why it is hand-written
----------------------
MCP's stdio transport is newline-delimited JSON-RPC 2.0, and a tools-only server needs
exactly five methods. Depending on the official SDK would pull in pydantic and friends,
and dejavu's zero-dependency property is load-bearing: it is why the Homebrew formula
needs no `resource` blocks at all.

The rule that matters
---------------------
**Never reimplement search, storage, or the safety checks here.** Call the same functions
`cli.py` calls. If the two paths diverged, the secret detector could run in one and not
the other — a credential leak that no test would catch, because each path would pass its
own tests.

Scope resolution
----------------
Unlike a shell, an MCP host has no meaningful working directory: the server is launched
by the desktop app, from wherever it happens to be. A project therefore cannot be
inferred, only stated. Every tool takes an optional `project_path`; without one, only the
user scope is touched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import __version__, preflight, safety
from . import scope as scope_mod
from .scope import CATEGORIES, STATUSES, Scope
from .search import search as run_search
from .store import (
    add_entry,
    connect,
    get_entry,
    latest_context,
    list_entries,
    normalize_keywords,
    recent_entries,
    update_entry,
)

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "dejavu"

# Trim bodies in list-shaped results, exactly as the CLI does. An MCP host will feed this
# straight into the model's context, so the same guard applies: a knowledge base that
# floods the context defeats its own purpose.
SNIPPET_LEN = 150

_PROJECT_PATH_SCHEMA = {
    "type": "string",
    "description": (
        "Absolute path to a project that has been initialised with `dejavu init` "
        "(it contains a .dejavu directory). Omit to use only the user scope."
    ),
}


# ---------------------------------------------------------------- scopes


def _scopes_for(project_path: str | None) -> list[Scope]:
    """Scopes to read. The user scope is always included; project only when given."""
    scopes: list[Scope] = []
    if project_path:
        proj = scope_mod.project_scope(Path(project_path).expanduser())
        if proj is None:
            raise ValueError(
                f"No .dejavu directory found at or above {project_path!r}. "
                f"Run `dejavu init` there first."
            )
        scopes.append(proj)
    scopes.append(scope_mod.user_scope())
    return scopes


def _write_scope(project_path: str | None, scope: str | None) -> Scope:
    """Scope to write to. Explicit `scope` wins; otherwise project when known, else user."""
    if scope == "user" or not project_path:
        return scope_mod.user_scope()
    return _scopes_for(project_path)[0]


def _snippet(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= SNIPPET_LEN else flat[:SNIPPET_LEN] + "…"


def _entry_json(entry, scope: Scope, *, full: bool) -> dict:
    return {
        "uid": entry.uid,
        "title": entry.title,
        "body": entry.body if full else _snippet(entry.body),
        "category": entry.category,
        "status": entry.status,
        "keywords": entry.keywords,
        # The Scope we opened, not `entry.scope`. store.add_entry re-reads the row through
        # get_entry, whose scope_name defaults to "project" — so a fresh Entry always
        # claims to be a project entry, even when it was written to the user scope.
        # Reporting the wrong scope back to the model would be worse than useless.
        "scope": scope.name,
        "updated_at": entry.updated_at,
        "age": entry.age_phrase,
        "stale_days": entry.stale_days(scope.stale_days),
    }


# ---------------------------------------------------------------- tools

TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_knowledge",
        "title": "Search the knowledge base",
        "description": (
            "Search stored knowledge before investigating unfamiliar code. Results whose "
            "`stale_days` is not null were last verified a long time ago: check them "
            "against the current code before relying on them. Bodies are trimmed; call "
            "get_knowledge for the full text."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Words to search for."},
                "category": {"type": "string", "enum": list(CATEGORIES)},
                "limit": {"type": "integer", "default": 10},
                "project_path": _PROJECT_PATH_SCHEMA,
            },
            "required": ["query"],
        },
    },
    {
        "name": "resume_knowledge",
        "title": "Read the latest handoff note",
        "description": (
            "Return the most recent `context` entry in full — the note left at the end of "
            "the last session. Use this when the user wants to continue from where they "
            "left off. Do NOT search for it: this lookup is deterministic and a search is "
            "not."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"project_path": _PROJECT_PATH_SCHEMA},
        },
    },
    {
        "name": "recent_knowledge",
        "title": "Recent activity",
        "description": (
            "Recent context, plan and decision entries, newest first. Use for 'what have I "
            "been working on', status updates and standup notes. Research caches are "
            "excluded unless a category is given."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "since": {
                    "type": "string",
                    "description": "today | 2d | 2026-07-01",
                    "default": "2d",
                },
                "category": {"type": "string", "enum": list(CATEGORIES)},
                "limit": {"type": "integer", "default": 50},
                "project_path": _PROJECT_PATH_SCHEMA,
            },
        },
    },
    {
        "name": "add_knowledge",
        "title": "Store knowledge",
        "description": (
            "Store something worth recalling later. Write densely: the reasoning behind a "
            "decision, the options rejected, the paths and function names that are "
            "expensive to rediscover — not a narrative. Hand-pick 5-10 keywords. Never "
            "store credentials; the server will refuse them. If a near-duplicate exists, "
            "the call is rejected and you should call update_knowledge instead."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "One-line summary."},
                "body": {"type": "string"},
                "category": {"type": "string", "enum": list(CATEGORIES), "default": "note"},
                "keywords": {"type": "array", "items": {"type": "string"}},
                "status": {"type": "string", "enum": list(STATUSES)},
                "scope": {
                    "type": "string",
                    "enum": ["project", "user"],
                    "description": (
                        "Use 'user' for knowledge about the person rather than the "
                        "repository — preferences, working style, cross-project context. "
                        "Defaults to project when project_path is given, else user."
                    ),
                },
                "project_path": _PROJECT_PATH_SCHEMA,
            },
            "required": ["title"],
        },
    },
    {
        "name": "update_knowledge",
        "title": "Update an entry",
        "description": (
            "Update an existing entry by UID. Use `append` to extend an entry rather than "
            "creating a near-duplicate. Updating also marks the entry as freshly verified."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "uid": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string", "description": "Replaces the body."},
                "append": {"type": "string", "description": "Appended to the body."},
                "keywords": {"type": "array", "items": {"type": "string"}},
                "status": {"type": "string", "enum": list(STATUSES)},
                "project_path": _PROJECT_PATH_SCHEMA,
            },
            "required": ["uid"],
        },
    },
    {
        "name": "get_knowledge",
        "title": "Read one entry in full",
        "description": "Return a single entry by UID, with its body untrimmed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "uid": {"type": "string"},
                "project_path": _PROJECT_PATH_SCHEMA,
            },
            "required": ["uid"],
        },
    },
]


def _find(uid: str, scopes: list[Scope]):
    for scope in scopes:
        if not scope.db_path.exists():
            continue
        con = connect(scope)
        try:
            entry = get_entry(con, uid, scope.name)
            if entry:
                return entry, scope
        finally:
            con.close()
    return None, None


def call_tool(name: str, args: dict[str, Any]) -> dict:
    """Run a tool. Returns the structured payload; raises ValueError for tool-level errors."""
    project_path = args.get("project_path")

    if name == "search_knowledge":
        scopes = _scopes_for(project_path)
        hits = run_search(
            scopes,
            args["query"],
            category=args.get("category"),
            limit=int(args.get("limit", 10)),
        )
        return {
            "results": [_entry_json(hit.entry, sc, full=False) for hit, sc in hits],
            "count": len(hits),
        }

    if name == "resume_knowledge":
        best = None
        for scope in _scopes_for(project_path):
            if not scope.db_path.exists():
                continue
            con = connect(scope)
            try:
                entry = latest_context(con, scope.name)
            finally:
                con.close()
            if entry and (best is None or entry.updated_at > best[0].updated_at):
                best = (entry, scope)
        if best is None:
            raise ValueError(
                "No handoff note found. Ask the user to save one at the end of a session."
            )
        entry, scope = best
        return _entry_json(entry, scope, full=True)

    if name == "recent_knowledge":
        from .cli import _parse_since  # the CLI owns the date parsing; do not duplicate it

        since = _parse_since(args.get("since") or "2d")
        collected = []
        for scope in _scopes_for(project_path):
            if not scope.db_path.exists():
                continue
            con = connect(scope)
            try:
                for entry in recent_entries(
                    con,
                    scope.name,
                    since=since,
                    category=args.get("category"),
                    limit=int(args.get("limit", 50)),
                ):
                    collected.append(_entry_json(entry, scope, full=False))
            finally:
                con.close()
        collected.sort(key=lambda e: e["updated_at"], reverse=True)
        return {"results": collected, "count": len(collected)}

    if name == "add_knowledge":
        title = args["title"]
        body = args.get("body", "")

        # The same guard the CLI applies. Reimplementing it here would be the mistake this
        # module's docstring warns about, so we call straight into safety.py.
        found = safety.find_secrets(f"{title}\n{body}")
        if found:
            raise ValueError(
                "Refused: this looks like it contains a credential ("
                + ", ".join(found)
                + "). Never store secrets in the knowledge base."
            )

        scope = _write_scope(project_path, args.get("scope"))
        con = connect(scope)
        try:
            # list_entries, not recent_entries: the latter filters to the "activity"
            # categories, which would hide near-duplicate `feature` and `note` entries
            # from the duplicate check.
            candidates = [
                (e.uid, e.title)
                for e in list_entries(con, scope.name, category=args.get("category", "note"))
            ]
            dup = safety.find_duplicate(title, candidates)
            if dup:
                raise ValueError(
                    f"A near-duplicate already exists: [{dup[0]}] {dup[1]}. "
                    f"Call update_knowledge with append instead of adding a second copy."
                )

            keywords = normalize_keywords(args.get("keywords"))
            if not keywords:
                keywords = safety.suggest_keywords(title, body)

            entry = add_entry(
                con,
                title=title,
                body=body,
                category=args.get("category", "note"),
                keywords=keywords,
                status=args.get("status"),
            )
        finally:
            con.close()
        return _entry_json(entry, scope, full=True)

    if name == "update_knowledge":
        entry, scope = _find(args["uid"], _scopes_for(project_path))
        if entry is None:
            raise ValueError(f"No entry with uid {args['uid']!r}.")

        text = "\n".join(
            filter(None, [args.get("title"), args.get("body"), args.get("append")])
        )
        if text and (found := safety.find_secrets(text)):
            raise ValueError("Refused: possible credential (" + ", ".join(found) + ").")

        con = connect(scope)
        try:
            updated = update_entry(
                con,
                entry,
                title=args.get("title"),
                body=args.get("body"),
                append=args.get("append"),
                keywords=normalize_keywords(args["keywords"]) if args.get("keywords") else None,
                status=args.get("status"),
            )
        finally:
            con.close()
        return _entry_json(updated, scope, full=True)

    if name == "get_knowledge":
        entry, scope = _find(args["uid"], _scopes_for(project_path))
        if entry is None:
            raise ValueError(f"No entry with uid {args['uid']!r}.")
        return _entry_json(entry, scope, full=True)

    raise KeyError(name)


# ---------------------------------------------------------------- JSON-RPC


def _result(request_id: Any, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_result(payload: dict, *, is_error: bool = False) -> dict:
    """A tool result carries both structured content and its JSON as text.

    The spec asks for the text block as well, for clients that cannot read
    structuredContent. Returning only one of the two silently breaks those clients.
    """
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["isError"] = True
    else:
        result["structuredContent"] = payload
    return result


def handle(message: dict) -> dict | None:
    """Handle one JSON-RPC message. Returns a response, or None for notifications."""
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    # Notifications carry no id and must never be answered.
    if request_id is None:
        return None

    if method == "initialize":
        # Echo the client's protocol version when we can speak it, otherwise state ours.
        # Refusing outright would strand hosts that are a revision behind for no reason.
        requested = params.get("protocolVersion")
        return _result(
            request_id,
            {
                "protocolVersion": requested or PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": __version__},
                "instructions": (
                    "dejavu is a local knowledge base that survives across sessions.\n"
                    "- The user wants to continue a previous session → resume_knowledge. "
                    "Do not search for it.\n"
                    "- The user asks what they have been working on → recent_knowledge.\n"
                    "- Before investigating unfamiliar code → search_knowledge first.\n"
                    "- Store findings, decisions and handoff notes with add_knowledge; "
                    "write densely, and never store credentials.\n"
                    "- Pass project_path when the work concerns a specific repository; "
                    "omit it for knowledge about the user themselves."
                ),
            },
        )

    if method == "ping":
        return _result(request_id, {})

    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            payload = call_tool(name, args)
        except KeyError:
            return _error(request_id, -32602, f"Unknown tool: {name}")
        except ValueError as exc:
            # A tool-level failure, not a protocol failure: report it in the result so the
            # model can read the reason and act on it, rather than seeing a transport error.
            return _result(request_id, _tool_result({"error": str(exc)}, is_error=True))
        except Exception as exc:  # noqa: BLE001 - never take the host down with us
            return _result(
                request_id,
                _tool_result({"error": f"{type(exc).__name__}: {exc}"}, is_error=True),
            )
        return _result(request_id, _tool_result(payload))

    return _error(request_id, -32601, f"Method not found: {method}")


def serve(stdin=None, stdout=None) -> int:
    """Read newline-delimited JSON-RPC from stdin, write responses to stdout."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout

    try:
        preflight.check(scope_mod.state_path())
    except preflight.PreflightError as exc:
        # stderr is the only channel that will not corrupt the protocol stream.
        print(f"dejavu: {exc}", file=sys.stderr)
        return 1

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _write(stdout, _error(None, -32700, "Parse error"))
            continue

        response = handle(message)
        if response is not None:
            _write(stdout, response)

    return 0


def _write(stdout, message: dict) -> None:
    # Messages are newline-delimited and must not contain embedded newlines, so the JSON
    # is written compactly on one line.
    stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    stdout.flush()
