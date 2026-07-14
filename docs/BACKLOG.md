# Backlog

Work that is deliberately deferred, with enough context to pick it up cold.

Status: `proposed` = decided but not started. `investigating` = needs facts first.

---

## MCP server — `done` (v0.3.0)

Shipped. `src/dejavu/mcp.py`, registered with `dejavu install-mcp`.

Kept for the record, because the reasoning behind two decisions is not obvious from the
code:

**Hand-written, no SDK.** MCP's stdio transport is newline-delimited JSON-RPC 2.0, and a
tools-only server needs five methods. The official SDK would have pulled in pydantic and
anyio, and dejavu's zero-dependency property is load-bearing: it is the reason the Homebrew
formula needs no `resource` blocks at all. The cost is that protocol revisions must be
followed by hand; `tests/test_mcp.py` is what makes that safe to do.

**Reach, not adoption.** The case for MCP was never "the agent will use dejavu more" — the
instructions already achieve that wherever the CLI is reachable. It was reach: Claude
Desktop and Cowork run their shells in an isolated sandbox that cannot see
`~/.config/dejavu/`, but they *do* launch MCP servers as local subprocesses. That was the
one door left open.

**Still not done: no phoning home.** The upstream MCP server contacts GitHub once a day to
check for updates. dejavu does not, and must not. The README promises *no network access at
all*, and that claim should stay literally true.

---

## Xcode Claude Agent: PATH is not inherited — `investigating`

**The problem.** Xcode 26.3+ embeds the real Claude Code binary as an Agent, so it *can*
run `dejavu`. But Xcode launches it in a restricted environment that **does not inherit
the login shell's configuration** (`.zshrc` and friends). If `/opt/homebrew/bin` is not on
`PATH`, the agent will hit `dejavu: command not found` and quietly fall back to reading
the code from scratch — the exact failure dejavu exists to prevent, and one that looks
like "dejavu just doesn't work in Xcode".

**Unknown.** Whether Homebrew's bin directory happens to be on the default `PATH` in that
environment. **This has not been tested on a real machine.** Find out first:

```
# Ask the Xcode Claude Agent to run these
echo $PATH
which dejavu
```

**Options, if it is not on PATH:**

1. `dejavu init` detects an Xcode project and writes the absolute path of the `dejavu`
   binary into `dejavu-triggers.md`. Simple, but bakes a machine-specific path into a
   file that is tracked by git and shared with the team — bad.
2. `dejavu init` writes the absolute path into a *local, git-ignored* fragment that the
   triggers file references. Keeps the shared file portable.
3. Document a symlink into a directory that is on the default PATH.

Option 2 is the likely answer, but do not build it until the `echo $PATH` result is known.
It may be a non-issue.

**Related.** Xcode's agent reads its own config directory, not `~/.claude`:

```
~/Library/Developer/Xcode/CodingAssistant/ClaudeAgentConfig/
├── commands/
└── skills/
```

So `dejavu init --global` does **not** reach it. Project-level `dejavu init` does, because
the project's `CLAUDE.md` is read normally. A symlink covers the slash commands:

```bash
ln -s ~/.claude/commands ~/Library/Developer/Xcode/CodingAssistant/ClaudeAgentConfig/commands
```

Source: https://fatbobman.com/en/posts/xcode-263-claude/ (third-party; verify before relying on it)

---

## Markdown export / sync — `proposed`

The `shared` half of the two-layer design (Markdown is the source of truth, SQLite is a
rebuildable index) is designed but not implemented. `storage`, `source_path` and
`source_hash` columns already exist in the schema and are currently unused.

- `dejavu export [<uid>]` — DB → `.dejavu/<category>/<slug>-<uid>.md`, flip `storage` to `shared`
- `dejavu sync` — Markdown → DB, driven by a file-hash diff against `source_hash`
- Automatic sync after `git pull`: compare hashes on any read command, no manual `sync`
- `dejavu promote <uid>` — shorthand for "this local note is worth sharing"
- ADR support: `status` transitions and bidirectional `supersede` links (the `links` table
  is already there)

The README's "Working with a team" section used to describe this as though it already
worked. It now says plainly that dejavu is a personal tool today, and points here.

Keep it that way: **do not describe sharing in the README until the code is there.**

---

## Tuning, once there is real usage data — `investigating`

These were set by guesswork and cannot be settled without a real corpus:

- **Duplicate-detection threshold** (`safety.DUPLICATE_TITLE_RATIO = 0.75`). Currently
  errs towards blocking. Watch for false positives that stop legitimate entries.
- **Stale thresholds** (`config.toml`: context 7d, decision 30d, …). Pure guesswork.
- **Search score weights** (`search.py`: `W_FTS` / `W_KEYWORD` / `W_LIKE`). The rankings
  look sensible on a handful of entries; they have never been tested against hundreds.
- **`dejavu-triggers.md` length.** Now 44 lines, up from 29 after adding the scope rules.
  It is loaded on every turn, so this is the file most worth shrinking. If the scope
  section turns out not to change Claude's behaviour, delete it.
