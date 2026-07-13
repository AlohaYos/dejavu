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

## Which scope

Default is the project scope. Add `--scope user` when the knowledge is about the *user*
rather than *this repository* — it then follows them into every project:

- personal preferences and working style ("always squash-merge", "write PR bodies as
  bullet points")
- facts about their machine or setup ("uses the Homebrew Python, not the system one")
- anything they say they want remembered **everywhere**, **always**, or **in general**

If it would be wrong advice in a different repository, it belongs in the project scope.

- **Dense, not long.** Skip the narrative; keep the reasoning behind a decision, the
  options rejected, and the paths and function names that are expensive to rediscover
- Hand-pick 5-10 keywords
- Never store credentials

Run `dejavu --help` or `dejavu <command> --help` for details.
