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

from . import __version__, preflight, safety, store
from . import scope as scope_mod
from .scope import CATEGORIES, STATUSES, Scope
from .search import search as run_search
from .store import Entry, connect

UTC = timezone.utc

SNIPPET_LEN = 150
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOT_FOUND = 2

IMPORT_LINE = "@.knowledge/dejavu-triggers.md"
GITIGNORE_LINES = [".knowledge/knowledge.db", ".knowledge/knowledge.db-*"]


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
    if entry.scope == "user":
        bits.append("[user]")
    if stale:
        bits.append(f"[STALE: {stale} days since last check]")

    lines = [f"{mark} [{entry.uid}] {entry.title} {' '.join(bits)}"]
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
    kdir = root / scope_mod.KNOWLEDGE_DIR
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
    return EXIT_OK


def cmd_search(args: argparse.Namespace) -> int:
    scopes = scope_mod.resolve_read(args.scope)
    results = run_search(
        scopes,
        args.query,
        category=args.category,
        since=_parse_since(args.since),
        limit=args.limit,
    )

    if args.json:
        print(
            json.dumps(
                [
                    _entry_dict(hit.entry, sc)
                    | {"score": round(hit.score, 3), "tiers": hit.tiers}
                    for hit, sc in results
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_OK if results else EXIT_NOT_FOUND

    if not results:
        print(f"No results for {args.query!r}")
        return EXIT_NOT_FOUND

    print()
    for hit, sc in results:
        print(_render(hit.entry, sc, full=args.full))
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dejavu",
        description="A local knowledge base that lets Claude Code pick up where it left off.",
    )
    p.add_argument("--version", action="version", version=f"dejavu {__version__}")
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
