# Knowledge base (dejavu)

This project has a local knowledge base, `dejavu`. These are the triggers.

## Recall

- The user wants to pick up a previous session ("continue from yesterday", "where did
  we leave off") → run `dejavu resume`. **Do not search for it**: `resume` returns the
  latest handoff note deterministically, whereas a search can miss it
- The user asks what they have been working on, or wants a status update or standup
  note → run `dejavu recent` (add `--since today` to narrow it to today)
- Before reading unfamiliar code or modules → run `dejavu search "<keywords>"` first
- A `⚠ STALE` result must be checked against the current code before you rely on it.
  Still correct? `dejavu touch <uid>`. Out of date? `dejavu edit` it, or re-investigate

## Save

- Store findings with `dejavu add "<one-line summary>" --category feature --keywords "..." --body -`
  (pass the body on stdin)
- Never add a near-duplicate: extend the existing entry with `dejavu edit <uid> --append -`
- Design decisions: `--category decision`
- Work you are deferring: `--category plan --status proposed`
- At a stopping point, or when the user says "save this":
  store **what is done / what to do next / concrete artefacts (paths, function names)**
  under `--category context`

## Where it goes

The project scope by default. Knowledge that would still be true in a *different*
repository — a language pitfall, a tool's real behaviour, the user's own working style —
belongs to the user: `dejavu obsidian add "<title>" --body -` when a vault is set up,
otherwise `dejavu add --scope user`. Commands say what to do next when it matters.

Write it rather than asking whether to; the user prunes their own vault, so a note they
delete costs less than a discovery nobody wrote down. Report it in one line.

## External memory (Obsidian)

A project can point at one vault folder as its **external memory** — its shelf in the
Obsidian vault, set once with `dejavu obsidian project <name>`. The user reaches for it
when they want something kept where they can read it on any device, or out of git: design
docs, notes, a TODO snapshot. They may call it "外部記憶", "Obsidian", or "本棚".

- The user says to save something to external memory (「外部記憶に保存」「設計書を Obsidian に」)
  → `dejavu obsidian add "<title>" --memory --body -`. It goes to the project's folder even
  though it is project-specific — that is the point of external memory
- "外部記憶の設計書を読んで…" (read from external memory) → `dejavu search "<keywords>"`;
  vault notes come back with `source: obsidian`. On an append-only vault, "整理" (tidy up)
  produces a *new* consolidated note rather than rewriting one
- "このTODOを外部記憶にも保存して" → the **project DB stays the source of truth** (so
  "完了にしといて" / "add a TODO" still work). Write the current list as a dated snapshot:
  `dejavu list --category plan` → `dejavu obsidian add "TODO YYYY-MM-DD" --memory --body -`

If no external memory is set, `--memory` says so and points at `dejavu obsidian project`.

## How to write entries

- **Dense, not long.** Skip the narrative; keep the reasoning behind a decision, the
  options rejected, and the paths and function names that are expensive to rediscover
- Hand-pick 5-10 keywords
- Never store credentials

Run `dejavu --help` or `dejavu <command> --help` for details.
