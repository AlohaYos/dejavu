---
description: Save this session's work as context so the next session can pick it up
---

Store what happened in this session in dejavu's `context` category.

1. First run `dejavu search "next" --category context --limit 3` to see whether a
   handoff note already exists.
   - Continuing the same thread of work? Overwrite it: `dejavu edit <uid> --body -`
   - Different work? Add a new entry with `dejavu add`

2. Write the body in this order, densely. No long narrative.

   ```
   ## Done
   - (merged / verified work, with PR or commit references where they exist)

   ## Next
   - (what the next session should start on — put it on the first line)

   ## Artefacts
   - (file paths, function names, commands, and values that are expensive to rediscover)

   ## Open questions
   - (if any)
   ```

3. Title the entry `NEXT: <what to do next>`. That way it is the first thing the user
   sees tomorrow when they search for where they left off.

4. Hand-pick 5-10 keywords. Always include `next-steps` and `where-we-left-off`.

Report the UID and title of the entry you saved.
