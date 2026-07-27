# Reference

The detail that was kept out of [README.md](../README.md). You do not need to read this to
use dejavu.

---

## Contents

1. [Command reference](#command-reference)
2. [Where knowledge lives (scopes)](#where-knowledge-lives-scopes)
3. [Configuration](#configuration)
4. [How the write mode is decided](#how-the-write-mode-is-decided)
5. [Note format](#note-format)
6. [Automatic linking between notes (Ollama)](#automatic-linking-between-notes-ollama)
7. [Categories](#categories)
8. [When knowledge goes stale](#when-knowledge-goes-stale)
9. [Credentials are never stored](#credentials-are-never-stored)
10. [Sharing with a team](#sharing-with-a-team)
11. [The MCP server](#the-mcp-server)
12. [Coexisting with Claude's own memory](#coexisting-with-claudes-own-memory)
13. [Using it in Xcode](#using-it-in-xcode)
14. [Troubleshooting](#troubleshooting)

---

## Command reference

Claude runs most of these for you, so you will rarely type one yourself.

### Setup

| Command | Description |
| --- | --- |
| `dejavu init` | Set up the current project |
| `dejavu init --global` | Install the shared instructions into `~/.claude/` (once) |
| `dejavu install-mcp` | Register the MCP server with Claude Desktop / Cowork |
| `dejavu install-mcp --config <path>` | Register with a different host's config file |

`dejavu init` is safe to run repeatedly. It never touches your source, and only *appends*
lines to `CLAUDE.md` and `.gitignore` that are not already there.

> **Re-run `dejavu init` after upgrading.** `dejavu-triggers.md` is copied into each
> project at `init` time, so upgrading the binary leaves old instructions in place.
> `dejavu init --global` does the same for the shared copy.

### Recalling

| Command | Description |
| --- | --- |
| `dejavu resume` | Show the last handoff note |
| `dejavu recent` | Recent work, grouped by day (default: the last 2 days) |
| `dejavu recent --since today` | Today only |
| `dejavu search "<query>"` | Search project, shared and vault together |
| `dejavu search "<query>" --full` | Print full bodies instead of snippets |
| `dejavu search "<query>" --json` | Machine-readable output, with scores and tiers |
| `dejavu list --stale` | Entries that need reviewing |
| `dejavu show <uid>` | Print one entry in full |
| `dejavu stats` | Counts, category breakdown, stale count |

`search` exits with code **2** when there are no results.

### Saving

| Command | Description |
| --- | --- |
| `dejavu add "<title>" --body -` | Store knowledge (body on stdin) |
| `dejavu add ... --category <cat>` | Pick a category (see below) |
| `dejavu add ... --keywords "a,b,c"` | Hand-pick keywords (5–10 is right) |
| `dejavu add ... --status proposed` | `proposed` \| `accepted` \| `done` \| `superseded` |
| `dejavu add ... --scope user` | Store as personal rather than project knowledge |
| `dejavu edit <uid> --append -` | Extend an existing entry |
| `dejavu touch <uid>` | "I checked this and it is still correct" |
| `dejavu rm <uid>` | Delete an entry |

`add` refuses a near-duplicate title. `--force` overrides it, but `edit --append` is
usually the right answer.

### Obsidian

| Command | Description |
| --- | --- |
| `dejavu obsidian init <vault>` | Register a vault, create the folders, index it |
| `dejavu obsidian init <vault> --preset dev` | Also create `API/` `Architecture/` `Patterns/` `Tools/` |
| `dejavu obsidian sync` | Re-read the vault after editing notes yourself |
| `dejavu obsidian doctor` | Vault path, write mode and why, note counts |
| `dejavu obsidian doctor --vault <path>` | Inspect another vault without changing the config |
| `dejavu obsidian add "<title>" --body -` | Write a note into `Knowledge/` |
| `dejavu obsidian add ... --category <name>` | File it in `Knowledge/<name>/` — **only if that folder already exists** |
| `dejavu obsidian add ... --tags "a,b"` | Written to the note's frontmatter |
| `dejavu obsidian add ... --replace` | Replace an existing note's body (refused on a synced vault) |
| `dejavu research "<title>" --body -` | Record under `Research/<project>/<date>-<title>.md` |
| `dejavu research ... --project <name>` | Default: the current directory name |

If a note with the same title exists, `obsidian add` **appends to it** rather than
creating a duplicate.

### Configuration

| Command | Description |
| --- | --- |
| `dejavu config` | Show every setting |
| `dejavu config <key>` | Show one |
| `dejavu config <key> <value>` | Change one and save it |

Add `--help` to any command for its full set of options.

---

## Where knowledge lives (scopes)

| Scope | File | What it holds |
| --- | --- | --- |
| **project** | `<repo>/.dejavu/knowledge.db` | This repository only. Most knowledge |
| **user** | `~/.config/dejavu/knowledge.db` | Cross-project. The fallback when there is no vault |
| **shared** | `<repo>/.dejavu/shared.db` | An index of `docs/knowledge/*.md` (read-only) |
| **obsidian** | `~/.config/dejavu/obsidian.db` | An index of the vault (read-only) |

`shared` and `obsidian` are **indexes, not storage.** The Markdown files are the real
thing; delete either database and `dejavu obsidian sync` rebuilds it.

### What searches what

- `dejavu search` — all four
- `dejavu list` / `recent` / `resume` — **project and user only**

`resume` answers "what was I doing", and hundreds of vault notes would bury that answer.
The omission is deliberate.

### git worktrees

Every worktree shares the **main worktree's** database, with no configuration. A separate
memory per worktree would break the "all worktrees, one knowledge base" guarantee.

---

## Configuration

Project settings live in `<repo>/.dejavu/config.toml`, personal ones in
`~/.config/dejavu/config.toml`. `[obsidian]` is **personal**: a vault belongs to the
machine, not to a repository.

```toml
[stale_days]
context    = 7
plan       = 14
decision   = 30
feature    = 7
convention = 30
note       = 14

[obsidian]
vault         = "~/Documents/MyVault"
include       = ["Knowledge", "UserInfo", "Research"]
knowledge_dir = "Knowledge"
userinfo_dir  = "UserInfo"
research_dir  = "Research"
write_mode    = "auto"       # auto | full | append-only
research      = "findings"   # all | findings | manual
promote       = "ask"        # ask | always | never
```

| Key | Meaning |
| --- | --- |
| `vault` | Path to the vault. **Unset means the integration is entirely off** |
| `include` | Folders that are indexed and written to. Anything else is invisible |
| `knowledge_dir` | Where cross-project knowledge goes |
| `userinfo_dir` | Where your own information goes |
| `research_dir` | Where investigations go (one subfolder per project) |
| `write_mode` | See below |
| `research` | How much of an investigation to keep |
| `promote` | Whether to offer to lift project knowledge into the vault |

### `research` — how much to file

| Value | Behaviour |
| --- | --- |
| `all` | Mirror everything, handoff notes included |
| `findings` | **Reusable discoveries only** (default). Not today's session state |
| `manual` | Only when asked |

To override for one call, put it before the subcommand:

```bash
dejavu --research all resume
```

### `promote` — whether to offer

| Value | Behaviour |
| --- | --- |
| `ask` | Offer a four-way choice when knowledge looks general (default) |
| `always` | Save without asking |
| `never` | Never offer |

`dejavu config promote always` persists it; `ask` puts it back.

---

## How the write mode is decided

A synced vault can be edited on another device while dejavu is writing, and one side
becomes a conflict copy. An append survives that; a rewritten body does not.

With `write_mode = "auto"` (the default):

| Condition | Result |
| --- | --- |
| Vault under `~/Library/Mobile Documents/` | `append-only` (iCloud Drive) |
| Vault under `~/Library/CloudStorage/` | `append-only` (Google Drive / OneDrive / Box) |
| Vault under `~/Dropbox` | `append-only` |
| `<vault>/.obsidian/sync.json` exists | `append-only` (Obsidian Sync) |
| None of the above | `full` |

Even in `full`, the file's modification time is re-checked immediately before a body is
replaced. If it changed since it was read, the write is abandoned rather than trampling
an edit made elsewhere.

`dejavu obsidian doctor` reports the mode and the reason. Setting `write_mode` to `full`
or `append-only` overrides the detection.

---

## Note format

A note dejavu writes looks like this:

```markdown
---
category: pattern
tags: [swiftui, layout]
source: dejavu
project: MyApp
created: 2026-07-27
---

# The ignoresSafeArea trap

safeAreaInsets.bottom reads as 0.
```

| Key | Role |
| --- | --- |
| `source: dejavu` | **dejavu will not write to a note without this.** It is what protects notes you wrote |
| `category` | Classification. Independent of folders, so rearranging later breaks nothing |
| `tags` | Picked up directly by Obsidian's tag pane and Bases |
| `project` | Where the knowledge was learned |
| `created` | Creation date |

**Keys dejavu does not know are left alone.** An `autolink:` list written by an embedding
script survives an append untouched, because frontmatter edits splice individual lines
rather than re-serialising the block.

### Folders

`Knowledge/` starts flat. Create subfolders and dejavu will file notes into them, but it
**never creates one of its own** — vault layouts are personal, and imposing dejavu's
taxonomy on yours would be rude.

If you want a starting point for code work:

```bash
dejavu obsidian init <vault> --preset dev
# → creates API/ Architecture/ Patterns/ Tools/ under Knowledge/
```

---

## Automatic linking between notes (Ollama)

**The core of dejavu needs no AI model and no network connection.** Search runs on
SQLite's own full-text index (FTS5) and nothing else. The zero-dependency property is what
keeps the Homebrew formula free of extra downloads, so it is a line held deliberately.

The one exception is **linking notes to each other by meaning**. That needs text
embeddings, which means a local model such as [Ollama](https://ollama.com).

So it is **kept out of the core and split into a separate command.** Without Ollama that
one feature is unavailable and nothing else is affected. **Everything documented in this
reference works without it.**

Obsidian also has manual `[[links]]` and a graph view of its own, so the vault remains
perfectly usable with no automatic linking at all.

---

## Categories

Knowledge is filed under one of six categories. Claude picks, so you will rarely think
about it.

| Category | What it holds | Example |
| --- | --- | --- |
| `context` | Session handoff notes | "Done: migration merged. Next: rollback tests." |
| `plan` | Work put off until later | "Fix the AppDelegate warning" |
| `decision` | Design decisions **and rejected options** | "Chose UIKit over SwiftUI because…" |
| `feature` | How a piece of code works | "`Migration.swift` runs in three phases…" |
| `convention` | Team rules | "Every view model ends in `ViewModel`" |
| `note` | Everything else | |

---

## When knowledge goes stale

Code changes. Notes about the code do not. dejavu is built on that assumption.

Every entry records when it was last **checked against the real code**. Once that gets
old, search results come back marked:

```
⚠ [a3f01c8b] Migration runs in three phases (feature) [STALE: 12 days since last check]
```

**A stale entry is not dropped from the results.** Old knowledge is still a useful clue,
and throwing it away would do more harm than flagging it. Claude is instructed to check a
stale entry against the current code before relying on it.

For a spring clean, say "**review the knowledge that has gone stale**" and Claude goes
through them one by one, sorting out what to fix, what to throw away, and what to leave.

Thresholds live in `[stale_days]` in `.dejavu/config.toml`.

> Vault and `docs/knowledge/` notes are never marked stale. The file *is* the truth, so
> there is nothing for it to fall out of date with.

---

## Credentials are never stored

Text containing something that looks like an API key, a token or a private key is refused.
The same detector runs on the CLI and MCP paths.

Covered: OpenAI and Anthropic API keys, GitHub tokens, AWS access keys, Google API keys,
Slack tokens, private key blocks, Bearer tokens, basic auth embedded in a URL, and
`api_key = "..."`-style assignments.

`--force` overrides it, for false positives only.

---

## Sharing with a team

Put Markdown in `docs/knowledge/*.md`. git tracks it, so it is reviewed in pull requests
and arrives with a clone.

dejavu indexes it with the same machinery it uses for the vault, so it shows up in
`dejavu search` marked `[shared]`:

```
    [5eb6c3c6f85a] Team conventions (note) [shared]
       File: docs/knowledge/team-rule.md
```

The index (`.dejavu/shared.db`) is gitignored — the Markdown it is built from is already
tracked, so committing a binary would add nothing.

**Sharing the database itself is not built.** A design for exporting entries to Markdown
exists but is not implemented ([BACKLOG.md](BACKLOG.md)).

---

## The MCP server

The terminal and Xcode's agent sit in the same filesystem as the database, so the CLI
reaches them. **Claude Desktop and Cowork do not** — their shells run in a sandbox that
cannot see `~/.config/dejavu/`. Those hosts *do* launch MCP servers as local subprocesses,
which is the one door left open.

```bash
dejavu install-mcp
```

It registers in `~/Library/Application Support/Claude/claude_desktop_config.json`.
Restart the app to pick it up.

### Tools

| Tool | Purpose |
| --- | --- |
| `search_knowledge` | Search everything; `source` says where each hit came from |
| `resume_knowledge` | The last handoff note |
| `recent_knowledge` | Recent activity |
| `add_knowledge` | Store |
| `update_knowledge` | Update or append |
| `get_knowledge` | One entry in full |
| `obsidian_status` | Whether a vault is connected, the write mode, the policies |
| `add_obsidian_knowledge` | Save into the vault's `Knowledge/` |
| `add_research` | Record under the vault's `Research/<project>/` |

### Scopes have no working directory here

An MCP server is launched by the desktop app, from wherever that happens to be, so **it has
no working directory.** A project cannot be inferred, only stated. Name the project and
Claude passes the path.

With no project named, only your personal knowledge and the vault are used.

### When both sides answer

If the project and the vault both hit the same query, both come back as
`conflict_candidates` and Claude shows:

```
  ⚠ CONFLICT RISK — the project and the vault both answer this query:
    project   [48f7921e75f4] Auth design decision
    obsidian  [0c0cac2bbacf] Shared auth policy
```

dejavu does not judge which is right. A wrong answer in the vault would follow you into
every other project, so the question goes to you.

---

## Coexisting with Claude's own memory

Claude Code has two memory mechanisms of its own. They do different jobs from dejavu and
do not compete with it. Here are the technical differences.

| | CLAUDE.md | Auto memory | dejavu |
| --- | --- | --- | --- |
| Who writes it | you | Claude | Claude |
| Where | project / `~/.claude/` | `~/.claude/projects/<project>/memory/` | `.dejavu/` / `~/.config/dejavu/` |
| Loading | in full, every session | `MEMORY.md`, **first 200 lines or 25KB** | **only when searched** |
| Search | none | none (Claude reads the files) | FTS5 full text plus keywords |
| Structure | none | free-form Markdown | categories, status, keywords |
| Freshness | none | none | `checked_at` and a ⚠ STALE flag |
| Reach | Claude Code | Claude Code only (machine-local) | Claude Code / Xcode / chat / Cowork |
| Credentials | unprotected | unprotected | detected and refused |

### Why dejavu is still needed

`MEMORY.md` loads at the start of every session, but only its **first 200 lines (or
25KB)**. Anything beyond that is not loaded at startup. The overflow lives in topic files
like `debugging.md`, which Claude reads on demand when it judges them relevant.

So **the more that accumulates, the more it competes for that fixed slot — and there is no
search.** dejavu inverts this: nothing is loaded until something is asked for, then a
search returns the handful of entries that match. The only standing cost is a few dozen
lines of instructions, so it keeps working as the knowledge grows.

### Which to use

- **CLAUDE.md** — rules you want Claude to follow. You write it
- **Auto memory** — what Claude notices while working. It accumulates on its own
- **dejavu** — long-term memory you search; reachable from several surfaces

Auto memory can be inspected and edited with the `/memory` command.

> claude.ai's chat also has a "memory" feature, but that is a separate thing stored on the
> server. Claude Code cannot see it, and it cannot see auto memory either.

---

## Using it in Xcode

Xcode 26.3+ embeds Claude Code itself as an Agent, so it can run `dejavu`. The project's
`CLAUDE.md` is read normally, so once `dejavu init` has been run there is nothing to
configure.

**Two things to watch for.**

**Do not put `.dejavu/` in an Xcode 16 synchronized group.** A "buildable folder" adds
every file it contains to the target automatically. At the repository root you are safe.

**`PATH` is not inherited.** Xcode launches the agent in an environment that does not read
your login shell config. If you hit `dejavu: command not found`, have the agent run:

```
echo $PATH
which dejavu
```

That is why `install-mcp` writes an absolute path (`/usr/local/bin/dejavu`).

Note also that `dejavu init --global` installs into `~/.claude/`, while Xcode reads its
own config directory:

```
~/Library/Developer/Xcode/CodingAssistant/ClaudeAgentConfig/
```

A symlink covers the slash commands:

```bash
ln -s ~/.claude/commands ~/Library/Developer/Xcode/CodingAssistant/ClaudeAgentConfig/commands
```

---

## Troubleshooting

**I changed the instructions and nothing happened**
Re-run `dejavu init` in each project. `dejavu-triggers.md` is copied at `init` time, so
upgrading the binary leaves the old copy in place. `dejavu init --global` for the shared one.

**`dejavu obsidian sync` says nothing changed, but I edited a note**
Files are skipped when their modification time and size are unchanged. Save again in
Obsidian and re-run.

**A vault note does not turn up in search**
Check the per-folder counts with `dejavu obsidian doctor`. A count of zero usually means
the folder is not in `include`:

```bash
dejavu config include
```

**It refuses to write, saying the note was not written by dejavu**
Working as intended. A note without `source: dejavu` in its frontmatter is protected. Add
that line yourself if you really want dejavu to manage it.

**It refuses to replace a body**
The vault is in a synced folder; `dejavu obsidian doctor` says which one. Appending still
works. To override anyway: `dejavu config write_mode full`.

**Two-character Japanese search does not work**
It should. SQLite's trigram tokenizer cannot match anything shorter than three characters,
so dejavu always runs a third LIKE-based tier alongside it. If that fails, it is a bug —
please report it.

**How do I remove it from a project?**
Delete `.dejavu/` and the one imported line in `CLAUDE.md`. Nothing else was touched.
