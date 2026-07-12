# dejavu

A local knowledge base that lets Claude Code pick up where it left off.

Every new session, Claude re-reads the same modules, re-traces the same functions, and
burns the same tokens rediscovering what it already knew. `dejavu` gives it a persistent
memory so context survives across sessions.

- **Fully local** — SQLite only, no network access
- **Zero dependencies** — pure Python standard library
- **Full-text search that works in Japanese** — FTS5 trigram plus a LIKE fallback
- **Written by the agent, not by you** — Claude searches and stores on its own

## Install

```bash
uv tool install git+ssh://git@github.com/AlohaYos/dejavu@v0.1.0
```

Two commands are installed for the same entry point: `dejavu` and the shorter alias
`deja`. The examples below use `dejavu`; use whichever you prefer.

## Usage

```bash
cd your-project
dejavu init                     # creates .knowledge/ and wires instructions into CLAUDE.md

dejavu add "API rate limit is 100 req/min" --keywords "api,rate-limit"
dejavu search "rate limit"
dejavu list --category context
```

Then just start Claude Code. Following the instructions, it searches the knowledge base
before reading unfamiliar code and stores what it learns as it goes.

The next day, in a fresh session, all you need is:

```
continue from yesterday
```

## Commands

| Command | Description |
| --- | --- |
| `dejavu init [--global]` | Initialise a knowledge base. `--global` installs instructions for every project |
| `dejavu add <title>` | Store knowledge (body via `--body -` on stdin) |
| `dejavu search <query>` | Three-tier full-text search |
| `dejavu list` | List entries (`--stale` for ones that need review) |
| `dejavu show <uid>` | Print an entry in full |
| `dejavu edit <uid>` | Update an entry (`--append` to extend it) |
| `dejavu touch <uid>` | Mark an entry verified without changing it |
| `dejavu rm <uid>` | Delete an entry |
| `dejavu stats` | Counts, category breakdown, stale count |

## The three axes of knowledge

| Axis | Values | Meaning |
| --- | --- | --- |
| Scope | `project` / `user` | Where it can be recalled from |
| Storage | `local` / `shared` | Database only, or Markdown shared via git |
| Category | `context` / `plan` / `decision` / `feature` / `convention` / `note` | What it is for |

## Design principles

- **Recall matters more than storage.** Knowledge you cannot find does not exist, so
  search favours recall over precision
- **Dense, not long.** A bloated entry eats context every time it is recalled — which
  defeats the whole point of the tool
- **Stale knowledge is flagged, never hidden.** Old notes still hold clues; results come
  back marked `⚠ STALE` and the instructions say how to handle them
- **Keep what is loaded every turn small.** The instructions file is triggers only

## Development

```bash
uv tool install --editable .
uv run pytest -v
uv run ruff check .
```

## License

MIT
