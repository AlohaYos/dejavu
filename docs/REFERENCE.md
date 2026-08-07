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
7. [Connecting a pile of your own notes](#connecting-a-pile-of-your-own-notes)
8. [Categories](#categories)
9. [When knowledge goes stale](#when-knowledge-goes-stale)
10. [Credentials are never stored](#credentials-are-never-stored)
11. [Sharing with a team](#sharing-with-a-team)
12. [The MCP server](#the-mcp-server)
13. [Coexisting with Claude's own memory](#coexisting-with-claudes-own-memory)
14. [Using it in Xcode](#using-it-in-xcode)
15. [Troubleshooting](#troubleshooting)

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
| `dejavu obsidian relate "<title>"` | Show the links a note would get (**writes nothing**) |
| `dejavu obsidian relate "<title>" --write` | Write them |
| `dejavu obsidian relate --backfill` | Embed the notes you already have (`relate = embed`) |
| `dejavu obsidian relate --rebuild` | Throw the vectors away and build them again |
| `dejavu obsidian relate --start` | Start Ollama and add every link that is waiting |
| `dejavu obsidian relate --pending` | List the notes still waiting to be linked |
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
knowledge_other_dir = "Other"
userinfo_dir  = "UserInfo"
research_dir  = "Research"
write_mode    = "auto"       # auto | full | append-only
research      = "findings"   # all | findings | manual
promote       = "ask"        # ask | always | never
harvest       = "on"         # on | off
harvest_min_lines = 40
relate        = "off"        # off | search | embed
relate_model  = "bge-m3"
relate_host   = "http://localhost:11434"
relate_key    = "related"
relate_top_k  = 5
relate_min_sim   = 0.65
relate_min_chars = 40
relate_autostart = "ask"     # ask | always | never
relate_keep_alive = "24h"
relate_defer_days = 7
```

| Key | Meaning |
| --- | --- |
| `vault` | Path to the vault. **Unset means the integration is entirely off** |
| `include` | Folders that are indexed and written to. Anything else is invisible |
| `knowledge_dir` | Where cross-project knowledge goes |
| `knowledge_other_dir` | Catch-all for notes fitting nowhere (default `Other`; **used only if it exists**) |
| `userinfo_dir` | Where your own information goes |
| `research_dir` | Where investigations go (one subfolder per project) |
| `write_mode` | See below |
| `research` | How much of an investigation to keep |
| `promote` | Whether to offer to lift project knowledge into the vault |
| `harvest` | See below |
| `harvest_min_lines` | Sessions shorter than this are skipped silently (default 40) |
| `relate*` | [Automatic linking](#automatic-linking-between-notes-ollama). Off by default |

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

### `harvest` — the session-end sweep

At the end of a session, Claude Code runs the Stop hook that `dejavu init --global`
registered. dejavu answers it with one instruction: file anything you learned that would
still be true in a different repository — and do it without asking the user first.

It fires **once per session**, and stays silent when any of these hold: no vault is
configured, `harvest = "off"`, `promote = "never"`, or the session was shorter than
`harvest_min_lines`. Nothing is written by the hook itself; it only asks.

| Value | Behaviour |
| --- | --- |
| `on` | Prompt for a harvest at the end of a session (default) |
| `off` | Never prompt |

The hook is installed by `dejavu init --global` (skip it with `--no-hooks`). Existing
hooks in `settings.json` are preserved and the file is backed up before it is edited.

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

### Where notes that fit nowhere go

When `Knowledge/` has subfolders, **a note matching none of them goes to `Other/`**
(renameable with `knowledge_other_dir`, default `Other`).

Without it, the notes that fit nowhere collect directly in `Knowledge/` until the folders
you made are lost among them.

**dejavu does not create this folder either.** It is used only if you make it, so a vault
kept deliberately flat stays flat. `dejavu obsidian init --preset dev` creates `Other/`
along with the rest.

The MCP `obsidian_status` reports the subfolders of `Knowledge/` as `knowledge_folders`,
so Claude picks from names that exist rather than passing `pattern` at a folder called
`Patterns` and quietly landing in the catch-all.

### What a note is called

The name that appears in search results and in links is decided like this.

| Note | Name |
| --- | --- |
| Written by dejavu (`source: dejavu` present) | its leading `# heading` |
| Anything else (yours) | **the file name** |

In Obsidian the file name *is* the note's name, so that is what dejavu follows. The first
line of a note someone wrote is usually the opening of a chapter — "Introduction" — rather
than its title. Treating that as the name leaves the note called something meaningless,
and puts the same word at the front of the text handed to the embedding model, so
**documents that merely open the same way start to look related.**

Notes dejavu wrote are the exception because dejavu writes that heading as the title.

### Folders

`Knowledge/` starts flat. Create subfolders and dejavu will file notes into them, but it
**never creates one of its own** — vault layouts are personal, and imposing dejavu's
taxonomy on yours would be rude.

If you want a starting point for code work:

```bash
dejavu obsidian init <vault> --preset dev
# → creates API/ Architecture/ Patterns/ Tools/ Other/ under Knowledge/
```

---

## Automatic linking between notes (Ollama)

The moment dejavu writes a note into Obsidian, it writes `[[links]]` to the existing notes
that are about the same thing. The only trigger is dejavu's own write path — no daemon, no
file watcher. **This is not a nightly batch job.**

### Three modes

| `relate` | How closeness is judged | Needs |
| --- | --- | --- |
| `off` (default) | — | — |
| `search` | Shared words (the FTS5 → keywords → LIKE tiers) | nothing |
| `embed` | **What the text means** (cosine similarity of embeddings) | [Ollama](https://ollama.com) |

```bash
dejavu config relate embed
ollama pull bge-m3
dejavu obsidian relate --backfill      # embed the notes you already have, once
```

Ollama itself comes from <https://ollama.com/download>, or `brew install ollama` if you
prefer the terminal — in which case leave `ollama serve` running.

`--backfill` takes one to three minutes for a few hundred notes. It commits batch by
batch, so **stopping it is safe: run it again and it carries on from where it left off.**
`--rebuild` throws every stored vector away first, which is what you want after changing
`relate_model`.

`dejavu obsidian doctor` prints the current mode on its `Auto-link` line, whether Ollama
answered (and why not, if it did not) on the `Ollama` line, and how many notes have a
vector on the `Vectors` line. When links are not appearing, start there.

### When Ollama is not running

**Links are held back and added later.** They are not quietly made by words instead:
someone who chose `embed` paid for links that follow meaning, and on a synced vault a link
once written **cannot be corrected afterwards**.

- **Notes still save, exactly as before.** A model server being down never costs someone
  their writing
- Held-back notes are recorded in `pending_relate` and **cleared automatically the next
  time Ollama answers** — up to five per write, with nobody having to run anything
- `dejavu obsidian relate --pending` lists what is waiting
- `dejavu obsidian relate --start` starts it now and clears the lot, asking first if it
  has to launch anything (`relate_autostart`)
- A note still waiting after `relate_defer_days` (7 by default) **is linked by words and
  finished**. Left forever unlinked is worse than imperfectly linked

For sixty seconds after a failure, dejavu holds notes back without trying to connect, so a
run of writes during an outage costs one timeout rather than one each. `doctor` ignores
that memory and always makes a real connection.

### Keeping the model loaded

Ollama unloads a model five minutes after its last use. Left alone that produces the most
confusing failure of all — running, but timing out on the first note after a break — so
dejavu sends **`keep_alive` (default `"24h"`) with every request.**

The `OLLAMA_KEEP_ALIVE` environment variable is not used. Making it stick means writing a
launch agent, and **a change left on someone's machine is a change they have to be told
how to undo.** In the request, it affects dejavu's own calls and nothing else.

### How it gets started

`--start` picks the method from how Ollama was installed.

| Found | How it starts |
| --- | --- |
| `/Applications/Ollama.app` | `open -ga Ollama` |
| A Homebrew install | `brew services start ollama` (**this also makes it start at login** — said plainly when asking) |
| Neither | Nothing is run; you get the download link |

The app is preferred because `brew services` writes a launch agent, which turns "start it
now" into a permanent change. dejavu **never stops Ollama**: telling "I started this" apart
from "it was already running" is not worth getting wrong on someone else's machine.

`relate_autostart` is `ask` (default), `always` or `never`. **A refusal is remembered** —
being asked once is a question, being asked every time is a reason to give up on the
feature.

**The core of dejavu needs no AI model and no network connection.** Search runs on
SQLite's own full-text index (FTS5) and nothing else. Only `embed` talks to anything, and
only over HTTP to the Ollama on the same machine — using `urllib`, so the dependency count
stays at zero.

### Where the links are written

| Case | Destination |
| --- | --- |
| A new note | the `related:` key, written as part of creating the file (one write, not two) |
| `write_mode = full` | the `related:` line is replaced |
| `write_mode = append-only` | `---` and a `## Related` section are **appended** to the body |

On an append-only vault, a note that already has a `## Related` section is **left alone**:
moving or rewriting it would mean rewriting the whole file, which is what append-only
exists to avoid. Text appended afterwards therefore ends up below that section. That is
known and accepted.

### What it never touches

- **A note without `source: dejavu` is never written to.** Notes you wrote by hand are out
  of scope
- Frontmatter is spliced line by line, so keys other tools wrote — `autolink:` and the
  like — survive untouched
- **No backlinks are written.** Obsidian's backlink pane and graph view show the reverse
  direction for free

### Settings

| Key | Default | Meaning |
| --- | --- | --- |
| `relate` | `off` | `off` / `search` / `embed` |
| `relate_key` | `related` | the frontmatter key to write |
| `relate_top_k` | `5` | most links to add to one note |
| `relate_min_chars` | `40` | notes shorter than this are not linked |
| `relate_model` | `bge-m3` | the Ollama model |
| `relate_host` | `http://localhost:11434` | where Ollama is |
| `relate_min_sim` | `0.65` | below this, two notes are unrelated (`embed` only) |
| `relate_autostart` | `ask` | `ask` / `always` / `never` |
| `relate_keep_alive` | `"24h"` | sent with every request |
| `relate_defer_days` | `7` | days a note may wait before words are used instead |
| `link_keep_runs` | `10` | how many backup runs to keep |
| `link_keep_days` | `30` | how many days of backups to keep |

The default `relate_min_sim` of 0.65 was settled by running it over two real vaults. At
0.6, nearly every note in a 500-note vault filled `relate_top_k`, which means the cap was
choosing the links rather than the similarity. The right value depends on the vault, and
`dejavu obsidian relate "<title>"` (which writes nothing) is the way to find it.

`dejavu obsidian relate "<title>"` prints what would be linked and **writes nothing** —
the way to settle on a threshold. Add `--write` when you mean it.

### Dropping weak hits (in `search` mode)

A candidate found only by the LIKE tier is dropped: one shared substring is a coincidence,
not a relationship. **Unless the query contains a term shorter than three characters** —
for two-character Japanese words (検索 / 認証) LIKE is the only tier that can fire, so
dropping noise must never quietly drop Japanese.

### Where the vectors live

In a `vectors` table inside `~/.config/dejavu/obsidian.db`, keyed by the same `uid` the
index uses (derived from the note's path), so re-indexing never orphans one. Delete or
rename a note and the next sync clears its vector.

The hash is taken over the **embedded text**, not the file. Writing links changes a file's
mtime but not its meaning, so it does not make dejavu call the model again. The
`## Related` section and fenced code blocks are stripped before embedding.

---

## Connecting a pile of your own notes

`dejavu obsidian link` **links the notes in a vault folder to each other by meaning.**
The difference from [automatic linking](#automatic-linking-between-notes-ollama) is the
target: that one only touches notes dejavu wrote, while this one **edits notes the user
wrote themselves.**

It is the one feature that deliberately breaks the promise held since v0.4.0 — that a note
without `source: dejavu` is never written to. That is why it is kept separate.

### What makes it safe

A confirmation stops mattering the moment it is clicked. What this feature rests on is
**being able to take it back**.

| Mechanism | What it guarantees |
| --- | --- |
| Fenced in HTML comments | the exact bytes dejavu added are known |
| Every file copied before any is written | a failure partway leaves the vault untouched |
| Post-write hash in the manifest | a restore can tell "edited since" from "untouched" |
| Plan and apply are separate | what was shown is what happens |

### What gets added

```markdown
<!-- dejavu:links -->
## Related

- [[Sorting out receipts]]
- [[Filing as a sole trader]]
<!-- /dejavu:links -->
```

The comments are invisible in Obsidian. **Frontmatter is never touched** — other plugins
such as Dataview may be reading it.

**`source: dejavu` is never added.** With it, `append_to_note` and `replace_body` would
start treating the user's own writing as something dejavu may edit.

### Commands

| Command | Description |
| --- | --- |
| `dejavu obsidian link <folder>` | Show the plan. **Writes nothing** |
| `dejavu obsidian link <folder> --apply --plan-id <id>` | Carry it out |
| `dejavu obsidian link --all` | The whole vault (only when said explicitly) |
| `dejavu obsidian link --history` | Past runs |
| `dejavu obsidian link --remove [--run <id>]` | Take out only what was added |
| `dejavu obsidian link --restore [--run <id>]` | Put the files back as they were |

A plan gets an id, and applying requires it. Plans expire after 15 minutes, and **files
that changed since the plan are dropped from the run** and reported.

### How the links are chosen

Thresholds and model come from the `relate_*` settings; no separate ones are invented for
bulk runs. Two problems do appear in bulk that never appear one note at a time.

**One-sided resemblance is dropped.** A link is kept only when each note is among the
other's nearest — a one-way match usually means one of them is vague.

**Hubs are removed.** A note close to more than 30% of the others (a table of contents, an
index, a diary) is left out, and **the list is reported afterwards.** Removing them
silently would leave the user wondering why that one note never gets linked.

### Backups

```
~/.config/dejavu/backups/<vault>-<hash>/<timestamp>/
  manifest.json
  Inbox/tax-return.md
```

**Never inside the vault**: iCloud would copy every backup to every device, and could
raise sync conflicts on them.

The last **10 runs or 30 days** are kept (`link_keep_runs` / `link_keep_days`). Pruning
happens **only when the feature is next used** — nothing runs in the background. Runs that
were undone are dropped after a week.

### Two kinds of undo

| | `--remove` (preferred) | `--restore` |
| --- | --- | --- |
| What it does | takes out the added block | puts the whole file back |
| Text written since | **kept** | lost |
| Requires | the block still being there | the file matching its post-write hash |

`--restore` **refuses** on notes edited since the run. `--force` overrides it, and those
edits are lost.

### About `.txt`

Obsidian only reads `.md`. The plan reports how many `.txt` files were found, and applying
renames them. The renames are recorded in the manifest and undone with the run.

### From MCP

Three tools: `plan_note_links`, `apply_note_links`, `undo_note_links`.
`apply_note_links` refuses without `confirmed: true`, and its description states that it
**edits notes the user wrote, so the counts must be shown and agreed to first.**

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
