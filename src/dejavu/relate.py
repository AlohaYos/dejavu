"""Cross-links between vault notes, written at the moment a note is written.

Why at write time
-----------------
A nightly script that links notes is a script whose output nobody watches. Links matter
while the note is still warm — when the thought that produced it is still in the room. So
the only trigger is dejavu's own write path: `create_note` and `append_to_note`, and
nothing else. There is no daemon, no file watcher, no cron.

Two things this module must never do
------------------------------------
**Never loop.** Writing a link changes the note, which changes its mtime, which makes the
indexer re-read it. If linking were driven by indexing, that would be a cycle. It is not:
`apply_*` is called from the write commands and never from `index_markdown_tree`.

**Never damage a note.** Every guard from `obsidian.py` still applies — no `source:
dejavu` marker, no write. On an append-only vault, links are appended below a horizontal
rule and never spliced into a body. And when the candidates cannot be worked out at all,
the note is still saved: linking is best-effort, always.

Choosing what to link to
------------------------
There are two strategies. `search` reuses the same three-tier search the rest of dejavu
uses (FTS5 → keywords → LIKE); it matches words, not meaning, and needs nothing installed.
`embed` asks a local Ollama for an embedding and compares vectors, which is what makes
"these two notes are about the same thing, in different words" work.

`embed` degrades to `search` whenever Ollama cannot be reached — not as a fallback bolted
on afterwards, but as the designed behaviour. dejavu's promise is that it works offline
with zero dependencies; a note must never fail to save because a model server is down.

Talking to Ollama uses `urllib` and nothing else. The zero-dependency rule is not
negotiable: it is what keeps the Homebrew formula free of `resource` blocks.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from array import array
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import obsidian, search
from . import scope as scope_mod

RELATED_HEADING = "## Related"

# Defined here rather than in `link.py` because `strip_related_block` has to recognise it
# and `link` imports `relate`, not the other way round.
LINK_BLOCK_START = "<!-- dejavu:links -->"

# A hit that only the LIKE tier found shares a substring and nothing else — the kind of
# accident that links every note containing "Swift" to every other one. Those are dropped,
# *except* when the query itself is short enough that LIKE is the only tier that can fire.
# Two-character Japanese words (検索 / 認証 / 実装 / 設計) live in that exception, and it
# exists so that dropping noise never quietly drops Japanese.
WEAK_TIERS = frozenset({"like"})

# How many hits to ask the index for before filtering. Filtering drops self-links,
# already-linked notes and low scores, so the pool has to be wider than top_k.
SEARCH_POOL = 20

# Bump when a change here would produce a different vector for identical text — a new
# truncation length, a different way of stripping code. Vectors are skipped when their
# text_hash is unchanged, so without this an upgraded dejavu would keep comparing against
# vectors built by the previous version's rules. Same reasoning as `INDEX_VERSION`.
EMBED_VERSION = 1

# Long enough to hold a real note, short enough to stay well inside bge-m3's window.
MAX_EMBED_CHARS = 6000

# The write path gets three seconds. Past that, waiting costs the user more than the link
# is worth, and the note is already safely on disk. Backfill is not interactive and can
# afford to wait out a cold model load.
WRITE_TIMEOUT = 3.0
BACKFILL_TIMEOUT = 60.0

# Ollama's newer endpoint takes a list and returns a list; the older one takes a single
# prompt. Both are tried so that dejavu works on whatever version is already installed.
EMBED_PATH = "/api/embed"
LEGACY_EMBED_PATH = "/api/embeddings"

UTC = timezone.utc

_HEADING_RE = re.compile(rf"^{re.escape(RELATED_HEADING)}\s*$", re.MULTILINE)
_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
_FENCE_RE = re.compile(r"^```", re.MULTILINE)


@dataclass(frozen=True)
class Candidate:
    title: str
    rel_path: str  # vault-relative, e.g. "Knowledge/foo.md"
    score: float

    @property
    def stem(self) -> str:
        return Path(self.rel_path).stem


# ---------------------------------------------------------------- reading a note


def has_related_block(text: str) -> bool:
    """Only the heading counts.

    The horizontal rule above it is decoration; a user who deletes it has not deleted the
    section, and treating that as "no section yet" would append a second one.
    """
    return _HEADING_RE.search(text) is not None


def strip_related_block(body: str) -> str:
    """Remove dejavu's own section, including the rule that introduces it.

    Left in place, the links would feed back into the next query and the section would
    slowly start linking to whatever it already links to.
    """
    match = _HEADING_RE.search(body)
    if match is None:
        return body
    head = body[: match.start()].rstrip()
    # The bulk linker fences its section in HTML comments; the opening one sits just above
    # the heading. Leaving it behind would make the same note hash differently depending on
    # which part of dejavu last looked at it, and every look would re-embed it.
    if head.endswith(LINK_BLOCK_START):
        head = head[: -len(LINK_BLOCK_START)].rstrip()
    if head.endswith("\n---") or head == "---":
        head = head[: -len("---")].rstrip()
    return head + "\n"


def linked_targets(text: str) -> set[str]:
    """Every `[[target]]` already present, lowercased and stripped of any folder."""
    return {Path(m.group(1).strip()).name.lower() for m in _WIKILINK_RE.finditer(text)}


def _drop_code(body: str) -> str:
    """Fenced code is removed before it becomes a query.

    Identifiers repeat across unrelated notes, and a query built from them links every
    Swift note to every other Swift note.
    """
    parts = _FENCE_RE.split(body)
    return "\n".join(parts[::2])


def query_for(title: str, keywords: list[str] | None, body: str) -> str:
    """The words a note is about. Body text is deliberately left out.

    The LIKE tier matches substrings, so feeding it a whole body would match on stray
    particles and punctuation. Title and tags are what the author already distilled.
    """
    words = [title, *(keywords or [])]
    if not keywords:
        # Nothing was tagged, so fall back to the first line of prose for some signal.
        first = next((ln.strip() for ln in _drop_code(body).splitlines() if ln.strip()), "")
        words.append(first[:120])
    return " ".join(w for w in words if w)


# ---------------------------------------------------------------- remembering the outage

# Tables that hold what dejavu learned about its own failures. They live beside the vault
# index because they are worthless without it: throw obsidian.db away and both the index
# and these are rebuilt from the Markdown, which is the only thing that was ever the truth.
STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS relate_state (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_relate (
  uid       TEXT PRIMARY KEY,
  rel_path  TEXT NOT NULL,
  reason    TEXT NOT NULL,
  queued_at TEXT NOT NULL,
  attempts  INTEGER NOT NULL DEFAULT 0
);
"""

# How long to believe an outage without checking again. Short enough that someone who
# starts Ollama and comes back does not wait, long enough that a run of writes during an
# outage costs one timeout rather than one per note.
DOWN_FOR = 60.0

# A note that fails this many times is not going to start working. Leaving it to retry
# forever would make the queue permanently non-empty, which is the same as having no
# signal at all.
MAX_ATTEMPTS = 5

# Notes drained during an ordinary write. The point is to catch up without anyone noticing;
# draining hundreds here would turn a save into a wait.
DRAIN_ON_WRITE = 5


def _ensure(con) -> None:
    """Every table this module owns, created on whichever connection is already open."""
    obsidian.ensure_vectors(con)
    con.executescript(STATE_SCHEMA)


def _open_state():
    from .store import connect

    con = connect(scope_mod.obsidian_scope())
    _ensure(con)
    return con


def _get(con, key: str) -> str | None:
    row = con.execute("SELECT value FROM relate_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _set(con, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO relate_state(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def known_down(cfg) -> str | None:
    """The reason Ollama is believed to be down, or None. Never makes a network call."""
    scope = scope_mod.obsidian_scope()
    if not scope.db_path.exists():
        return None
    con = _open_state()
    try:
        until = _get(con, "unreachable_until")
        if until is None:
            return None
        if datetime.now(UTC) >= datetime.fromisoformat(until):
            return None
        return _get(con, "unreachable_reason") or "not reachable"
    except ValueError:  # pragma: no cover - a hand-edited timestamp
        return None
    finally:
        con.close()


def mark_down(cfg, reason: str) -> None:
    con = _open_state()
    try:
        until = datetime.now(UTC) + timedelta(seconds=DOWN_FOR)
        _set(con, "unreachable_until", until.isoformat())
        _set(con, "unreachable_reason", reason)
        con.commit()
    finally:
        con.close()


def clear_down(cfg) -> None:
    """Forget the outage. Called on success, and the moment the user asks for a start.

    Missing the second case would mean saying yes to "start it?" and then watching nothing
    happen for a minute, which is the most foolish way this could fail.
    """
    con = _open_state()
    try:
        con.execute(
            "DELETE FROM relate_state WHERE key IN ('unreachable_until', 'unreachable_reason')"
        )
        con.commit()
    finally:
        con.close()


def consent(cfg) -> str:
    """`ask` / `always` / `never`, with a refusal remembered from a previous run."""
    if cfg.relate_autostart != "ask":
        return cfg.relate_autostart
    scope = scope_mod.obsidian_scope()
    if not scope.db_path.exists():
        return "ask"
    con = _open_state()
    try:
        return "never" if _get(con, "autostart_refused") else "ask"
    finally:
        con.close()


def remember_refusal(cfg) -> None:
    """Being asked once is a question. Being asked every time is a reason to give up."""
    con = _open_state()
    try:
        _set(con, "autostart_refused", datetime.now(UTC).isoformat())
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------- the repair queue


def _queue(con, uid: str, rel_path: str, reason: str) -> None:
    con.execute(
        """INSERT INTO pending_relate(uid, rel_path, reason, queued_at, attempts)
                VALUES (?, ?, ?, ?, 1)
           ON CONFLICT(uid) DO UPDATE SET
                reason = excluded.reason, attempts = pending_relate.attempts + 1""",
        (uid, rel_path, reason, datetime.now(UTC).isoformat()),
    )


def _unqueue(con, uid: str) -> None:
    con.execute("DELETE FROM pending_relate WHERE uid = ?", (uid,))


def pending(cfg) -> list[dict]:
    """Notes still waiting for a working model, oldest first."""
    scope = scope_mod.obsidian_scope()
    if not scope.db_path.exists():
        return []
    con = _open_state()
    try:
        return [
            dict(row)
            for row in con.execute(
                "SELECT uid, rel_path, reason, queued_at, attempts FROM pending_relate "
                "ORDER BY queued_at"
            ).fetchall()
        ]
    finally:
        con.close()


def drain(cfg, *, limit: int | None = None, progress=None) -> tuple[int, int]:
    """Work through the queue. Returns (resolved, failed).

    Only ever called once a request has already succeeded, so a failure here means
    something new went wrong rather than that the outage is still going.
    """
    if cfg.relate != "embed" or cfg.vault is None:
        return 0, 0
    waiting = pending(cfg)
    if not waiting:
        return 0, 0
    if limit is not None:
        waiting = waiting[:limit]

    # Two passes, and the order is the point. Linking a note as soon as its own vector
    # exists would compare it against a half-filled table: the first note out of the queue
    # could never see the second. Every vector is stored first, and only then is anything
    # linked.
    ready: list = []
    failed = 0
    for index, row in enumerate(waiting, start=1):
        if progress is not None:
            progress(index, len(waiting))
        path = cfg.vault / row["rel_path"]
        if remember(cfg, path, vault=cfg.vault) != "stored":
            failed += 1
            if row["attempts"] >= MAX_ATTEMPTS:
                con = _open_state()
                try:
                    _unqueue(con, row["uid"])
                    con.commit()
                finally:
                    con.close()
            continue
        ready.append(path)

    # The vectors are the durable half and are already saved. A note that cannot take
    # links (an append-only vault whose section is already there) simply keeps the ones
    # it has.
    mode, _ = obsidian.effective_write_mode(cfg.vault, cfg.write_mode)
    for path in ready:
        apply_to_existing(cfg, path, vault=cfg.vault, mode=mode)
    return len(ready), failed


def expire_deferred(cfg) -> int:
    """Give up waiting on notes queued too long ago and link them by words instead.

    Deferring is a bet that Ollama comes back. When it does not, an unlinked note forever
    is worse than an imperfectly linked one, so the bet has a deadline.
    """
    if cfg.relate != "embed" or cfg.vault is None:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=cfg.relate_defer_days)
    stale = [row for row in pending(cfg) if _queued_before(row["queued_at"], cutoff)]
    if not stale:
        return 0

    words = replace(cfg, relate="search")
    mode, _ = obsidian.effective_write_mode(cfg.vault, cfg.write_mode)
    done = 0
    for row in stale:
        apply_to_existing(words, cfg.vault / row["rel_path"], vault=cfg.vault, mode=mode)
        done += 1
    return done


def _queued_before(stamp: str, cutoff: datetime) -> bool:
    try:
        return datetime.fromisoformat(stamp) < cutoff
    except ValueError:  # pragma: no cover
        return False


# ---------------------------------------------------------------- starting it up


@dataclass(frozen=True)
class Install:
    """How Ollama got onto this machine, which decides how it is started."""

    method: str  # "app" | "brew" | "none"
    command: list[str]
    permanent: bool = False  # does starting it this way survive a reboot?

    @property
    def found(self) -> bool:
        return self.method != "none"


APP_PATH = Path("/Applications/Ollama.app")


def detect_install(*, home: Path | None = None) -> Install:
    """Prefer the app: starting it is a one-off that macOS supervises.

    `brew services` writes a launch agent, so it silently turns "start it now" into "start
    it at every login" — a larger promise than the user was asked for.
    """
    app = (home / "Applications/Ollama.app") if home else APP_PATH
    if app.exists() or (home is None and APP_PATH.exists()):
        return Install("app", ["open", "-ga", "Ollama"])
    if shutil.which("ollama") and shutil.which("brew"):
        return Install("brew", ["brew", "services", "start", "ollama"], permanent=True)
    return Install("none", [])


def wait_until_ready(cfg, *, progress=None, port_timeout: float = 15.0) -> None:
    """Wait for the port, then for the model. Raises OllamaUnavailable if either gives up.

    Waiting for the port alone is not enough: the server answers long before a 1.2GB model
    is in memory, so skipping the warm-up just moves the timeout to the user's next note.
    """
    deadline = time.monotonic() + port_timeout
    while True:
        try:
            _post(cfg.relate_host.rstrip("/") + "/api/tags", {}, 2.0)
            break
        except OSError:
            pass
        except Exception:  # noqa: BLE001 - any answer at all means the port is open
            break
        if time.monotonic() >= deadline:
            raise OllamaUnavailable("it did not start in time")
        if progress is not None:
            progress("port")
        time.sleep(0.5)

    if progress is not None:
        progress("model")
    embed(
        ["warm"],
        model=cfg.relate_model,
        host=cfg.relate_host,
        timeout=BACKFILL_TIMEOUT,
        keep_alive=cfg.relate_keep_alive,
    )


def start(cfg, *, progress=None) -> Install:
    """Launch Ollama and wait until it can actually answer. Raises OllamaUnavailable.

    Never called without consent — see `consent()`. dejavu starts it; dejavu never stops
    it, because telling apart "I started this" from "it was already running" across
    processes is not worth getting wrong on someone else's machine.
    """
    clear_down(cfg)
    install = detect_install()
    if not install.found:
        raise OllamaUnavailable("the program that reads your notes is not installed")
    try:
        subprocess.run(install.command, check=True, capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        raise OllamaUnavailable(f"it could not be started ({exc})") from exc
    wait_until_ready(cfg, progress=progress)
    return install


# ---------------------------------------------------------------- embeddings


class OllamaUnavailable(RuntimeError):
    """Ollama could not be reached, or could not answer. Never fatal."""


def embed_text_for(title: str, body: str) -> str:
    """The text a note is represented by.

    Everything dejavu itself wrote is removed first. Left in, the links would be part of
    what the note "means", and each round of linking would nudge the vector towards the
    notes it already links to — a drift that would take months to notice.
    """
    clean = _drop_code(strip_related_block(body)).strip()
    return f"{title}\n\n{clean}"[:MAX_EMBED_CHARS]


def text_hash(text: str) -> str:
    """Identifies the *embedded* text, not the file.

    Writing links changes the file's mtime but not its meaning, so hashing the file would
    make every link write look like a reason to call the model again.
    """
    seed = f"{EMBED_VERSION}\n{text}"
    return hashlib.blake2b(seed.encode("utf-8"), digest_size=8).hexdigest()


def _post(url: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _normalize(values: list[float]) -> array:
    total = sum(v * v for v in values) ** 0.5
    if total == 0:  # pragma: no cover - a zero vector would mean the model failed
        raise OllamaUnavailable("the model returned an empty vector")
    return array("f", [v / total for v in values])


def embed(
    texts: list[str], *, model: str, host: str, timeout: float, keep_alive: str = ""
) -> list[array]:
    """Ask Ollama for L2-normalised embeddings. Raises OllamaUnavailable, never returns junk.

    Normalising here means every later comparison is a plain dot product, which keeps the
    hot loop free of square roots.

    `keep_alive` travels in the request body rather than in `OLLAMA_KEEP_ALIVE`. Ollama
    unloads a model five minutes after its last use, and reloading 1.2GB takes longer than
    the write path is willing to wait — but fixing that through the environment would mean
    writing a launch agent or an exported variable onto the user's machine, and a change
    left behind is a change someone has to be told how to undo. Per request, it affects
    exactly the calls dejavu makes and nothing else on the system.
    """
    base = host.rstrip("/")
    payload: dict = {"model": model, "input": texts}
    if keep_alive:
        payload["keep_alive"] = keep_alive
    try:
        data = _post(base + EMBED_PATH, payload, timeout)
        raw = data.get("embeddings")
        if not raw:
            raise OllamaUnavailable(f"{model} returned no embeddings")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise OllamaUnavailable(f"Ollama replied {exc.code}") from exc
        # An Ollama old enough not to know /api/embed. One text per request.
        try:
            raw = [
                _post(base + LEGACY_EMBED_PATH, {"model": model, "prompt": t}, timeout)["embedding"]
                for t in texts
            ]
        except (urllib.error.URLError, OSError, ValueError, KeyError) as legacy:
            raise OllamaUnavailable(str(legacy)) from legacy
    except urllib.error.URLError as exc:
        raise OllamaUnavailable(f"cannot reach Ollama at {host} ({exc.reason})") from exc
    except (OSError, ValueError) as exc:
        raise OllamaUnavailable(str(exc)) from exc

    if len(raw) != len(texts):
        raise OllamaUnavailable("Ollama returned a different number of vectors than asked for")
    return [_normalize(vec) for vec in raw]


def reachable(cfg) -> tuple[bool, str]:
    """Used by `doctor`. Answers the question the user actually has: why no links?"""
    try:
        embed(["ping"], model=cfg.relate_model, host=cfg.relate_host, timeout=WRITE_TIMEOUT)
    except OllamaUnavailable as exc:
        return False, str(exc)
    return True, f"reachable at {cfg.relate_host}"


# The vector for the note that was just embedded. `suggest_for_new` runs before the file
# exists, so there is no uid to file it under yet; `remember` picks it up a moment later
# once the note is on disk. One process, one entry — this is a relay, not a cache.
_LAST: tuple[str, array] | None = None


def _embed_one(
    cfg,
    text: str,
    *,
    timeout: float = WRITE_TIMEOUT,
    trust_state: bool = True,
    record_state: bool = True,
) -> array:
    """Embed one text, refusing instantly when Ollama is known to be down.

    Without that check, every write during an outage pays the full connection timeout for
    an answer already known. The write path is meant to be unnoticeable.

    `record_state` exists for callers that already hold a write transaction on the same
    database — writing the outage flag from inside one would deadlock against it.
    """
    global _LAST
    digest = text_hash(text)
    if _LAST is not None and _LAST[0] == digest:
        return _LAST[1]
    if trust_state and (reason := known_down(cfg)):
        raise OllamaUnavailable(reason)
    try:
        vec = embed(
            [text],
            model=cfg.relate_model,
            host=cfg.relate_host,
            timeout=timeout,
            keep_alive=cfg.relate_keep_alive,
        )[0]
    except OllamaUnavailable as exc:
        if record_state:
            mark_down(cfg, str(exc))
        raise
    if record_state:
        clear_down(cfg)
    _LAST = (digest, vec)
    return vec


def _store_vector(
    con, uid: str, model: str, digest: str, vec: array, *, origin: str = "index"
) -> None:
    con.execute(
        """INSERT INTO vectors(uid, model, dim, text_hash, vec, created_at, origin)
                VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(uid) DO UPDATE SET
                model = excluded.model, dim = excluded.dim,
                text_hash = excluded.text_hash, vec = excluded.vec,
                created_at = excluded.created_at, origin = excluded.origin""",
        (uid, model, len(vec), digest, vec.tobytes(), datetime.now(UTC).isoformat(), origin),
    )


def _load_vector(blob: bytes) -> array:
    vec = array("f")
    vec.frombytes(blob)
    return vec


def remember(cfg, path: Path, *, vault: Path) -> str:
    """Store the embedding of a note that was just written.

    Returns "stored", "deferred", or "skipped". Without this, notes written today would
    never become candidates for notes written tomorrow until someone remembered to run a
    backfill — and the damage from that is invisible at the time it is done.
    """
    if cfg.relate != "embed":
        return "skipped"
    try:
        text = path.read_text(encoding="utf-8")
        rel_path = path.relative_to(vault).as_posix()
    except (OSError, ValueError):
        return "skipped"

    raw, body = obsidian.split_frontmatter(text)
    title, clean = obsidian.split_title(strip_related_block(body), path)
    material = embed_text_for(title, clean)
    if len(material.strip()) < cfg.relate_min_chars:
        return "skipped"

    from .store import connect

    scope = scope_mod.obsidian_scope()
    con = connect(scope)
    try:
        _ensure(con)
        digest = text_hash(material)
        uid = obsidian.stable_uid(rel_path)
        row = con.execute("SELECT text_hash FROM vectors WHERE uid = ?", (uid,)).fetchone()
        if row is not None and row["text_hash"] == digest:
            return "stored"
        try:
            vec = _embed_one(cfg, material)
        except OllamaUnavailable:
            _queue(con, uid, rel_path, "ollama-down")
            con.commit()
            return "deferred"
        _store_vector(con, uid, cfg.relate_model, digest, vec)
        _unqueue(con, uid)
        con.commit()
    finally:
        con.close()
    return "stored"


def vector_counts(cfg) -> tuple[int, int]:
    """(notes with a vector, notes indexed). What `doctor` needs to explain itself."""
    from .store import connect

    scope = scope_mod.obsidian_scope()
    if not scope.db_path.exists():
        return 0, 0
    con = connect(scope)
    try:
        _ensure(con)
        notes = con.execute("SELECT COUNT(*) FROM entries WHERE storage = 'obsidian'").fetchone()[0]
        embedded = con.execute(
            """SELECT COUNT(*) FROM vectors v JOIN entries e ON e.uid = v.uid
                WHERE e.storage = 'obsidian' AND v.model = ?""",
            (cfg.relate_model,),
        ).fetchone()[0]
        return int(embedded), int(notes)
    finally:
        con.close()


def backfill(cfg, *, rebuild: bool = False, batch: int = 8, progress=None) -> tuple[int, int]:
    """Embed every indexed note that does not have a current vector.

    Returns (embedded, total). Committed batch by batch so that Ctrl-C keeps everything
    done so far — a first run over a large vault is minutes long, and a run that has to
    start over from zero is a run nobody finishes.
    """
    from .store import connect

    scope = scope_mod.obsidian_scope()
    if not scope.db_path.exists() or cfg.vault is None:
        return 0, 0

    con = connect(scope)
    try:
        _ensure(con)
        if rebuild:
            con.execute("DELETE FROM vectors")
            con.commit()

        rows = con.execute(
            """SELECT e.uid, e.title, e.source_path, v.text_hash
                 FROM entries e LEFT JOIN vectors v ON v.uid = e.uid
                WHERE e.storage = 'obsidian'"""
        ).fetchall()

        pending: list[tuple[str, str, str]] = []  # (uid, digest, text)
        for row in rows:
            path = cfg.vault / row["source_path"]
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            _, body = obsidian.split_frontmatter(text)
            material = embed_text_for(row["title"], strip_related_block(body))
            if len(material.strip()) < cfg.relate_min_chars:
                continue
            digest = text_hash(material)
            if row["text_hash"] == digest:
                continue
            pending.append((row["uid"], digest, material))

        done = 0
        for start in range(0, len(pending), batch):
            chunk = pending[start : start + batch]
            vectors = embed(
                [text for _, _, text in chunk],
                model=cfg.relate_model,
                host=cfg.relate_host,
                timeout=BACKFILL_TIMEOUT,
            )
            for (uid, digest, _), vec in zip(chunk, vectors, strict=True):
                _store_vector(con, uid, cfg.relate_model, digest, vec)
            con.commit()
            done += len(chunk)
            if progress is not None:
                progress(done, len(pending))
        return done, len(rows)
    finally:
        con.close()


# ---------------------------------------------------------------- choosing links


def _by_vector(
    cfg,
    *,
    title: str,
    body: str,
    exclude_paths: set[str],
    exclude_targets: set[str],
) -> list[Candidate]:
    """Nearest notes by embedding. Raises OllamaUnavailable so the caller can degrade."""
    from .store import connect

    material = embed_text_for(title, body)
    scope = scope_mod.obsidian_scope()
    con = connect(scope)
    try:
        _ensure(con)
        rows = con.execute(
            """SELECT e.title, e.source_path, v.vec, v.dim
                 FROM vectors v JOIN entries e ON e.uid = v.uid
                WHERE e.storage = 'obsidian' AND e.source_path IS NOT NULL"""
        ).fetchall()
    finally:
        con.close()
    if not rows:
        return []

    mine = _embed_one(cfg, material)
    scored: list[Candidate] = []
    for row in rows:
        if row["dim"] != len(mine):
            continue  # a vector from another model; the next backfill replaces it
        if row["source_path"] in exclude_paths:
            continue
        if Path(row["source_path"]).stem.lower() in exclude_targets:
            continue
        other = _load_vector(row["vec"])
        similarity = sum(a * b for a, b in zip(mine, other, strict=False))
        if similarity < cfg.relate_min_sim:
            continue
        scored.append(Candidate(title=row["title"], rel_path=row["source_path"], score=similarity))
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[: cfg.relate_top_k]


def _candidates(
    cfg,
    *,
    title: str,
    keywords: list[str] | None,
    body: str,
    exclude_paths: set[str],
    exclude_targets: set[str],
) -> list[Candidate]:
    if cfg.relate == "off":
        return []

    scope = scope_mod.obsidian_scope()
    if not scope.db_path.exists():
        return []

    if cfg.relate == "embed":
        try:
            return _by_vector(
                cfg,
                title=title,
                body=body,
                exclude_paths=exclude_paths,
                exclude_targets=exclude_targets,
            )
        except OllamaUnavailable:
            # Deliberately no fallback to words here. Someone who chose `embed` paid for
            # links that follow meaning; quietly writing a different kind instead would be
            # bad enough on its own, and on a synced vault those links can never be
            # corrected afterwards. So the note is saved now and linked once the model is
            # back — `remember` puts it in the queue, and `relate_defer_days` is the
            # deadline after which words are used rather than leaving it unlinked forever.
            return []

    query = query_for(title, keywords, body)
    needs_like = any(len(t) < search.MIN_TRIGRAM_LEN for t in query.split())

    hits = search.search([scope], query, limit=SEARCH_POOL)
    out: list[Candidate] = []
    for hit, _ in hits:
        rel_path = hit.entry.source_path
        if not rel_path or rel_path in exclude_paths:
            continue
        if Path(rel_path).stem.lower() in exclude_targets:
            continue
        if not needs_like and set(hit.tiers) <= WEAK_TIERS:
            continue
        out.append(Candidate(title=hit.entry.title, rel_path=rel_path, score=hit.score))
        if len(out) >= cfg.relate_top_k:
            break
    return out


def _ambiguous_stems(scope) -> set[str]:
    """Stems that appear more than once in the vault.

    Obsidian resolves `[[name]]` by filename, so a duplicated filename makes a bare link
    point somewhere arbitrary. Those get a folder prefix instead.
    """
    from .store import connect

    if not scope.db_path.exists():
        return set()
    con = connect(scope)
    try:
        seen: set[str] = set()
        twice: set[str] = set()
        for row in con.execute("SELECT source_path FROM entries WHERE source_path IS NOT NULL"):
            stem = Path(row["source_path"]).stem.lower()
            (twice if stem in seen else seen).add(stem)
        return twice
    finally:
        con.close()


def format_links(candidates: list[Candidate], *, ambiguous: set[str]) -> list[str]:
    links = []
    for cand in candidates:
        target = (
            Path(cand.rel_path).with_suffix("").as_posix()
            if cand.stem.lower() in ambiguous
            else cand.stem
        )
        label = f"{target}|{cand.title}" if cand.title and cand.title != cand.stem else target
        links.append(f"[[{label}]]")
    return links


def render_block(links: list[str]) -> str:
    """The section appended to a note whose body cannot be rewritten.

    The horizontal rule is the point: without it, `## Related` reads as one more section
    the author wrote.
    """
    body = "\n".join(f"- {link}" for link in links)
    return f"---\n\n{RELATED_HEADING}\n\n{body}"


def catch_up(cfg) -> tuple[int, int]:
    """Called after a write. Clears a little of the queue, and enforces the deadline.

    Draining here is what makes the queue self-healing: the user starts Ollama for their
    own reasons, and the backlog quietly disappears over the next few notes without anyone
    running a command.
    """
    if cfg.relate != "embed":
        return 0, 0
    expired = expire_deferred(cfg)
    if known_down(cfg):
        return 0, expired
    resolved, _ = drain(cfg, limit=DRAIN_ON_WRITE)
    return resolved, expired


# ---------------------------------------------------------------- the two entry points


def suggest_for_new(
    cfg,
    *,
    title: str,
    body: str,
    keywords: list[str] | None = None,
) -> list[str]:
    """Links for a note that does not exist yet. Returned, not written.

    `create_note` puts them straight into the frontmatter it is already building, so a
    new note costs one file write no matter what the vault's write mode is.
    """
    if cfg.relate == "off" or len(body.strip()) < cfg.relate_min_chars:
        return []
    cands = _candidates(
        cfg,
        title=title,
        keywords=keywords,
        body=body,
        exclude_paths=set(),
        exclude_targets=linked_targets(body),
    )
    return format_links(cands, ambiguous=_ambiguous_stems(scope_mod.obsidian_scope()))


def apply_to_existing(cfg, path: Path, *, vault: Path, mode: str) -> list[str]:
    """Link a note that is already on disk. Returns the links written, or [].

    Every reason to do nothing returns quietly. A failure to link is not a failure to
    save, and this runs *after* the user's content is already safely on disk.
    """
    if cfg.relate == "off":
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    if not obsidian.is_dejavu_note(text):
        return []
    if mode != "full" and has_related_block(text):
        # Appending is the only tool available here, and the section is already there.
        # A second one is worse than a stale one.
        return []

    raw, body = obsidian.split_frontmatter(text)
    fields = obsidian.parse_frontmatter(raw)
    tags = fields.get("tags")
    keywords = [str(t).lstrip("#") for t in tags] if isinstance(tags, list) else None
    clean = strip_related_block(body)
    if len(clean.strip()) < cfg.relate_min_chars:
        return []

    title, clean_body = obsidian.split_title(clean, path)
    try:
        rel_path = path.relative_to(vault).as_posix()
    except ValueError:  # pragma: no cover - callers always pass a note inside the vault
        return []

    cands = _candidates(
        cfg,
        title=title,
        keywords=keywords,
        body=clean_body,
        exclude_paths={rel_path},
        exclude_targets=linked_targets(clean),
    )
    if not cands:
        return []
    links = format_links(cands, ambiguous=_ambiguous_stems(scope_mod.obsidian_scope()))

    try:
        if mode == "full":
            obsidian.set_frontmatter_key(path, cfg.relate_key, links, mode=mode)
        else:
            obsidian.append_to_note(path, render_block(links))
    except obsidian.WriteRefused:
        return []
    return links
