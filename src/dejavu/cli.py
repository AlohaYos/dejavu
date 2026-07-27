"""The dejavu command-line interface.

Output is designed to be read by Claude first and a human second:
- search results trim the body by default, so recalling knowledge does not devour the
  very context the knowledge base exists to protect
- exit code 2 means "no results", which is easy for an agent to branch on
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path

from . import __version__, obsidian, preflight, safety, store
from . import scope as scope_mod
from .scope import CATEGORIES, STATUSES, Scope
from .search import search as run_search
from .store import Entry, connect

UTC = timezone.utc

SNIPPET_LEN = 150
DEFAULT_RECENT_SINCE = "2d"
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOT_FOUND = 2

IMPORT_LINE = "@.dejavu/dejavu-triggers.md"
GITIGNORE_LINES = [
    ".dejavu/knowledge.db",
    ".dejavu/knowledge.db-*",
    # An index of docs/knowledge/*.md, rebuilt from files that are themselves tracked.
    # Committing it would put a binary in every review for no gain.
    ".dejavu/shared.db",
    ".dejavu/shared.db-*",
]


# ---------------------------------------------------------------- helpers


def die(message: str, code: int = EXIT_ERROR) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def _asset(name: str) -> str:
    return (resources.files("dejavu.assets") / name).read_text(encoding="utf-8")


def _parse_since(value: str | None) -> str | None:
    """Turn 'today' / '7d' / '2026-07-01' into an ISO8601 timestamp."""
    if not value:
        return None
    now = datetime.now(UTC)
    if value == "today":
        dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif value.endswith("d") and value[:-1].isdigit():
        dt = now - timedelta(days=int(value[:-1]))
    else:
        try:
            dt = datetime.fromisoformat(value).replace(tzinfo=UTC)
        except ValueError as exc:
            die(f"Invalid --since value: {value} (expected today, 7d, or 2026-07-01)")
            raise AssertionError from exc  # pragma: no cover
    return store.iso(dt)


def _snippet(text: str, length: int = SNIPPET_LEN) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= length else flat[:length] + "…"


def _read_body(arg: str | None) -> str:
    """Read the body from stdin when --body is '-' or omitted with piped input.

    This is the main path by which Claude passes long-form content.
    """
    if arg == "-":
        return sys.stdin.read().strip()
    if arg is not None:
        return arg
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return ""


def _entry_dict(entry: Entry, scope: Scope) -> dict:
    return {
        "uid": entry.uid,
        "id": entry.id,
        "scope": entry.scope,
        "source": entry.scope,
        "file": entry.source_path,
        "title": entry.title,
        "body": entry.body,
        "category": entry.category,
        "storage": entry.storage,
        "status": entry.status,
        "keywords": entry.keywords,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "checked_at": entry.checked_at,
        "stale_days": entry.stale_days(scope.stale_days),
    }


def _render(entry: Entry, scope: Scope, *, full: bool = False) -> str:
    stale = entry.stale_days(scope.stale_days)
    mark = "  ⚠" if stale else "   "
    bits = [f"({entry.category})"]
    if entry.status:
        bits.append(f"[{entry.status}]")
    if entry.scope != "project":
        bits.append(f"[{entry.scope}]")
    if stale:
        bits.append(f"[STALE: {stale} days since last check]")

    lines = [f"{mark} [{entry.uid}] {entry.title} {' '.join(bits)}"]
    if entry.source_path:
        lines.append(f"       File: {entry.source_path}")
    if entry.keywords:
        lines.append(f"       Keywords: {', '.join(entry.keywords)}")
    if entry.body:
        if full:
            lines.extend("       " + ln for ln in entry.body.splitlines())
        else:
            lines.append(f"       {_snippet(entry.body)}")
    return "\n".join(lines)


def _find_anywhere(ref: str, scopes: list[Scope]) -> tuple[Entry, Scope] | None:
    for scope in scopes:
        if not scope.db_path.exists():
            continue
        con = connect(scope)
        try:
            entry = store.get_entry(con, ref, scope.name)
            if entry:
                return entry, scope
        finally:
            con.close()
    return None


def _append_once(path: Path, lines: list[str], header: str | None = None) -> bool:
    """Append lines that are not already present. Returns True if anything was written."""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    missing = [ln for ln in lines if ln not in existing]
    if not missing:
        return False
    chunk = ""
    if existing and not existing.endswith("\n"):
        chunk += "\n"
    if header and header not in existing:
        chunk += f"\n{header}\n"
    chunk += "\n".join(missing) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(chunk)
    return True


def _install_commands(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    src = resources.files("dejavu.assets") / "commands"
    for item in src.iterdir():
        if item.name.endswith(".md"):
            (dest / item.name).write_text(item.read_text(encoding="utf-8"), encoding="utf-8")


# ---------------------------------------------------------------- vault prompts
#
# Everything below is printed *by the command that just ran*, never added to
# dejavu-triggers.md. The triggers file is read on every single turn of every session, so
# a rule parked there is paid for constantly and used almost never. Emitting the same
# guidance from the command that detected the situation costs nothing until it fires.

CONFLICT_TOP_N = 5
PROJECT_SIDE = ("project", "shared")

CONFLICT_BANNER = "  ⚠ CONFLICT RISK — the project and the vault both answer this query:"
CONFLICT_INSTRUCTION = (
    "\n    They may disagree. Read both before you act on either.\n"
    "    If they do disagree, do not choose silently: show the user both versions, ask\n"
    "    which one to adopt, and then correct the other side."
)

PROMOTE_PROMPT = {
    "ask": (
        "  ? Does this apply beyond this repository? If so, ask the user:\n"
        "      1. yes (this time)   2. no (this time)   3. always yes   4. always no\n"
        '    On yes:  dejavu obsidian add "<title>" --tags "..." --body -\n'
        "    On 3/4:  dejavu config promote always|never"
    ),
    "always": (
        "  → promote = always. If this applies beyond this repository, save it to the\n"
        '    vault now without asking:  dejavu obsidian add "<title>" --body -'
    ),
}

RESEARCH_PROMPT = {
    "all": (
        "  → research = all. Mirror this to the vault:\n"
        '      dejavu research "<title>" --body -'
    ),
    "findings": (
        "  → research = findings. If this holds a reusable finding rather than just\n"
        '    today\'s state:  dejavu research "<title>" --body -'
    ),
}


def vault_followup(entry: Entry, scope: Scope, research_override: str | None = None) -> list[str]:
    """Guidance to print after a project entry is saved, if a vault is configured."""
    cfg = scope_mod.obsidian_config()
    if not cfg.enabled or scope.name != "project":
        return []
    if entry.category == "context":
        return [line for line in [RESEARCH_PROMPT.get(research_override or cfg.research)] if line]
    return [line for line in [PROMOTE_PROMPT.get(cfg.promote)] if line]


def _conflict_side(pair: tuple) -> dict:
    hit, sc = pair
    return {
        "source": sc.name,
        "uid": hit.entry.uid,
        "title": hit.entry.title,
        "file": hit.entry.source_path,
    }


def find_conflict(results: list[tuple]) -> list[dict]:
    """Both sides answered the same question, so they might contradict each other.

    Nothing here judges whether they actually disagree — that needs reading, which is the
    model's job. Detection stops at "these two are about to be used together".
    """
    top = results[:CONFLICT_TOP_N]
    project = next((p for p in top if p[1].name in PROJECT_SIDE), None)
    vault = next((p for p in top if p[1].name == "obsidian"), None)
    if project is None or vault is None:
        return []
    return [_conflict_side(project), _conflict_side(vault)]


# ---------------------------------------------------------------- commands


def cmd_init(args: argparse.Namespace) -> int:
    if args.globally:
        home = Path.home() / ".claude"
        home.mkdir(parents=True, exist_ok=True)
        (home / "dejavu-triggers.md").write_text(_asset("dejavu-triggers.md"), encoding="utf-8")
        _append_once(
            home / "CLAUDE.md",
            ["@~/.claude/dejavu-triggers.md"],
            header="## Knowledge base",
        )
        _install_commands(home / "commands")
        connect(scope_mod.user_scope()).close()  # make sure the user-scope DB exists
        print(f"✓ Installed global instructions in {home}")
        print("  Knowledge now accumulates in the user scope even outside initialised projects.")
        return EXIT_OK

    root = Path.cwd()
    kdir = root / scope_mod.DEJAVU_DIR
    created = not kdir.exists()
    kdir.mkdir(parents=True, exist_ok=True)

    (kdir / "dejavu-triggers.md").write_text(_asset("dejavu-triggers.md"), encoding="utf-8")

    config = kdir / scope_mod.CONFIG_NAME
    if not config.exists():
        config.write_text(_asset("config.toml"), encoding="utf-8")

    scope = scope_mod.project_scope(root)
    assert scope is not None
    connect(scope).close()

    _append_once(root / "CLAUDE.md", [IMPORT_LINE], header="## Knowledge base")
    _append_once(root / ".gitignore", GITIGNORE_LINES, header="# dejavu")
    _install_commands(root / ".claude" / "commands")

    print(f"{'✓ Initialised' if created else '✓ Updated'} {kdir}")
    print(f"  database   : {scope.db_path}")
    print(f"  CLAUDE.md  : added {IMPORT_LINE}")
    print("  .gitignore : excluded knowledge.db (the .md files stay shared via git)")
    print()
    print('Next: `dejavu add "..."` to store knowledge, `dejavu search "..."` to recall it.')
    print("Start Claude Code and it will read and write the knowledge base on its own.")
    return EXIT_OK


def cmd_add(args: argparse.Namespace) -> int:
    scope = scope_mod.resolve_write(args.scope)
    body = _read_body(args.body)

    found = safety.find_secrets(f"{args.title}\n{body}")
    if found and not args.force:
        die(
            "Possible secret detected: "
            + ", ".join(found)
            + "\n  Never store credentials in the knowledge base."
            + "\n  Use --force if this is a false positive."
        )

    keywords = store.normalize_keywords(args.keywords)
    if not keywords:
        keywords = safety.suggest_keywords(args.title, body)

    con = connect(scope)
    try:
        if not args.force:
            candidates = [
                (e.uid, e.title)
                for e in store.list_entries(con, scope.name, category=args.category)
            ]
            dup = safety.find_duplicate(args.title, candidates)
            if dup:
                uid, title = dup
                print(f"Similar entry already exists: [{uid}] {title}", file=sys.stderr)
                print(
                    f"  Nothing was added. To extend the existing entry:\n"
                    f"    dejavu edit {uid} --append '<text to append>'\n"
                    f"  To add this as a separate entry, pass --force.",
                    file=sys.stderr,
                )
                return EXIT_ERROR

        entry = store.add_entry(
            con,
            title=args.title,
            body=body,
            category=args.category,
            keywords=keywords,
            status=args.status,
        )
    except ValueError as exc:
        die(str(exc))
        raise AssertionError from exc  # pragma: no cover
    finally:
        con.close()

    if args.json:
        print(json.dumps(_entry_dict(entry, scope), ensure_ascii=False))
    else:
        print(f"✓ Saved [{entry.uid}] ({entry.category}, {scope.name} scope)")
        if entry.keywords:
            print(f"  Keywords: {', '.join(entry.keywords)}")
        for line in vault_followup(entry, scope, getattr(args, "research", None)):
            print(line)
    return EXIT_OK


def cmd_search(args: argparse.Namespace) -> int:
    scopes = scope_mod.resolve_read(args.scope)
    if args.scope is None:
        scopes = obsidian.with_indexes(scopes, scope_mod.find_project_root())
    results = run_search(
        scopes,
        args.query,
        category=args.category,
        since=_parse_since(args.since),
        limit=args.limit,
    )
    conflict = find_conflict(results)

    if args.json:
        payload: dict = {
            "results": [
                _entry_dict(hit.entry, sc) | {"score": round(hit.score, 3), "tiers": hit.tiers}
                for hit, sc in results
            ]
        }
        if conflict:
            payload["conflict_candidates"] = conflict
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return EXIT_OK if results else EXIT_NOT_FOUND

    if not results:
        print(f"No results for {args.query!r}")
        return EXIT_NOT_FOUND

    print()
    for hit, sc in results:
        print(_render(hit.entry, sc, full=args.full))
        print()
    if conflict:
        print(CONFLICT_BANNER)
        for side in conflict:
            print(f"    {side['source']:9} [{side['uid']}] {side['title']}")
        print(CONFLICT_INSTRUCTION)
        print()
    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    scopes = scope_mod.resolve_read(args.scope)
    since = _parse_since(args.since)

    collected: list[tuple[Entry, Scope]] = []
    for sc in scopes:
        if not sc.db_path.exists():
            continue
        con = connect(sc)
        try:
            for entry in store.list_entries(
                con, sc.name, category=args.category, status=args.status, since=since
            ):
                if args.stale and entry.stale_days(sc.stale_days) is None:
                    continue
                collected.append((entry, sc))
        finally:
            con.close()

    collected.sort(key=lambda pair: pair[0].updated_at, reverse=True)
    collected = collected[: args.limit]

    if args.json:
        print(json.dumps([_entry_dict(e, sc) for e, sc in collected], ensure_ascii=False, indent=2))
        return EXIT_OK if collected else EXIT_NOT_FOUND

    if not collected:
        print("No entries")
        return EXIT_NOT_FOUND

    print()
    for entry, sc in collected:
        print(_render(entry, sc, full=args.full))
        print()
    return EXIT_OK


def cmd_resume(args: argparse.Namespace) -> int:
    """Print the most recent context entry — the "where did we leave off" command."""
    scopes = scope_mod.resolve_read(args.scope)

    best: tuple[Entry, Scope] | None = None
    for sc in scopes:
        if not sc.db_path.exists():
            continue
        con = connect(sc)
        try:
            entry = store.latest_context(con, sc.name)
        finally:
            con.close()
        if entry and (best is None or entry.updated_at > best[0].updated_at):
            best = (entry, sc)

    if best is None:
        if args.json:
            print("null")
        else:
            print("No handoff note found.", file=sys.stderr)
            print(
                "  Save one at the end of a session with /dejavu-save-context, or:\n"
                '    dejavu add "NEXT: <what to do next>" --category context --body -',
                file=sys.stderr,
            )
        return EXIT_NOT_FOUND

    entry, sc = best

    if args.json:
        print(json.dumps(_entry_dict(entry, sc) | {"age": entry.age_phrase}, ensure_ascii=False,
                         indent=2))
        return EXIT_OK

    scope_bit = "  [user]" if entry.scope == "user" else ""
    print()
    print(f"  [{entry.uid}] {entry.title} ({entry.category}){scope_bit}")
    print(
        f"  saved: {entry.local_date} ({entry.age_phrase})"
        + (f"   keywords: {', '.join(entry.keywords)}" if entry.keywords else "")
    )
    print()
    # Printed in full, never trimmed: the whole purpose of this command is to be read.
    print(entry.body or "(no body)")
    print()
    return EXIT_OK


def cmd_recent(args: argparse.Namespace) -> int:
    """Recent activity, grouped by day — for "what have I been up to" and standup notes."""
    scopes = scope_mod.resolve_read(args.scope)
    since = _parse_since(args.since) or _parse_since(DEFAULT_RECENT_SINCE)
    assert since is not None

    collected: list[tuple[Entry, Scope]] = []
    for sc in scopes:
        if not sc.db_path.exists():
            continue
        con = connect(sc)
        try:
            for entry in store.recent_entries(
                con, sc.name, since=since, category=args.category, limit=args.limit
            ):
                collected.append((entry, sc))
        finally:
            con.close()

    collected.sort(key=lambda pair: pair[0].updated_at, reverse=True)
    collected = collected[: args.limit]

    if args.json:
        print(
            json.dumps(
                [_entry_dict(e, sc) | {"date": str(e.local_date)} for e, sc in collected],
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_OK if collected else EXIT_NOT_FOUND

    if not collected:
        print(f"No activity since {args.since or DEFAULT_RECENT_SINCE}.")
        return EXIT_NOT_FOUND

    print()
    current_day = None
    for entry, sc in collected:
        if entry.local_date != current_day:
            current_day = entry.local_date
            print(f"  {current_day} ({entry.age_phrase})")
        print(_render(entry, sc, full=args.full))
        print()
    return EXIT_OK


def cmd_mcp(args: argparse.Namespace) -> int:
    """Speak MCP on stdin/stdout. Launched by the host, not by a human."""
    from . import mcp

    return mcp.serve()


# Hosts that launch stdio MCP servers, and where their config lives.
MCP_HOSTS = {
    "claude-desktop": Path.home()
    / "Library/Application Support/Claude/claude_desktop_config.json",
    "cowork": Path.home() / "Library/Application Support/Claude/claude_desktop_config.json",
}


def _mcp_binary() -> Path:
    """The absolute path to write into a host's MCP config.

    Absolute, because the host launches the server from an environment that does not
    inherit your login shell — a bare `dejavu` would very likely not be found.

    But *not* resolved through its symlinks. Homebrew's `/usr/local/bin/dejavu` points into
    a version-stamped Cellar directory (`.../Cellar/dejavu/0.3.0/bin/dejavu`), and that
    directory disappears on the next `brew upgrade`. Writing the resolved path would leave
    the host launching a binary that no longer exists — and it would fail silently, months
    later, for no reason the user could connect to anything they did.
    """
    from shutil import which

    found = which(Path(sys.argv[0]).name)
    if found:
        return Path(found)
    return Path(sys.argv[0]).absolute()


def cmd_install_mcp(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser() if args.config else MCP_HOSTS["claude-desktop"]

    binary = _mcp_binary()
    if not binary.exists():  # pragma: no cover - defensive
        die(f"Cannot resolve the dejavu binary from {sys.argv[0]!r}")

    config: dict = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except ValueError:
            die(
                f"{config_path} is not valid JSON. Fix or move it before running "
                f"install-mcp, so this command does not destroy a config it cannot parse."
            )

    servers = config.setdefault("mcpServers", {})
    if "dejavu" in servers and not args.force:
        print(f"dejavu is already registered in {config_path}", file=sys.stderr)
        print("  Use --force to overwrite it.", file=sys.stderr)
        return EXIT_ERROR

    servers["dejavu"] = {"command": str(binary), "args": ["mcp"]}

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"✓ Registered the dejavu MCP server in {config_path}")
    print(f"  command: {binary} mcp")
    print()
    print("Restart the host application to pick it up.")
    print()
    print("The server has no working directory of its own, so a project cannot be inferred.")
    print("Tell Claude which repository you mean, and it will pass the path:")
    print('  "search my MyApp project for the CoreData migration notes"')
    print("Without a path, only the user scope is used.")
    return EXIT_OK


def cmd_show(args: argparse.Namespace) -> int:
    found = _find_anywhere(args.ref, scope_mod.resolve_read(args.scope))
    if not found:
        print(f"Not found: {args.ref}", file=sys.stderr)
        return EXIT_NOT_FOUND
    entry, sc = found

    if args.json:
        print(json.dumps(_entry_dict(entry, sc), ensure_ascii=False, indent=2))
        return EXIT_OK

    stale = entry.stale_days(sc.stale_days)
    print(f"[{entry.uid}] {entry.title}")
    print(f"  category : {entry.category}" + (f"   status: {entry.status}" if entry.status else ""))
    print(f"  scope    : {entry.scope}   storage: {entry.storage}")
    print(f"  keywords : {', '.join(entry.keywords) or '-'}")
    print(f"  updated  : {entry.updated_at}   checked: {entry.checked_at}")
    if stale:
        print(f"  ⚠ STALE  : {stale} days since it was last verified")
        print("             Check it against the current code before relying on it.")
        print(f"             Still correct? Run: dejavu touch {entry.uid}")
    print()
    print(entry.body or "(no body)")
    return EXIT_OK


def cmd_edit(args: argparse.Namespace) -> int:
    found = _find_anywhere(args.ref, scope_mod.resolve_read(None))
    if not found:
        print(f"Not found: {args.ref}", file=sys.stderr)
        return EXIT_NOT_FOUND
    entry, sc = found

    append = _read_body(args.append) if args.append is not None else None
    body = _read_body(args.body) if args.body is not None else None
    text = "\n".join(filter(None, [args.title, body, append]))
    if text and (secrets_found := safety.find_secrets(text)) and not args.force:
        die("Possible secret detected: " + ", ".join(secrets_found))

    con = connect(sc)
    try:
        updated = store.update_entry(
            con,
            entry,
            title=args.title,
            body=body,
            append=append,
            keywords=store.normalize_keywords(args.keywords) if args.keywords else None,
            status=args.status,
        )
    finally:
        con.close()

    print(f"✓ Updated [{updated.uid}] {updated.title}")
    return EXIT_OK


def cmd_touch(args: argparse.Namespace) -> int:
    found = _find_anywhere(args.ref, scope_mod.resolve_read(None))
    if not found:
        print(f"Not found: {args.ref}", file=sys.stderr)
        return EXIT_NOT_FOUND
    entry, sc = found
    con = connect(sc)
    try:
        store.touch_entry(con, entry)
    finally:
        con.close()
    print(f"✓ Marked as verified [{entry.uid}] {entry.title}")
    return EXIT_OK


def cmd_rm(args: argparse.Namespace) -> int:
    found = _find_anywhere(args.ref, scope_mod.resolve_read(None))
    if not found:
        print(f"Not found: {args.ref}", file=sys.stderr)
        return EXIT_NOT_FOUND
    entry, sc = found

    if not args.yes:
        print(f"Delete this entry? [{entry.uid}] {entry.title} ({entry.category})")
        if input("  yes/no > ").strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return EXIT_OK

    con = connect(sc)
    try:
        store.delete_entry(con, entry)
    finally:
        con.close()
    print(f"✓ Deleted [{entry.uid}]")
    return EXIT_OK


def cmd_stats(args: argparse.Namespace) -> int:
    scopes = scope_mod.resolve_read(args.scope)
    payload: dict[str, dict] = {}

    for sc in scopes:
        if not sc.db_path.exists():
            continue
        con = connect(sc)
        try:
            entries = store.list_entries(con, sc.name)
        finally:
            con.close()

        by_cat: dict[str, int] = {}
        stale = 0
        for e in entries:
            by_cat[e.category] = by_cat.get(e.category, 0) + 1
            if e.stale_days(sc.stale_days) is not None:
                stale += 1
        payload[sc.name] = {
            "db": str(sc.db_path),
            "total": len(entries),
            "stale": stale,
            "by_category": by_cat,
        }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return EXIT_OK

    if not payload:
        print("No knowledge base yet. Run `dejavu init`.")
        return EXIT_NOT_FOUND

    for name, data in payload.items():
        print(f"[{name}] {data['db']}")
        print(f"  total: {data['total']}   stale: {data['stale']}")
        for cat, count in sorted(data["by_category"].items(), key=lambda kv: -kv[1]):
            print(f"    {cat:<12} {count}")
        print()
    return EXIT_OK


# ---------------------------------------------------------------- parser


# ---------------------------------------------------------------- obsidian / config

PRESETS: dict[str, list[str]] = {
    "none": [],
    "dev": ["API", "Architecture", "Patterns", "Tools"],
}

CONFIG_KEYS = (
    "vault",
    "include",
    "knowledge_dir",
    "userinfo_dir",
    "research_dir",
    "write_mode",
    "research",
    "promote",
)

CROWDED_FOLDER = 100


def _require_vault(cli_vault: str | None = None) -> tuple[Path, scope_mod.ObsidianConfig]:
    cfg = scope_mod.obsidian_config()
    vault = Path(cli_vault).expanduser() if cli_vault else cfg.vault
    if vault is None:
        die(
            "No Obsidian vault configured.\n"
            "  dejavu obsidian init <path-to-vault>\n"
            "  A vault is just a folder of Markdown; see https://help.obsidian.md/vault"
        )
        raise AssertionError  # pragma: no cover
    if not vault.is_dir():
        die(f"Not a directory: {vault}")
    return vault, cfg


def cmd_obsidian_init(args: argparse.Namespace) -> int:
    vault = Path(args.vault).expanduser()
    if not vault.is_dir():
        die(f"Not a directory: {vault}\n  Create the vault in Obsidian first.")

    scope_mod.set_config_value(scope_mod.user_config_path(), "obsidian", "vault", str(vault))
    cfg = scope_mod.obsidian_config()

    created: list[str] = []
    for folder in (cfg.knowledge_dir, cfg.userinfo_dir, cfg.research_dir):
        path = vault / folder
        if not path.exists():
            path.mkdir(parents=True)
            created.append(folder)
    for folder in PRESETS[args.preset]:
        path = vault / cfg.knowledge_dir / folder
        if not path.exists():
            path.mkdir(parents=True)
            created.append(f"{cfg.knowledge_dir}/{folder}")

    stats = obsidian.sync_vault(cfg, force=True)
    mode, reason = obsidian.effective_write_mode(vault, cfg.write_mode)

    print(f"✓ Vault registered: {vault}")
    if created:
        print(f"  Created: {', '.join(created)}")
    if stats:
        print(f"  Indexed {stats.total} notes from {', '.join(stats.scanned_dirs or [])}")
    print(f"  Write mode: {mode} — {reason}")
    if args.preset == "none":
        print(
            f"  {cfg.knowledge_dir}/ is flat. Make any subfolders you like and dejavu will\n"
            f"  file notes into them; it never invents folders of its own."
        )
    return EXIT_OK


def cmd_obsidian_sync(args: argparse.Namespace) -> int:
    _, cfg = _require_vault()
    stats = obsidian.sync_vault(cfg, force=True)
    assert stats is not None
    root = scope_mod.find_project_root()
    shared = obsidian.sync_shared(root) if root else None

    if args.json:
        payload = {"obsidian": stats.as_dict()}
        if shared:
            payload["shared"] = shared.as_dict()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return EXIT_OK

    print(
        f"✓ Vault: +{stats.added} added, {stats.updated} updated, "
        f"-{stats.removed} removed ({stats.total} total)"
    )
    if shared:
        print(
            f"  {obsidian.SHARED_DIR}: +{shared.added} added, {shared.updated} updated, "
            f"-{shared.removed} removed ({shared.total} total)"
        )
    return EXIT_OK


def cmd_obsidian_doctor(args: argparse.Namespace) -> int:
    vault, cfg = _require_vault(args.vault)
    mode, reason = obsidian.effective_write_mode(vault, cfg.write_mode)
    scope = scope_mod.obsidian_scope()
    counts = {folder: obsidian.count_in_folder(scope, folder) for folder in cfg.include}
    indexed = sum(counts.values())

    if args.json:
        print(
            json.dumps(
                {
                    "vault": str(vault),
                    "write_mode": mode,
                    "reason": reason,
                    "indexed": indexed,
                    "by_folder": counts,
                    "research": cfg.research,
                    "promote": cfg.promote,
                    "index_db": str(scope.db_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_OK

    print(f"Vault       {vault}")
    print(f"Index       {scope.db_path} ({indexed} notes)")
    for folder, count in counts.items():
        print(f"              {folder}/  {count}")
    print(f"Write mode  {mode}")
    print(f"              because {reason}")
    print(f"Settings    research = {cfg.research}, promote = {cfg.promote}")
    if not scope.db_path.exists():
        print("\n  Not indexed yet. Run: dejavu obsidian sync")
    crowded = [f for f, c in counts.items() if c > CROWDED_FOLDER]
    for folder in crowded:
        print(
            f"\n  {folder}/ holds {counts[folder]} notes. Search does not care, but the file\n"
            f"  explorer will. Consider grouping them into subfolders — dejavu will follow."
        )
    return EXIT_OK


def cmd_obsidian_add(args: argparse.Namespace) -> int:
    vault, cfg = _require_vault()
    body = _read_body(args.body)

    found = safety.find_secrets(f"{args.title}\n{body}")
    if found and not args.force:
        die(
            "Possible secret detected: "
            + ", ".join(found)
            + "\n  Never store credentials in the vault."
            + "\n  Use --force if this is a false positive."
        )

    base = vault / cfg.knowledge_dir
    mode, reason = obsidian.effective_write_mode(vault, cfg.write_mode)
    existing = obsidian.find_note(base, args.title)

    try:
        if existing is not None and args.replace:
            obsidian.replace_body(existing, body, mode=mode)
            path, verb = existing, "Replaced"
        elif existing is not None:
            obsidian.append_to_note(existing, body)
            path, verb = existing, "Appended to"
        else:
            path = obsidian.create_note(
                obsidian._category_dir(base, args.category),
                args.title,
                body,
                category=args.category,
                tags=store.normalize_keywords(args.tags),
                project=args.project,
            )
            verb = "Wrote"
    except obsidian.WriteRefused as exc:
        die(str(exc))
        raise AssertionError from exc  # pragma: no cover

    obsidian.sync_vault(cfg, force=True)
    rel = path.relative_to(vault)
    if args.json:
        print(json.dumps({"file": rel.as_posix(), "action": verb.lower()}, ensure_ascii=False))
    else:
        print(f"✓ {verb} {rel.as_posix()}  ({mode})")
    return EXIT_OK


def cmd_research(args: argparse.Namespace) -> int:
    vault, cfg = _require_vault()
    body = _read_body(args.body)

    found = safety.find_secrets(f"{args.title}\n{body}")
    if found and not args.force:
        die("Possible secret detected: " + ", ".join(found) + "\n  Use --force to override.")

    root = scope_mod.find_project_root()
    project = args.project or (root.name if root else None)
    if not project:
        die("No project could be inferred. Pass --project <name>.")

    day = datetime.now().astimezone().strftime("%Y-%m-%d")
    path = obsidian.create_note(
        vault / cfg.research_dir / project,
        args.title,
        body,
        tags=store.normalize_keywords(args.tags),
        project=project,
        filename=f"{day}-{obsidian.slugify(args.title)}",
    )
    obsidian.sync_vault(cfg, force=True)

    rel = path.relative_to(vault).as_posix()
    if args.json:
        print(json.dumps({"file": rel, "project": project}, ensure_ascii=False))
    else:
        print(f"✓ Wrote {rel}")
    return EXIT_OK


def cmd_config(args: argparse.Namespace) -> int:
    path = scope_mod.user_config_path()
    cfg = scope_mod.obsidian_config()
    current = {
        "vault": str(cfg.vault) if cfg.vault else "",
        "include": ", ".join(cfg.include),
        "knowledge_dir": cfg.knowledge_dir,
        "userinfo_dir": cfg.userinfo_dir,
        "research_dir": cfg.research_dir,
        "write_mode": cfg.write_mode,
        "research": cfg.research,
        "promote": cfg.promote,
    }

    if args.key is None:
        print(f"{path}\n")
        for key, value in current.items():
            print(f"  {key:14} {value}")
        return EXIT_OK

    if args.key not in CONFIG_KEYS:
        die(f"Unknown key: {args.key} (expected one of: {', '.join(CONFIG_KEYS)})")

    if args.value is None:
        print(current[args.key])
        return EXIT_OK

    allowed = scope_mod.OBSIDIAN_CHOICES.get(args.key)
    if allowed and args.value not in allowed:
        die(f"Invalid value for {args.key}: {args.value} (expected one of: {', '.join(allowed)})")

    scope_mod.set_config_value(path, "obsidian", args.key, args.value)
    print(f"✓ {args.key} = {args.value}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dejavu",
        description="A local knowledge base that lets Claude Code pick up where it left off.",
    )
    p.add_argument("--version", action="version", version=f"dejavu {__version__}")
    p.add_argument(
        "--research",
        choices=("all", "findings", "manual"),
        help="override the research policy for this call (default: from config.toml)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add_scope(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--scope",
            choices=["project", "user"],
            help="default: both when reading, project-first when writing",
        )

    def add_json(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--json", action="store_true", help="machine-readable output")

    sp = sub.add_parser("init", help="initialise a knowledge base")
    sp.add_argument(
        "--global",
        dest="globally",
        action="store_true",
        help="install instructions into ~/.claude so every project can use dejavu",
    )
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("add", help="store a piece of knowledge")
    sp.add_argument("title")
    sp.add_argument("--body", help="body text; '-' or omitted reads from stdin")
    sp.add_argument("--category", choices=list(CATEGORIES), default="note")
    sp.add_argument("--keywords", help="comma-separated; hand-pick 5-10 of them")
    sp.add_argument("--status", choices=list(STATUSES))
    sp.add_argument("--force", action="store_true", help="ignore duplicate and secret warnings")
    add_scope(sp)
    add_json(sp)
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("search", help="search the knowledge base")
    sp.add_argument("query")
    sp.add_argument("--category", choices=list(CATEGORIES))
    sp.add_argument("--since", help="today | 7d | 2026-07-01")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--full", action="store_true", help="print full bodies instead of snippets")
    add_scope(sp)
    add_json(sp)
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("list", help="list entries")
    sp.add_argument("--category", choices=list(CATEGORIES))
    sp.add_argument("--status", choices=list(STATUSES))
    sp.add_argument("--since", help="today | 7d | 2026-07-01")
    sp.add_argument("--stale", action="store_true", help="only entries that have gone stale")
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--full", action="store_true")
    add_scope(sp)
    add_json(sp)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser(
        "resume",
        help="print the latest handoff note — use this for 'continue from yesterday'",
    )
    add_scope(sp)
    add_json(sp)
    sp.set_defaults(func=cmd_resume)

    sp = sub.add_parser(
        "recent",
        help="recent activity grouped by day — use this for 'what have I been working on'",
    )
    sp.add_argument(
        "--since",
        default=DEFAULT_RECENT_SINCE,
        help=f"today | 2d | 2026-07-01 (default: {DEFAULT_RECENT_SINCE})",
    )
    sp.add_argument(
        "--category",
        choices=list(CATEGORIES),
        help="default: context, plan and decision (research caches are excluded)",
    )
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--full", action="store_true")
    add_scope(sp)
    add_json(sp)
    sp.set_defaults(func=cmd_recent)

    sp = sub.add_parser("show", help="print an entry in full")
    sp.add_argument("ref", help="UID or numeric ID")
    add_scope(sp)
    add_json(sp)
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("edit", help="update an entry")
    sp.add_argument("ref")
    sp.add_argument("--title")
    sp.add_argument("--body", help="replace the body; '-' reads from stdin")
    sp.add_argument("--append", help="append to the body; '-' reads from stdin")
    sp.add_argument("--keywords")
    sp.add_argument("--status", choices=list(STATUSES))
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_edit)

    sp = sub.add_parser("touch", help="mark an entry as verified without changing it")
    sp.add_argument("ref")
    sp.set_defaults(func=cmd_touch)

    sp = sub.add_parser("rm", help="delete an entry")
    sp.add_argument("ref")
    sp.add_argument("--yes", "-y", action="store_true", help="skip the confirmation prompt")
    sp.set_defaults(func=cmd_rm)

    sp = sub.add_parser("stats", help="entry counts, category breakdown, stale count")
    add_scope(sp)
    add_json(sp)
    sp.set_defaults(func=cmd_stats)

    sp = sub.add_parser(
        "mcp",
        help="run the MCP server on stdin/stdout (launched by the host, not by you)",
    )
    sp.set_defaults(func=cmd_mcp)

    sp = sub.add_parser("obsidian", help="index and write to an Obsidian vault")
    obs = sp.add_subparsers(dest="obsidian_command", required=True)

    osp = obs.add_parser("init", help="register a vault and index it")
    osp.add_argument("vault", help="path to the vault folder")
    osp.add_argument(
        "--preset",
        choices=list(PRESETS),
        default="none",
        help="starter folders under Knowledge/ (default: none — stay flat)",
    )
    osp.set_defaults(func=cmd_obsidian_init)

    osp = obs.add_parser("sync", help="refresh the index from the Markdown on disk")
    add_json(osp)
    osp.set_defaults(func=cmd_obsidian_sync)

    osp = obs.add_parser("doctor", help="vault path, write mode and why, index counts")
    osp.add_argument("--vault", help="check a different vault without changing the config")
    add_json(osp)
    osp.set_defaults(func=cmd_obsidian_doctor)

    osp = obs.add_parser("add", help="write a note into the vault's Knowledge folder")
    osp.add_argument("title")
    osp.add_argument("--body", help="body text; '-' or omitted reads from stdin")
    osp.add_argument("--category", help="a subfolder of Knowledge/, used only if it exists")
    osp.add_argument("--tags", help="comma-separated; written to the note's frontmatter")
    osp.add_argument("--project", help="the project this was learned in")
    osp.add_argument(
        "--replace",
        action="store_true",
        help="replace the body of an existing note (refused on a synced vault)",
    )
    osp.add_argument("--force", action="store_true", help="ignore secret warnings")
    add_json(osp)
    osp.set_defaults(func=cmd_obsidian_add)

    sp = sub.add_parser("research", help="record an investigation in the vault")
    sp.add_argument("title")
    sp.add_argument("--body", help="body text; '-' or omitted reads from stdin")
    sp.add_argument("--project", help="default: the current project directory name")
    sp.add_argument("--tags", help="comma-separated")
    sp.add_argument("--force", action="store_true", help="ignore secret warnings")
    add_json(sp)
    sp.set_defaults(func=cmd_research)

    sp = sub.add_parser("config", help="show or change the [obsidian] settings")
    sp.add_argument("key", nargs="?", choices=list(CONFIG_KEYS))
    sp.add_argument("value", nargs="?")
    sp.set_defaults(func=cmd_config)

    sp = sub.add_parser(
        "install-mcp",
        help="register the MCP server with Claude Desktop / Cowork",
    )
    sp.add_argument("--config", help="path to the host's JSON config (default: Claude Desktop)")
    sp.add_argument("--force", action="store_true", help="overwrite an existing registration")
    sp.set_defaults(func=cmd_install_mcp)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        preflight.check(scope_mod.state_path())
    except preflight.PreflightError as exc:
        die(str(exc))

    try:
        return int(args.func(args))
    except FileNotFoundError as exc:
        die(str(exc))
    except KeyboardInterrupt:  # pragma: no cover
        return 130
    raise AssertionError  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
