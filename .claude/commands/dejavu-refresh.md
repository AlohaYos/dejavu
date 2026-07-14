---
description: Audit stale entries against the current code
---

Review knowledge that has gone stale.

1. Run `dejavu list --stale` to collect the stale entries
2. For each one, **actually read the current code** and compare

3. Act on the verdict:

   | Verdict | Action |
   | --- | --- |
   | Still correct | `dejavu touch <uid>` — resets freshness only |
   | Out of date, shared knowledge (`decision`, `convention`) | `dejavu edit <uid> --body -` to bring it up to date |
   | Out of date, local research cache (`feature`, `note`) | `dejavu rm <uid> --yes` and re-investigate. Do not patch it: a half-corrected cache carries no guarantee of correctness, which makes it worse than nothing |
   | Plan that is already finished | `dejavu edit <uid> --status done` |

4. Finish with a summary of how many entries you touched, edited, and removed

**Do not bulk-touch entries without checking them.** Touching an entry you have not
verified simply puts a "fresh" label on knowledge that may be wrong.
