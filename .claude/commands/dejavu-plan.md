---
description: Save, list, and resume deferred plans
---

Arguments: $ARGUMENTS

## No arguments — list and resume

1. Run `dejavu list --category plan --status proposed`
2. Present the plans as a table (title / status / last updated) and ask which to resume
3. Once chosen, read it in full with `dejavu show <uid>`, mark it
   `dejavu edit <uid> --status accepted`, and start work
4. When it is finished: `dejavu edit <uid> --status done`

## With arguments — save a plan without breaking focus

Save $ARGUMENTS as a plan **without interrupting the work currently in progress**.

```
dejavu add "<one-line plan title>" --category plan --status proposed \
  --keywords "..." --body -
```

The body should densely cover: motivation, what to do, which files are involved, and
any options already ruled out.

Then report the UID and **return to what you were doing**. Not getting derailed is the
entire point of this command.
