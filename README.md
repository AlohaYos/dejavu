# dejavu

dejavu gives Claude Code a long-term memory — one that survives across sessions.

**You will hardly ever type a dejavu command.** After a one-time setup, Claude does the
remembering and the recalling itself. You just talk to it the way you always have.

---

## Table of contents

1. [What problem this solves](#what-problem-this-solves)
2. [Install (once)](#install-once)
3. [Add it to a project](#add-it-to-a-project)
4. [Scopes: what Claude remembers, and where](#scopes-what-claude-remembers-and-where)
5. [A day with dejavu](#a-day-with-dejavu)
6. [The four things you actually say](#the-four-things-you-actually-say)
7. [What gets stored](#what-gets-stored)
8. [Credentials are never stored](#credentials-are-never-stored)
9. [Working with a team](#working-with-a-team)
10. [When knowledge goes stale](#when-knowledge-goes-stale)
11. [Command reference](#command-reference)
12. [FAQ](#faq)

---

## What problem this solves

Say you spend hours reading through a program with Claude Code. Claude opens the files,
traces the call graph, works out why that one function is written so strangely. You make
progress. You close the session.

The next morning you open a fresh session and **Claude remembers none of it.** It opens
the same files, follows the same functions, and spends the same tokens arriving at exactly
the conclusion it reached yesterday.

The same thing happens *within* a long session. As the context fills up the answers get
worse, so you want to switch to a fresh one — but switching throws away everything Claude
learned.

This is where dejavu comes in.
dejavu is a local database that Claude writes what it learns into, and reads back from
when it needs it. A memory that outlives the session.

```
Session 1                      Session 2 (the next day)
──────────                     ────────────────────────
Claude reads the code          You: "continue from yesterday"
Claude works things out        Claude runs `dejavu resume`
Claude saves what it found     Claude reads yesterday's handoff note
                               Claude picks up exactly where it stopped
        │                                    ▲
        └────────── .dejavu/ ────────────────┘
                (a local database file)
```

Everything dejavu remembers stays on your own machine. No network access, no account, no
sync service. And it is free.

---

## Install (once, from the command line)

```bash
brew install alohayos/tap/dejavu
dejavu init --global
```

The second line installs dejavu's instructions into `~/.claude/`. That is the part that
teaches Claude Code how to use dejavu. Do it once and every project on your machine can
use it.

> The shorter alias `deja` works everywhere `dejavu` does. This guide uses `dejavu`.

To move to a newer version later: `brew upgrade dejavu`.

---

## Add it to a project

Run this at the root of a repository — new or existing, in any language.

```bash
dejavu init
```

**That is the last command you need to type.** It creates:

```
your-project/
├── .dejavu/                    ← new
│   ├── knowledge.db            (the database — not tracked by git)
│   ├── dejavu-triggers.md      (instructions for Claude — tracked by git)
│   └── config.toml
├── CLAUDE.md                   ← one line added, importing the instructions
└── .gitignore                  ← one line added, excluding the database
```

**It is safe on an existing project.** `dejavu init` does not touch your source code, and
it only *appends* lines to `CLAUDE.md` and `.gitignore` if they are not already there. Run
it twice and nothing bad happens.

**If you use Xcode**: `.dejavu/` lives at the repository root, outside `.xcodeproj`, so it
never ends up in a build. The one thing to avoid is putting it inside an Xcode 16
**synchronized group** (a "buildable folder"), because that feature adds every file in the
folder to the target automatically. At the repository root you are safe.

Then start Claude Code as usual:

```bash
claude
```

---

## Scopes: what Claude remembers, and where

```bash
dejavu init --global
dejavu init
```

What is the difference between these two? That difference is the **scope**.

Things you want remembered everywhere on this machine are stored as *your* memory (the
**user** scope). Things that only make sense inside one repository are stored as that
project's memory (the **project** scope).

### "Remember this for every project"

The user scope is for things that are about **you**, not about this repository. There is
no command or flag to learn. Words like *everywhere*, *always*, or *for every project* are
enough — Claude picks the user scope on its own.

```
You:     I always squash-merge. Remember that for every project.

Claude:  Saved to the user scope. I will remember it in your other projects too.
```

Good candidates for the user scope:

- **Preferences and working style** — "write PR bodies as bullet points", "commit messages
  in Japanese"
- **Quirks of your setup** — "I use the Homebrew Python, not the system one"
- **Context that crosses projects** — a note you want to carry into a different repository

There is one test when you are unsure: **would this still be true in another repository?**
If yes, it is user scope. If it is only true here, it is project scope.

- **project** — stored in `.dejavu/` inside the repository. Most knowledge lives here
- **user** — stored in `~/.config/dejavu/` and readable from every project. Personal notes
  and cross-project context

---

## A day with dejavu

### First thing: "let's pick up where we left off"

```
You:     continue from yesterday

Claude:  Yesterday you finished the CoreData migration and merged PR #23.
         The note says the next step is writing tests for the rollback path,
         and points at Sources/Store/Migration.swift:142.

         Shall I start there?
```

Claude has read **the handoff note you left yesterday**: what was finished, what comes
next, which file and which line to look at. No re-reading. None of Claude's usual "let me
get up to speed first".

### During the day: Claude uses it by itself

Claude remembers and recalls on its own. There is nothing for you to manage.

- **Before** it reads an unfamiliar module, it searches the knowledge base
- If it has looked into this before, it carries on from there
- When it works something out, it saves it
- When it makes a design decision, it records the decision **and the options it rejected** —
  the part that is normally lost forever

You will see Claude run a `dejavu` command now and then in the middle of its work. That is
normal. Think "ah, it is remembering something" and leave it be.

### Side tasks: "not now — remember it for later"

```
You:     That AppDelegate warning bugs me, but not now. Remember it for later.

Claude:  Saved as a plan. Back to the tests.
```

**This may be the most useful habit of all.** Something catches your eye mid-task. Stopping
to fix it derails the work you were doing; ignoring it means forgetting it. Just say
"remember it" and it is captured, with no interruption.

Later, say "show me the plans you saved" and Claude lists them so you can pick one up.

### End of day: "save what we did today"

```
You:     save what we did today

Claude:  Saved: "NEXT: write the rollback-path tests"
```

**The only habit you need to build is saying "save what we did today" when you finish
work.** One sentence at the end of a session, and the next one starts at full speed.
Forget it and dejavu takes no note — tomorrow starts from zero.

### Any time: "what have I been up to?"

```
You:     what was I working on this week?

Claude:  Wednesday
           - Merged the CoreData migration (PR #23)
           - Decided against SwiftData; the reason is recorded
         Tuesday
           - Investigated the rollback crash
```

Handy as raw material for a status report, and for the moment you come back after a few
days off and cannot remember where you were.

---

## The four things you actually say

Everything above comes down to these four phrases. There are no commands to memorise.

| Say this | Claude does this |
| --- | --- |
| **"continue from yesterday"** | Reads the last handoff note and resumes |
| **"save what we did today"** | Writes a handoff note for the next session |
| **"remember that for later"** | Records a side task without breaking your focus |
| **"what have I been working on?"** | Summarises recent activity |

---

## What gets stored

Knowledge is filed under one of six categories. Claude picks the right one, so you will
rarely think about this.

| Category | What it holds | Example |
| --- | --- | --- |
| `context` | Session handoff notes | "Done: migration merged. Next: rollback tests." |
| `plan` | Work put off until later | "Fix the AppDelegate warning" |
| `decision` | Design decisions **and rejected options** | "Chose UIKit over SwiftUI because…" |
| `feature` | How a piece of code works | "`Migration.swift` runs in three phases…" |
| `convention` | Team rules | "Every view model ends in `ViewModel`" |
| `note` | Everything else | |

---

## Credentials are never stored

`dejavu` refuses any text containing something that looks like an API key, a token, or a
private key. If Claude ever tries to save a snippet with a secret in it, it is stopped
right there.

---

## Working with a team

`dejavu` keeps two kinds of knowledge apart.

- **Shared knowledge** — architecture, design decisions, team conventions. Written out to
  `.dejavu/*.md`, **tracked by git**, and reviewed in pull requests like any other file
- **Local knowledge** — Claude's research cache. It lives only in the database, which is
  not tracked by git. Disposable, and yours alone

In other words: **your teammates get the decisions and the conventions, and none of your
"wait, what does this function do again" lookups.** When someone new clones the repository,
their Claude already knows why the architecture is the way it is.

The database itself is never committed. It is only an index, rebuildable from the Markdown
at any time.

---

## When knowledge goes stale

Code changes. Notes about the code do not. dejavu is built on that assumption.

Every entry records when it was last **checked against the real code**. Once that gets old
(7 days for research caches, 30 days for design decisions — adjustable in
`.dejavu/config.toml`), search results come back marked:

```
⚠ [a3f01c8b] Migration runs in three phases (feature) [STALE: 12 days since last check]
```

**A stale entry is not dropped from the results.** Old knowledge is still a useful clue,
and throwing it away would do more harm than flagging it. Claude is instructed to check a
stale entry against the current code before relying on it, then either keep it as is, fix
it, or discard it and investigate again.

When you want a spring clean, say "**review the knowledge that has gone stale**" and Claude
will go through them one by one against the current code, sorting out what to fix, what to
throw away, and what to leave alone.

---

## Command reference

Claude runs most of these for you, so you will rarely type one yourself — but here they
are for when you need them.

| Command | Description |
| --- | --- |
| `dejavu init` | Set up the current project |
| `dejavu init --global` | Install the instructions for every project (once) |
| `dejavu resume` | Show the last handoff note |
| `dejavu recent` | Show recent work, grouped by day (default: the last 2 days) |
| `dejavu search "<query>"` | Search the knowledge base |
| `dejavu list --stale` | List entries that need reviewing |
| `dejavu show <uid>` | Print an entry in full |
| `dejavu stats` | See how much has piled up |
| `dejavu rm <uid>` | Delete an entry |

Add `--help` to any of them for the full set of options.

---

## FAQ

**Do I have to remember to save things?**  
Claude saves as it works, following the instructions. The one habit worth building is
saying "save what we did today" before you stop. That is what makes "continue from
yesterday" work the next morning.

**Does my code get sent anywhere?**  
No. dejavu is a local database with no network access at all.

**Does it slow Claude down?**  
The opposite. A search finishes in tens of milliseconds and saves Claude from reading
several files. The instructions loaded on every turn are only about 30 lines.

**What if Claude saves something wrong?**  
Tell it: "that entry is wrong, fix it." Or delete it with `dejavu rm <uid>` — the UID is
the short code in brackets in every result.

**Does it work in Japanese?**  
Yes. Full-text search is designed so that **two-character Japanese words like 検索 or 認証**
— short enough that most search engines miss them — still match reliably.

**Can I use it without Claude Code?**  
You can. It is an ordinary CLI, so `dejavu add` and `dejavu search` work by hand. But it is
built for an agent to drive, and that is where it earns its keep.

**How do I remove it from a project?**  
Delete `.dejavu/` and remove the one imported line from `CLAUDE.md`. Nothing else was
touched.
