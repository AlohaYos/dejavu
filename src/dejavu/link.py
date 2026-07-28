"""Linking notes the user wrote themselves — the one place dejavu edits someone else's file.

Everywhere else, dejavu refuses to touch a note without `source: dejavu` in its
frontmatter. That refusal is the promise that makes the Obsidian integration adoptable at
all: people arrive with vaults holding years of their own writing. This module breaks that
promise on purpose, because the feature it provides cannot exist otherwise — drop a pile
of old notes into a folder, ask for them to be connected, and get back a vault where
related things point at each other.

What makes that acceptable is not the confirmation. A confirmation stops mattering the
instant it is clicked, and the person clicking it is usually not an engineer. What makes it
acceptable is that **every change can be taken back**:

* Added text is fenced in HTML comments, so the exact bytes dejavu wrote are known and can
  be lifted out again without disturbing anything written afterwards.
* Every file is copied, whole, before it is touched — all of them, before the first write,
  so a failure halfway through leaves nothing half-backed-up.
* The manifest records the hash of each file as dejavu left it, so a restore can tell
  "nobody touched this" from "the user has edited it since" and refuse the second case.

The frontmatter is never touched, and `source: dejavu` is never added. Adding it would tell
the rest of dejavu that it wrote these notes, and `append_to_note` and `replace_body` would
begin treating the user's own writing as fair game.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import obsidian, relate
from . import scope as scope_mod

UTC = timezone.utc

BLOCK_START = relate.LINK_BLOCK_START
BLOCK_END = "<!-- /dejavu:links -->"

# The same heading `relate` uses. Two different words for the same thing would leave the
# user wondering which part of the vault produced which section.
HEADING = relate.RELATED_HEADING

_BLOCK_RE = re.compile(re.escape(BLOCK_START) + r".*?" + re.escape(BLOCK_END) + r"\n?", re.DOTALL)

# A note that turns up in more than this share of the results is a table of contents, an
# index, a diary — something general enough to resemble everything. Linking it everywhere
# would bury the connections that mean something.
HUB_SHARE = 0.30
HUB_MIN_NOTES = 10

# Plans go stale: acting on one means writing to files as they were when it was made.
PLAN_TTL_MINUTES = 15

# Markdown does not get big. A run this large means something unexpected is in the folder.
MAX_BACKUP_BYTES = 200 * 1024 * 1024

PLANS_SCHEMA = """
CREATE TABLE IF NOT EXISTS link_plans (
  id         TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  payload    TEXT NOT NULL
);
"""


class LinkRefused(RuntimeError):
    """The run was stopped to protect the user's notes."""


# ---------------------------------------------------------------- the block


def has_block(text: str) -> bool:
    return _BLOCK_RE.search(text) is not None


def strip_block(text: str) -> str:
    """Remove dejavu's block and nothing else, including text added after it."""
    return _BLOCK_RE.sub("", text).rstrip() + "\n"


def render_block(links: list[str]) -> str:
    body = "\n".join(f"- {link}" for link in links)
    return f"{BLOCK_START}\n{HEADING}\n\n{body}\n{BLOCK_END}\n"


def upsert_block(text: str, links: list[str]) -> str:
    """Replace the block if there is one, otherwise append it.

    Replacing rather than appending is what makes a second run over the same folder safe:
    the links change, the file does not grow.
    """
    block = render_block(links)
    if has_block(text):
        return _BLOCK_RE.sub(lambda _: block, text, count=1)
    return text.rstrip() + f"\n\n{block}"


def file_hash(path: Path) -> str:
    return hashlib.blake2b(path.read_bytes(), digest_size=16).hexdigest()


# ---------------------------------------------------------------- backups


def _slug(vault: Path) -> str:
    digest = hashlib.blake2b(str(vault).encode("utf-8"), digest_size=3).hexdigest()
    return f"{obsidian.slugify(vault.name)}-{digest}"


def backup_root(cfg) -> Path:
    """Outside the vault, always.

    A copy kept inside the vault would be synced to every device the user owns and would
    show up in their file browser — a backup that creates the problem it exists to solve.
    """
    return scope_mod.user_home() / "backups" / _slug(cfg.vault)


def runs(cfg) -> list[dict]:
    """Every recorded run, newest first."""
    root = backup_root(cfg)
    if not root.is_dir():
        return []
    found = []
    for entry in sorted(root.iterdir(), reverse=True):
        manifest = entry / "manifest.json"
        if not manifest.is_file():
            continue
        try:
            found.append(json.loads(manifest.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return found


def prune(cfg) -> int:
    """Drop runs that are both old and long superseded. Only ever called before a new run.

    Nothing is deleted in the background. Files disappearing while the user is doing
    something else is unsettling even when the files are backups.
    """
    root = backup_root(cfg)
    if not root.is_dir():
        return 0
    now = datetime.now(UTC)
    keep_days = timedelta(days=cfg.link_keep_days)
    reverted_days = timedelta(days=7)

    removed = 0
    for index, manifest in enumerate(runs(cfg)):
        age = now - _parse_time(manifest["run"])
        recent_enough = index < cfg.link_keep_runs or age < keep_days
        # A run that has been undone has done its job. It is still kept for a week, because
        # "undo that undo" is a thing people want a day or two later.
        if manifest.get("reverted_at") and age > reverted_days:
            recent_enough = False
        if not recent_enough:
            shutil.rmtree(root / manifest["run"], ignore_errors=True)
            removed += 1
    return removed


def _parse_time(run_id: str) -> datetime:
    try:
        return datetime.strptime(run_id[:20], "%Y-%m-%dT%H-%M-%SZ").replace(tzinfo=UTC)
    except ValueError:  # pragma: no cover - only a hand-made directory name
        return datetime.now(UTC)


def _run_id(now: datetime, seed: str) -> str:
    stamp = now.strftime("%Y-%m-%dT%H-%M-%SZ")
    return f"{stamp}-{hashlib.blake2b(seed.encode(), digest_size=2).hexdigest()}"


# ---------------------------------------------------------------- planning


@dataclass
class Plan:
    plan_id: str
    folder: str
    files: list[dict] = field(default_factory=list)  # path, before, links
    renames: list[dict] = field(default_factory=list)
    hubs: list[str] = field(default_factory=list)
    needs_embedding: int = 0
    handwritten: int = 0

    @property
    def link_count(self) -> int:
        return sum(len(f["links"]) for f in self.files)

    def as_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "folder": self.folder,
            "notes": len(self.files),
            "links": self.link_count,
            "handwritten": self.handwritten,
            "renames": self.renames,
            "hubs": self.hubs,
            "needs_embedding": self.needs_embedding,
            "files": [f["path"] for f in self.files],
        }


def _targets(vault: Path, folder: str | None) -> list[Path]:
    root = vault if folder is None else vault / folder
    if not root.is_dir():
        raise LinkRefused(f"{folder or vault} is not a folder in the vault.")
    return list(obsidian.iter_markdown(root))


def _text_of(path: Path) -> tuple[str, str]:
    """Return (title, body without dejavu's own additions).

    For a note dejavu wrote, the leading `# heading` *is* the title — dejavu put it there.
    For everyone else's notes it is just the first heading, and treating it as the title
    goes wrong in two ways at once: a chapter that opens with "Introduction" gets that word
    as its name, and the same word is fed to the model as the note's subject, so every
    document that opens the same way starts to look alike. Obsidian's own convention is
    that the file name is the title, so that is what is used here.
    """
    text = path.read_text(encoding="utf-8")
    _, body = obsidian.split_frontmatter(strip_block(text))
    return obsidian.title_and_body(text, relate.strip_related_block(body), path)


def _vector_for(cfg, con, path: Path, vault: Path) -> tuple[str, object] | None:
    """The note's vector, computed only if it is not already stored."""
    rel_path = path.relative_to(vault).as_posix()
    uid = obsidian.stable_uid(rel_path)
    title, body = _text_of(path)
    material = relate.embed_text_for(title, body)
    if len(material.strip()) < cfg.relate_min_chars:
        return None
    digest = relate.text_hash(material)

    row = con.execute("SELECT text_hash, vec, dim FROM vectors WHERE uid = ?", (uid,)).fetchone()
    if row is not None and row["text_hash"] == digest:
        return uid, relate._load_vector(row["vec"])
    # The caller holds an open write transaction on this database, so neither reading
    # nor writing the outage flag can happen from in here. `plan` checks it once, first.
    vec = relate._embed_one(cfg, material, trust_state=False, record_state=False)
    relate._store_vector(con, uid, cfg.relate_model, digest, vec, origin="link")
    return uid, vec


def _ambiguous_stems(vault: Path, paths: list[Path]) -> set[str]:
    """File names that appear more than once, across the index *and* this run.

    Obsidian resolves `[[name]]` by file name, so a duplicated name makes a bare link point
    somewhere arbitrary. The index alone is not enough to know: the notes being linked here
    are usually outside the indexed folders, which is the whole point of the command.
    """
    from .store import connect

    rels = {p.relative_to(vault).as_posix() for p in paths}
    scope = scope_mod.obsidian_scope()
    if scope.db_path.exists():
        con = connect(scope)
        try:
            for row in con.execute(
                "SELECT source_path FROM entries WHERE source_path IS NOT NULL"
            ):
                rels.add(row["source_path"])
        finally:
            con.close()

    seen: set[str] = set()
    twice: set[str] = set()
    for rel in rels:
        stem = Path(rel).stem.lower()
        (twice if stem in seen else seen).add(stem)
    return twice


def _pairs(vectors: dict[str, object], *, top_k: int, min_sim: float) -> dict[str, set[str]]:
    """Neighbours that each other agree on.

    A one-sided resemblance is usually a note being vague rather than two notes being
    about the same thing, so a link is kept only when it points both ways.
    """
    ranked: dict[str, list[tuple[float, str]]] = {}
    uids = list(vectors)
    for i, a in enumerate(uids):
        va = vectors[a]
        scored = []
        for b in uids[i + 1 :] + uids[:i]:
            similarity = sum(x * y for x, y in zip(va, vectors[b], strict=False))
            if similarity >= min_sim:
                scored.append((similarity, b))
        scored.sort(reverse=True)
        ranked[a] = scored[:top_k]

    mutual: dict[str, set[str]] = {uid: set() for uid in uids}
    for a, neighbours in ranked.items():
        for _, b in neighbours:
            if any(other == a for _, other in ranked.get(b, [])):
                mutual[a].add(b)
                mutual[b].add(a)
    return mutual


def _drop_hubs(mutual: dict[str, set[str]]) -> tuple[dict[str, set[str]], set[str]]:
    total = len(mutual)
    if total < HUB_MIN_NOTES:
        return mutual, set()
    hubs = {uid for uid, links in mutual.items() if len(links) > total * HUB_SHARE}
    if not hubs:
        return mutual, set()
    trimmed = {
        uid: {other for other in links if other not in hubs}
        for uid, links in mutual.items()
        if uid not in hubs
    }
    return trimmed, hubs


def plan(cfg, folder: str | None, *, progress=None) -> Plan:
    """Work out what would change. Writes nothing to the vault."""
    from .store import connect

    if cfg.vault is None:
        raise LinkRefused("No vault is configured.")
    if (reason := relate.known_down(cfg)) is not None:
        raise relate.OllamaUnavailable(reason)
    vault = cfg.vault
    paths = _targets(vault, folder)
    scanned = vault if folder is None else vault / folder
    renames = [
        {
            "from": p.relative_to(vault).as_posix(),
            "to": p.with_suffix(".md").relative_to(vault).as_posix(),
        }
        for p in sorted(scanned.rglob("*.txt"))
        if p.is_file()
    ]
    if not paths:
        return Plan(plan_id="", folder=folder or ".", renames=renames)

    con = connect(scope_mod.obsidian_scope())
    try:
        obsidian.ensure_vectors(con)
        con.executescript(PLANS_SCHEMA)

        known = {
            row["uid"]
            for row in con.execute("SELECT uid FROM vectors WHERE model = ?", (cfg.relate_model,))
        }
        vectors: dict[str, object] = {}
        by_uid: dict[str, Path] = {}
        needed = 0
        for index, path in enumerate(paths, start=1):
            if progress is not None:
                progress(index, len(paths))
            uid = obsidian.stable_uid(path.relative_to(vault).as_posix())
            if uid not in known:
                needed += 1
            found = _vector_for(cfg, con, path, vault)
            if found is None:
                continue
            vectors[found[0]] = found[1]
            by_uid[found[0]] = path
        con.commit()
    finally:
        con.close()

    mutual, hubs = _drop_hubs(_pairs(vectors, top_k=cfg.relate_top_k, min_sim=cfg.relate_min_sim))
    ambiguous = _ambiguous_stems(vault, paths)

    files = []
    handwritten = 0
    for uid, neighbours in sorted(mutual.items(), key=lambda kv: by_uid[kv[0]].name):
        if not neighbours:
            continue
        path = by_uid[uid]
        candidates = [
            relate.Candidate(
                title=_text_of(by_uid[other])[0],
                rel_path=by_uid[other].relative_to(vault).as_posix(),
                score=0.0,
            )
            for other in sorted(neighbours, key=lambda u: by_uid[u].name)
        ]
        links = relate.format_links(candidates, ambiguous=ambiguous)
        text = path.read_text(encoding="utf-8")
        if not obsidian.is_dejavu_note(text):
            handwritten += 1
        files.append(
            {
                "path": path.relative_to(vault).as_posix(),
                "before": file_hash(path),
                "links": links,
            }
        )

    made = Plan(
        plan_id="",
        folder=folder or ".",
        files=files,
        renames=renames,
        hubs=sorted(by_uid[uid].relative_to(vault).as_posix() for uid in hubs),
        needs_embedding=needed,
        handwritten=handwritten,
    )
    return _save_plan(made)


def _save_plan(made: Plan) -> Plan:
    from .store import connect

    now = datetime.now(UTC)
    made.plan_id = _run_id(now, made.folder + str(len(made.files)))[-4:]
    con = connect(scope_mod.obsidian_scope())
    try:
        con.executescript(PLANS_SCHEMA)
        con.execute(
            "INSERT OR REPLACE INTO link_plans(id, created_at, payload) VALUES (?, ?, ?)",
            (
                made.plan_id,
                now.isoformat(),
                json.dumps(
                    {
                        "folder": made.folder,
                        "files": made.files,
                        "renames": made.renames,
                        "hubs": made.hubs,
                        "handwritten": made.handwritten,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        con.commit()
    finally:
        con.close()
    return made


def load_plan(plan_id: str) -> Plan:
    from .store import connect

    con = connect(scope_mod.obsidian_scope())
    try:
        con.executescript(PLANS_SCHEMA)
        row = con.execute(
            "SELECT created_at, payload FROM link_plans WHERE id = ?", (plan_id,)
        ).fetchone()
    finally:
        con.close()
    if row is None:
        raise LinkRefused(f"No plan called {plan_id}. Make a new one.")
    age = datetime.now(UTC) - datetime.fromisoformat(row["created_at"])
    if age > timedelta(minutes=PLAN_TTL_MINUTES):
        # Acting on an old plan means writing to files as they were, not as they are.
        raise LinkRefused("That plan is out of date. Make a new one.")
    data = json.loads(row["payload"])
    return Plan(
        plan_id=plan_id,
        folder=data["folder"],
        files=data["files"],
        renames=data["renames"],
        hubs=data["hubs"],
        handwritten=data["handwritten"],
    )


# ---------------------------------------------------------------- applying


def apply(cfg, plan_id: str, *, convert_txt: bool = True, progress=None) -> dict:
    """Carry out a plan. Every file is copied before any file is written."""
    if cfg.vault is None:
        raise LinkRefused("No vault is configured.")
    made = load_plan(plan_id)
    vault = cfg.vault
    prune(cfg)

    # Files that changed since the plan was made are dropped rather than overwritten with
    # links worked out from text that no longer exists.
    todo, skipped = [], []
    for entry in made.files:
        path = vault / entry["path"]
        if not path.is_file() or file_hash(path) != entry["before"]:
            skipped.append(entry["path"])
            continue
        todo.append((path, entry))

    renames = made.renames if convert_txt else []
    if not todo and not renames:
        return {"run": None, "notes": 0, "links": 0, "skipped": skipped, "renamed": 0}

    now = datetime.now(UTC)
    run_id = _run_id(now, plan_id)
    run_dir = backup_root(cfg) / run_id

    total_bytes = sum(path.stat().st_size for path, _ in todo)
    if total_bytes > MAX_BACKUP_BYTES:
        raise LinkRefused(
            f"That would copy {total_bytes // (1024 * 1024)}MB before writing anything. "
            "Point it at a smaller folder."
        )

    # Phase one: copy everything. A failure here must leave the vault untouched, which it
    # cannot do if copying and writing are interleaved.
    try:
        for path, entry in todo:
            destination = run_dir / entry["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        for rename in renames:
            source = vault / rename["from"]
            if source.is_file():
                destination = run_dir / rename["from"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
    except OSError as exc:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise LinkRefused(f"Nothing was changed: the copies could not be made ({exc}).") from exc

    # Phase two: write.
    records = []
    for index, (path, entry) in enumerate(todo, start=1):
        if progress is not None:
            progress(index, len(todo))
        path.write_text(upsert_block(path.read_text(encoding="utf-8"), entry["links"]), "utf-8")
        records.append(
            {
                "path": entry["path"],
                "before": entry["before"],
                "after": file_hash(path),
                "links_added": entry["links"],
            }
        )

    renamed = []
    for rename in renames:
        source = vault / rename["from"]
        target = vault / rename["to"]
        if source.is_file() and not target.exists():
            source.rename(target)
            renamed.append(rename)

    manifest = {
        "run": run_id,
        "vault": str(vault),
        "command": f"dejavu obsidian link {made.folder}",
        "files": records,
        "renamed": renamed,
        "reverted_at": None,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "run": run_id,
        "notes": len(records),
        "links": sum(len(r["links_added"]) for r in records),
        "handwritten": made.handwritten,
        "skipped": skipped,
        "renamed": len(renamed),
        "backup": str(run_dir),
    }


# ---------------------------------------------------------------- undoing


def _manifest_for(cfg, run_id: str | None) -> dict:
    found = runs(cfg)
    if not found:
        raise LinkRefused("There is nothing to undo.")
    if run_id is None:
        return found[0]
    for manifest in found:
        if manifest["run"] == run_id:
            return manifest
    raise LinkRefused(f"No run called {run_id}.")


def _mark_reverted(cfg, manifest: dict) -> None:
    manifest["reverted_at"] = datetime.now(UTC).isoformat()
    path = backup_root(cfg) / manifest["run"] / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def remove(cfg, run_id: str | None = None) -> dict:
    """Lift out the block dejavu added, leaving everything written since.

    This is the undo people should reach for. Restoring the whole file would also throw
    away anything they wrote after the run.
    """
    manifest = _manifest_for(cfg, run_id)
    vault = cfg.vault
    cleaned, missing = 0, []
    for record in manifest["files"]:
        path = vault / record["path"]
        if not path.is_file():
            missing.append(record["path"])
            continue
        text = path.read_text(encoding="utf-8")
        if not has_block(text):
            missing.append(record["path"])
            continue
        path.write_text(strip_block(text), encoding="utf-8")
        cleaned += 1

    for rename in reversed(manifest.get("renamed", [])):
        target = vault / rename["to"]
        original = vault / rename["from"]
        if target.is_file() and not original.exists():
            target.rename(original)

    _mark_reverted(cfg, manifest)
    return {"run": manifest["run"], "cleaned": cleaned, "untouched": missing}


def restore(cfg, run_id: str | None = None, *, force: bool = False) -> dict:
    """Put the files back exactly as they were. Refuses if they have been edited since."""
    manifest = _manifest_for(cfg, run_id)
    vault = cfg.vault
    run_dir = backup_root(cfg) / manifest["run"]

    edited = []
    for record in manifest["files"]:
        path = vault / record["path"]
        if path.is_file() and file_hash(path) != record["after"]:
            edited.append(record["path"])
    if edited and not force:
        raise LinkRefused(
            f"{len(edited)} of these notes have been edited since. Restoring would discard "
            "those edits — use `--remove` to take out only the links dejavu added, or "
            "`--force` to overwrite anyway.\n  " + "\n  ".join(edited[:5])
        )

    restored = 0
    for record in manifest["files"]:
        copy = run_dir / record["path"]
        if not copy.is_file():
            continue
        (vault / record["path"]).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(copy, vault / record["path"])
        restored += 1

    for rename in reversed(manifest.get("renamed", [])):
        target = vault / rename["to"]
        original = vault / rename["from"]
        if target.is_file() and not original.exists():
            target.rename(original)

    _mark_reverted(cfg, manifest)
    return {"run": manifest["run"], "restored": restored, "edited": edited}
