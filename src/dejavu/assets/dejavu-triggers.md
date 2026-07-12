# Knowledge base (dejavu)

This project has a local knowledge base, `dejavu`. These are the triggers.

## Search

- Before reading unfamiliar code or modules, run `dejavu search "<keywords>"` first
- If the user says "continue from yesterday" or "where did we leave off",
  run `dejavu search "next" --category context`
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

## How to write entries

- **Dense, not long.** Skip the narrative; keep the reasoning behind a decision, the
  options rejected, and the paths and function names that are expensive to rediscover
- Hand-pick 5-10 keywords
- Never store credentials

Run `dejavu --help` or `dejavu <command> --help` for details.
