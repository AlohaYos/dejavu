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
from datetime import datetime
from pathlib import Path
from typing import Any

from . import __version__, link, obsidian, preflight, relate, safety
from . import scope as scope_mod
from .cli import CONFLICT_INSTRUCTION, find_conflict
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
        # Which store answered: project / user / shared (the repo's docs) / obsidian
        # (the user's vault). The model needs this to weigh two hits against each other.
        "source": scope.name,
        "file": entry.source_path,
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


OBSIDIAN_TOOLS: list[dict[str, Any]] = [
    {
        "name": "obsidian_status",
        "title": "Is an Obsidian vault connected?",
        "description": (
            "Check before writing user-level knowledge. Reports whether a vault is "
            "configured, which folders it holds, and the write mode: `append-only` means "
            "the vault syncs to other devices, so notes can be created and appended to but "
            "never rewritten. Also reports the `research` and `promote` policies the user "
            "has chosen, which govern how eagerly you should be saving to the vault."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "add_obsidian_knowledge",
        "title": "Save knowledge to the user's vault",
        "description": (
            "Save knowledge that outlives this repository — a language or framework "
            "pitfall, a tool's real behaviour, the user's own working style. The test is "
            "'would this still be true in a different repository?'. If yes, it belongs "
            "here; if no, use add_knowledge with the project scope instead.\n"
            "Notes land in the vault's Knowledge folder, and in a subfolder only when the "
            "user has already created one by that name — never invent folders. An existing "
            "note with the same title is appended to rather than duplicated. Notes the "
            "user wrote by hand are never modified."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "One-line summary."},
                "body": {"type": "string"},
                "category": {
                    "type": "string",
                    "description": (
                        "Subfolder of Knowledge/, used only if it already exists. Pass one "
                        "of the names from `knowledge_folders` in obsidian_status, spelled "
                        "exactly as it appears there — a name that matches nothing lands in "
                        "the catch-all folder instead of where it belongs."
                    ),
                },
                "tags": {"type": "array", "items": {"type": "string"}},
                "project": {"type": "string", "description": "Where this was learned."},
                "project_path": _PROJECT_PATH_SCHEMA,
            },
            "required": ["title"],
        },
    },
    {
        "name": "add_research",
        "title": "Record an investigation in the vault",
        "description": (
            "File what an investigation found, so the same ground is not covered twice: "
            "measurements, API behaviour that the documentation does not state, options "
            "compared and rejected. Filed under Research/<project>/<date>-<title>.\n"
            "Respect the user's `research` policy from obsidian_status: `findings` (the "
            "default) means save reusable discoveries but not routine session state, "
            "`all` means mirror handoff notes here too, `manual` means only when asked."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "project": {"type": "string", "description": "Default: the project_path name."},
                "tags": {"type": "array", "items": {"type": "string"}},
                "project_path": _PROJECT_PATH_SCHEMA,
            },
            "required": ["title"],
        },
    },
]

AUTOLINK_TOOL = {
    "name": "enable_autolink",
    "title": "Start the note-linking model",
    "description": (
        "Start the local model that links vault notes to each other, then add the links "
        "for every note that was waiting on it. Call this when a write reported "
        "`link_mode: deferred`, or when the user asks why their notes are not linked.\n"
        "ALWAYS ask the user before calling this: it starts a program on their machine.\n"
        "This call takes 5-30 seconds — the first run has to read a 1.2GB model from "
        "disk. Tell the user it is starting and will take a moment BEFORE you call it, "
        "or they will be left watching nothing happen."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "confirmed": {
                "type": "boolean",
                "description": "True once the user has agreed to start it.",
            }
        },
        "required": ["confirmed"],
    },
}

TOOLS.extend(OBSIDIAN_TOOLS)


LINK_TOOLS: list[dict[str, Any]] = [
    {
        "name": "plan_note_links",
        "title": "Plan links between the user's own notes",
        "description": (
            "Work out which notes in a vault folder are about the same things, and report "
            "what linking them would change. WRITES NOTHING. Use this when the user asks "
            "to connect, link or organise notes they put into the vault themselves.\n"
            "Show the user the counts it returns — especially `handwritten`, the number of "
            "their own notes that would be edited — before going any further."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder": {
                    "type": "string",
                    "description": "Folder inside the vault. Omit only with all: true.",
                },
                "all": {"type": "boolean", "description": "The whole vault. Prefer a folder."},
            },
        },
    },
    {
        "name": "apply_note_links",
        "title": "Add the planned links",
        "description": (
            "Carry out a plan from plan_note_links.\n"
            "THIS EDITS NOTES THE USER WROTE THEMSELVES. Before calling it you MUST show "
            "them the plan (how many notes, how many links, how many are their own) and "
            "get an explicit yes. Never call it on your own initiative.\n"
            "Tell them it can be undone — undo_note_links takes the added links back out "
            "and leaves anything they write afterwards alone."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "From plan_note_links."},
                "confirmed": {
                    "type": "boolean",
                    "description": "True once the user has agreed, in their own words.",
                },
                "convert_txt": {
                    "type": "boolean",
                    "description": "Rename .txt files to .md so Obsidian can see them.",
                    "default": True,
                },
            },
            "required": ["plan_id", "confirmed"],
        },
    },
    {
        "name": "undo_note_links",
        "title": "Take the added links back out",
        "description": (
            "Remove the links a previous run added, leaving every other edit in place. "
            "Defaults to the most recent run. Use this whenever the user is unhappy with "
            "the result — it is always safe, and nothing they wrote is lost."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"run": {"type": "string", "description": "Default: the last run."}},
        },
    },
]


def visible_tools() -> list[dict[str, Any]]:
    """The tool list for this machine's configuration.

    `enable_autolink` is hidden unless linking is switched on. A tool that cannot do
    anything useful still costs context on every single turn, and invites the model to
    try it and report a failure the user never needed to hear about.
    """
    cfg = scope_mod.obsidian_config()
    if not cfg.enabled:
        return TOOLS
    extra = list(LINK_TOOLS)
    if cfg.relate != "off":
        extra.append(AUTOLINK_TOOL)
    return [*TOOLS, *extra]


def _link_status(cfg, links: list[str], stored: str) -> dict:
    """How the links were chosen, and whether any are still owed.

    Without this the degradation is invisible: stderr goes nowhere an MCP host displays,
    so a user in chat would never learn that their notes are being linked by words, or
    not yet linked at all.
    """
    if cfg.relate == "off":
        return {}
    if stored == "deferred":
        waiting = len(relate.pending(cfg))
        return {
            "link_mode": "deferred",
            "pending": waiting,
            "hint": (
                "The model that links notes is not running, so links are on hold. "
                "Ask the user whether to start it, and call enable_autolink if they agree."
            ),
        }
    mode = "meaning" if cfg.relate == "embed" else "words"
    return {"link_mode": mode} if links else {"link_mode": mode, "pending": 0}


def _vault():
    cfg = scope_mod.obsidian_config()
    if not cfg.enabled or cfg.vault is None or not cfg.vault.is_dir():
        raise ValueError(
            "No Obsidian vault is configured. Ask the user to run "
            "`dejavu obsidian init <path-to-vault>` in a terminal."
        )
    return cfg.vault, cfg


def _refuse_secrets(title: str, body: str) -> None:
    """The same detector the CLI runs. Reimplementing it here would let one path leak."""
    found = safety.find_secrets(f"{title}\n{body}")
    if found:
        raise ValueError(
            "Possible secret detected: " + ", ".join(found) + ". Never store credentials."
        )


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
        scopes = obsidian.with_indexes(
            _scopes_for(project_path),
            Path(project_path).expanduser() if project_path else None,
        )
        hits = run_search(
            scopes,
            args["query"],
            category=args.get("category"),
            limit=int(args.get("limit", 10)),
        )
        payload = {
            "results": [_entry_json(hit.entry, sc, full=False) for hit, sc in hits],
            "count": len(hits),
        }
        conflict = find_conflict(hits)
        if conflict:
            payload["conflict_candidates"] = conflict
            payload["conflict_instruction"] = CONFLICT_INSTRUCTION
        return payload

    if name == "add_obsidian_knowledge":
        vault, cfg = _vault()
        body = args.get("body", "")
        _refuse_secrets(args["title"], body)
        base = vault / cfg.knowledge_dir
        mode, _ = obsidian.effective_write_mode(vault, cfg.write_mode)
        existing = obsidian.find_note(base, args["title"])
        tags = normalize_keywords(args.get("tags"))
        try:
            if existing is not None:
                obsidian.append_to_note(existing, body)
                path, action = existing, "appended"
                links = relate.apply_to_existing(cfg, path, vault=vault, mode=mode)
            else:
                links = relate.suggest_for_new(cfg, title=args["title"], body=body, keywords=tags)
                path = obsidian.create_note(
                    obsidian._category_dir(
                        base, args.get("category"), cfg.knowledge_other_dir
                    ),
                    args["title"],
                    body,
                    category=args.get("category"),
                    tags=tags,
                    project=args.get("project"),
                    related=links,
                    related_key=cfg.relate_key,
                )
                action = "created"
        except obsidian.WriteRefused as exc:
            raise ValueError(str(exc)) from exc
        obsidian.sync_vault(cfg, force=True)
        stored = relate.remember(cfg, path, vault=vault)
        relate.catch_up(cfg)
        return {
            "file": path.relative_to(vault).as_posix(),
            "action": action,
            "write_mode": mode,
            "related": links,
            **_link_status(cfg, links, stored),
        }

    if name == "add_research":
        vault, cfg = _vault()
        body = args.get("body", "")
        _refuse_secrets(args["title"], body)
        project = args.get("project") or (Path(project_path).name if project_path else None)
        if not project:
            raise ValueError("Pass `project`, or `project_path`, so the note can be filed.")
        day = datetime.now().astimezone().strftime("%Y-%m-%d")
        tags = normalize_keywords(args.get("tags"))
        links = relate.suggest_for_new(cfg, title=args["title"], body=body, keywords=tags)
        path = obsidian.create_note(
            vault / cfg.research_dir / project,
            args["title"],
            body,
            tags=tags,
            project=project,
            filename=f"{day}-{obsidian.slugify(args['title'])}",
            related=links,
            related_key=cfg.relate_key,
        )
        obsidian.sync_vault(cfg, force=True)
        stored = relate.remember(cfg, path, vault=vault)
        relate.catch_up(cfg)
        return {
            "file": path.relative_to(vault).as_posix(),
            "project": project,
            "related": links,
            **_link_status(cfg, links, stored),
        }

    if name == "enable_autolink":
        from .cli import _start_linking

        cfg = scope_mod.obsidian_config()
        if not args.get("confirmed"):
            raise ValueError("Ask the user first, then call again with confirmed: true.")
        # ask=False: the user was already asked, by Claude. A second prompt here would be
        # read from the JSON-RPC stream, which is not a place a person can answer from.
        return _start_linking(cfg, ask=False)

    if name == "plan_note_links":
        cfg = scope_mod.obsidian_config()
        _vault()
        try:
            made = link.plan(cfg, None if args.get("all") else args.get("folder"))
        except (link.LinkRefused, relate.OllamaUnavailable) as exc:
            raise ValueError(str(exc)) from exc
        payload = made.as_dict()
        payload["warning"] = (
            f"{payload['handwritten']} of these notes were written by the user. "
            "Show these numbers and get an explicit yes before applying."
        )
        return payload

    if name == "apply_note_links":
        cfg = scope_mod.obsidian_config()
        _vault()
        if not args.get("confirmed"):
            raise ValueError(
                "Show the user the plan and get their agreement, then call again with "
                "confirmed: true."
            )
        try:
            result = link.apply(
                cfg, args["plan_id"], convert_txt=args.get("convert_txt", True)
            )
        except link.LinkRefused as exc:
            raise ValueError(str(exc)) from exc
        obsidian.sync_vault(cfg, force=True)
        result["undo"] = "Call undo_note_links to take these links back out."
        return result

    if name == "undo_note_links":
        cfg = scope_mod.obsidian_config()
        _vault()
        try:
            return link.remove(cfg, args.get("run"))
        except link.LinkRefused as exc:
            raise ValueError(str(exc)) from exc

    if name == "obsidian_status":
        cfg = scope_mod.obsidian_config()
        if not cfg.enabled or cfg.vault is None:
            return {
                "configured": False,
                "hint": (
                    "No vault is set up. Ask the user to run `dejavu obsidian init "
                    "<path-to-vault>` in a terminal. Until then, user-level knowledge has "
                    "nowhere to go and should stay in the project scope."
                ),
            }
        mode, reason = obsidian.effective_write_mode(cfg.vault, cfg.write_mode)
        scope = scope_mod.obsidian_scope()
        return {
            "configured": True,
            "vault": str(cfg.vault),
            "write_mode": mode,
            "reason": reason,
            "by_folder": {f: obsidian.count_in_folder(scope, f) for f in cfg.include},
            # The subfolders of Knowledge/, so `category` can be given a name that exists
            # rather than one that seems reasonable. A guess that matches nothing puts the
            # note in the catch-all, which is safe but not where it belongs.
            "knowledge_folders": obsidian.subfolders(cfg.vault / cfg.knowledge_dir),
            "catch_all_folder": cfg.knowledge_other_dir,
            "research": cfg.research,
            "promote": cfg.promote,
            "relate": cfg.relate,
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
        return _result(request_id, {"tools": visible_tools()})

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
