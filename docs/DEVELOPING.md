# Developing dejavu

You will spend most of your time *using* dejavu — on real work, in other repositories.
Now and then it will annoy you, and you will come back here to fix it.

This document is about that loop: how to notice a problem while working elsewhere, how to
carry it back, and how to make the change without breaking the copy you depend on.

---

## Contents

1. [Two hats, one machine](#two-hats-one-machine)
2. [Never let the dev build shadow the real one](#never-let-the-dev-build-shadow-the-real-one)
3. [Carrying a complaint back from real work](#carrying-a-complaint-back-from-real-work)
4. [The change loop](#the-change-loop)
5. [Releasing](#releasing)
6. [After a release: refreshing the projects that use dejavu](#after-a-release-refreshing-the-projects-that-use-dejavu)
7. [Tuning](#tuning)
8. [The MCP server](#the-mcp-server)
9. [Checklists](#checklists)

---

## Two hats, one machine

| Hat | Where | Which dejavu |
| --- | --- | --- |
| **Using** dejavu | your Xcode project, any other repo | the Homebrew build (`/usr/local/bin/dejavu`) |
| **Developing** dejavu | `~/GitHub/dejavu` | the working tree, via `uv run` |

Keep these apart. The failure mode is subtle: you install a development build, forget, and
weeks later cannot tell whether a bug is in your code or in the version you happen to have
on `PATH`.

### Use dejavu on dejavu

Run this once, in the dejavu repository itself:

```bash
cd ~/GitHub/dejavu
dejavu init
```

Now the tool's own design decisions are searchable while you work on it. When you come back
in three weeks and wonder why `resume` is a separate command instead of a `search` flag,
Claude can answer without you having to remember.

---

## Never let the dev build shadow the real one

**Do not run `uv tool install --editable .`.** It puts a `dejavu` on your `PATH` at
`~/.local/bin/dejavu`, ahead of the Homebrew one. Homebrew warns about this:

```
The following dejavu executables are shadowed by other commands earlier in your PATH:
  deja (shadowed by /Users/yoshiyuki/.local/bin/deja)
```

From then on, every `dejavu` you type in *any* project — including the Xcode work you
depend on — runs your half-finished branch.

**Use `uv run` instead.** It executes the working tree without touching `PATH`:

```bash
cd ~/GitHub/dejavu
uv run dejavu --version
uv run dejavu search "検索"
uv run pytest -v
uv run ruff check .
```

If you have already installed the editable build, remove it:

```bash
uv tool uninstall dejavu
hash -r
which dejavu          # → /usr/local/bin/dejavu
```

### Trying a change against real data

To see how a change behaves against an actual knowledge base — without writing to it:

```bash
cp -R ~/.config/dejavu /tmp/dejavu-snapshot
DEJAVU_HOME=/tmp/dejavu-snapshot uv run dejavu search "..."
```

`DEJAVU_HOME` redirects the user scope. The test suite uses the same escape hatch.

---

## Carrying a complaint back from real work

The moment you notice something is when you are busy with something else. Stopping to fix
dejavu derails the work you were actually doing; carrying on means forgetting.

**Use the user scope as the bridge.** It is readable from every project, which is exactly
what you need when the complaint occurs in one repository and the fix belongs in another.

In the Xcode project, mid-task:

```
You:     dejavu keeps saving entries that are far too long. Remember that as a dejavu
         improvement idea — save it to the user scope so I see it when I next work on dejavu.
```

Later, in `~/GitHub/dejavu`:

```bash
dejavu recent --scope user --since 14d
```

Everything you flagged over the last two weeks comes back, and you can turn it into a plan.

### Write down the symptom, not the fix

At the moment of annoyance you know what went *wrong*. You rarely know yet what the right
change is, and a note that records your first guess ("increase the snippet limit") throws
away the evidence you will actually need. Record:

- what you asked for
- what dejavu did
- what you expected instead
- the entry UID, if there is one

The fix follows from that. The reverse does not.

---

## The change loop

```bash
cd ~/GitHub/dejavu
claude                              # say what is annoying you; Claude searches its own knowledge base

git switch -c wip-snippet-length    # a local branch, never pushed
# ... experiment freely; commit as messily as you like ...

uv run pytest -v
uv run ruff check .
uv run dejavu search "検索"          # ★ the two-character Japanese check, every time

git switch main
git merge --squash wip-snippet-length
git commit -m "fix(search): trim snippets to 100 chars"
git branch -D wip-snippet-length    # the messy history disappears with the branch

git push origin main                # CI runs
```

Only `main` is ever pushed, so the experimental commits stay private. This is what keeps
the public history readable without any extra effort.

### Before you change search, know what you are protecting

`tests/test_search_ja.py` is not routine coverage. The FTS5 trigram tokenizer **cannot
match any query shorter than three characters**, and many everyday Japanese words —
検索, 認証, 実装, 設計 — are exactly two. The LIKE fallback is the only reason Japanese
search works at all.

If a change to `search.py` makes those tests red, the change is wrong, however reasonable it
looked. Do not adjust the tests to fit.

---

## Releasing

```bash
# 1. Bump the version. This file is the single source of truth.
vim src/dejavu/__init__.py          # __version__ = "0.3.0"
git commit -am "chore: bump to 0.3.0"
git push

# 2. Tag. Everything downstream is automatic.
git tag v0.3.0
git push origin v0.3.0
```

The workflow verifies the tag against `__version__` and **fails the release if they
disagree** — otherwise you would ship a formula that claims 0.3.0 and installs 0.2.1. If CI
goes red at the very first step, this is why.

Then it creates the Release, computes the tarball's sha256, rewrites `packaging/dejavu.rb`
into `AlohaYos/homebrew-tap` as `Formula/dejavu.rb`, and pushes.

```bash
brew update && brew upgrade dejavu
brew test dejavu                    # initialises a knowledge base and searches 検索
```

### Two ways a tag silently does nothing

- **The tag was never pushed.** `git push` does not push tags. `git push origin v0.3.0` does.
- **The tag points at a commit with no `release.yml`.** Actions runs the workflow *as it
  exists in the tagged commit*. Re-pushing the same tag will not help — no new event is
  generated. Delete the tag and re-create it on a commit that has the workflow, or just cut
  the next version.

See `docs/RELEASING.md` for the full picture.

---

## After a release: refreshing the projects that use dejavu

**Upgrading the binary does not update the instructions already sitting in your projects.**
`dejavu-triggers.md` was copied into each project's `.dejavu/` when you ran `dejavu init`
there. If you changed the triggers — which is most of what tuning means — every project
needs a refresh:

```bash
cd ~/Projects/MyApp
dejavu init                         # rewrites .dejavu/dejavu-triggers.md; the database is untouched
```

And for the global instructions:

```bash
dejavu init --global
```

`dejavu init` is idempotent: it never touches your source, and it only appends to
`CLAUDE.md` and `.gitignore` if the lines are missing. Running it again is safe.

Forgetting this step makes a triggers change look like it did nothing.

---

## Tuning

Everything below was set by guesswork. None of it can be settled without a real corpus,
which is exactly what the next few weeks of Xcode work will produce.

### First, collect

After two weeks of real use:

```bash
cd ~/Projects/MyApp
dejavu stats
dejavu list --limit 100             # read them. actually read them
dejavu list --stale
```

### `dejavu-triggers.md` — the one worth cutting

Currently 44 lines, up from 29 after the scope rules were added. **It is loaded on every
single turn**, which makes it the file whose weight you pay for most often — and the thing
dejavu exists to prevent is exactly this kind of context tax.

Ask, for each section:

| Question | If yes |
| --- | --- |
| Does Claude do this anyway, without being told? | delete the lines |
| Does Claude ignore it despite being told? | the wording is wrong, not missing — rewrite, do not add |
| Did it change behaviour? | keep it, and know why |

The upstream project cut its instructions from 127 lines to 29. Expect to cut, not grow.

### Entry length — `SNIPPET_LEN` in `cli.py`

Symptom: search results are wordy; recalling three entries costs more context than reading
the file would have.

Two different levers, and they are not interchangeable:

- **`SNIPPET_LEN` (150)** — how much of an entry `search` prints. Cheap to change, affects
  every recall.
- **The triggers wording** — how much Claude *writes* in the first place. This is the real
  fix. A 900-word entry trimmed to 150 characters on display is still 900 words in the
  database, and `dejavu show` will still dump all of it.

If entries are too long, fix the writing instructions first.

### Duplicate detection — `DUPLICATE_TITLE_RATIO` (0.75) in `safety.py`

- Blocking entries that are genuinely new → lower the threshold is **wrong**; raise it
  (0.85) so fewer things count as duplicates.
- Letting near-identical entries pile up → lower it (0.65).

Look at `dejavu list` and count the actual near-duplicates before turning the dial.

### Stale thresholds — `.dejavu/config.toml`

Defaults: context 7d, plan 14d, decision 30d, feature 7d, convention 30d, note 14d.

- Everything is `⚠ STALE` and you have stopped reading the warning → the thresholds are too
  tight. A warning that always fires carries no information.
- Claude confidently used a note that was long out of date → too loose.

Note that these are **per project**, in `.dejavu/config.toml`. To change the defaults for
new projects, edit `src/dejavu/assets/config.toml` and cut a release.

### Search weights — `W_FTS` / `W_KEYWORD` / `W_LIKE` in `search.py`

Leave these alone until the knowledge base has hundreds of entries. With a dozen, the
ranking is meaningless and you will be tuning noise.

When you do touch them, `dejavu search --json` reports the score and which tiers fired for
each hit. That is what to look at — not the rendered output.

---

## The MCP server

Shipped in v0.3.0: `src/dejavu/mcp.py`, registered with `dejavu install-mcp`.

### Why it exists, so you do not extend it for the wrong reason

The CLI reaches any agent that can run shell commands in the same filesystem as the
database: terminal Claude Code, and Xcode's built-in Claude Agent. It **cannot** reach
Claude Desktop or Cowork, whose shells run in an isolated sandbox with no access to
`~/.config/dejavu/`. Those hosts *do* launch MCP servers as local subprocesses on the real
machine — the one door left open.

**Reach is the whole justification.** Not "the agent will use dejavu more": the instructions
already achieve that wherever the CLI is reachable. The upstream author found MCP tools were
easier for the model to notice at first, but as the instructions and the models improved,
that advantage vanished, and he now runs without MCP.

### The two rules

**Never reimplement search, storage or the safety checks there.** `mcp.py` calls the same
functions `cli.py` calls. If the two paths diverged, the secret detector could run in one
and not the other — a credential leak that no test would catch, because each path would
pass its own tests. `tests/test_mcp.py::test_add_refuses_secrets` exists for exactly this.

**No dependency.** MCP's stdio transport is newline-delimited JSON-RPC 2.0, and a tools-only
server needs five methods (`initialize`, `notifications/initialized`, `tools/list`,
`tools/call`, `ping`). The official SDK would pull in pydantic and anyio, and the
zero-dependency property is load-bearing: it is why the Homebrew formula needs no `resource`
blocks at all. The cost is that protocol revisions must be followed by hand — which is what
`tests/test_mcp.py` makes safe.

### Scopes have no cwd here

A shell command knows where it is. An MCP server does not: it is launched by the desktop app
from wherever that happens to be. A project therefore cannot be inferred, only stated. Every
tool takes an optional `project_path`; without one, only the user scope is touched.

Watch out for `Entry.scope`. It is set by `store.get_entry`, whose `scope_name` defaults to
`"project"` — so a freshly written entry always *claims* to be a project entry even when it
went to the user scope. `mcp.py` reports `scope.name` from the Scope it opened, never
`entry.scope`. This bit once already.

### Debugging it

The server speaks on stdin/stdout, so you can drive it by hand exactly as a host would:

```bash
{
  echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{}}}'
  echo '{"jsonrpc":"2.0","method":"notifications/initialized"}'
  echo '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
} | uv run dejavu mcp
```

Anything written to stdout that is not a JSON-RPC message corrupts the stream. Log to
**stderr** only.

### Registering it elsewhere

Xcode's Claude Agent reads its own config directory, not `~/.claude`:

```
~/Library/Developer/Xcode/CodingAssistant/ClaudeAgentConfig/.claude
```

and launches agents in a restricted environment that **does not inherit your login shell**.
Any command there needs an absolute path — which is why `install-mcp` writes
`/usr/local/bin/dejavu`, not `dejavu`. See `docs/BACKLOG.md`.

---

## Checklists

### Starting a session on dejavu

```bash
cd ~/GitHub/dejavu
dejavu recent --scope user --since 14d    # complaints you parked while doing real work
claude
```
Then: "continue from yesterday".

### Before pushing to main

- [ ] `uv run pytest -v` — green, including `test_search_ja.py`
- [ ] `uv run ruff check .` — clean
- [ ] `uv run dejavu search "検索"` — hits
- [ ] Changed the triggers? `wc -l src/dejavu/assets/dejavu-triggers.md` — did it get longer?
- [ ] Squashed into one commit

### Cutting a release

- [ ] `__version__` bumped and pushed
- [ ] Tag matches `__version__`
- [ ] Tag pushed explicitly (`git push origin vX.Y.Z`)
- [ ] Actions green
- [ ] `Formula/dejavu.rb` updated in `AlohaYos/homebrew-tap`
- [ ] `brew upgrade dejavu && brew test dejavu`
- [ ] **`dejavu init` re-run in every project** — otherwise triggers changes do nothing
