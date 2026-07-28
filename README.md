# dejavu

**Memory for Claude.**

When you work with Claude, things move fast in the moment. But close the window, come
back the next day, and Claude remembers none of it. You explain the background again.
You have it look up the same things again.

dejavu gives Claude somewhere on your own machine to write down what it worked out, and
reads it back when it is needed. With it in place, Claude can start from "where we left
off yesterday".

dejavu also pairs with **Obsidian**, a free notes app. Together, what Claude remembers
becomes notes *you* can read back — and the same knowledge becomes available from every
way you reach Claude: the terminal, Claude Desktop chat, Cowork, and Xcode.  
There is also an optional feature that reads the notes in an Obsidian vault and links the
related ones to each other.

Everything stays on your own machine. No account, no subscription, and nothing leaves it.

[日本語](README.ja.md)

---

## Table of contents

1. [What problem this solves](#what-problem-this-solves)
2. [What dejavu remembers](#what-dejavu-remembers)
3. [How this differs from Claude's own memory](#how-this-differs-from-claudes-own-memory)
4. [What changes when you add Obsidian](#what-changes-when-you-add-obsidian)
5. [What goes where](#what-goes-where)
6. [What it looks like in use](#what-it-looks-like-in-use)
7. [Install](#install)
8. [Using it from each surface (chat, Cowork, terminal, Xcode)](#using-it-from-each-surface)
9. [If you already use Obsidian](#if-you-already-use-obsidian)
10. [FAQ](#faq)
11. [Appendix: connecting a pile of your own notes](#appendix-connecting-a-pile-of-your-own-notes)
12. [Going deeper](#going-deeper)

---

## What problem this solves

Let us start with the situations dejavu is for. If any of these sound familiar, it will
help.

### Situation 1: tomorrow, you start over

You spend hours working something out with Claude. It opens file after file, traces how
things fit together, works out why one piece is written so strangely. You decide on an
approach. Real progress. You close the window.

The next morning you open a fresh session, and Claude **remembers none of it.** It opens
the same files, follows the same trail, spends the same tokens, and arrives at exactly the
conclusion it reached yesterday. You explain the background from scratch.

### Situation 2: you cannot move a long conversation somewhere fresh

As a conversation gets long, the answers get worse. You want to move to a new one — but
the moment you do, every piece of shared context is gone. So you either put up with the
long session or start explaining all over again.

### Situation 3: you are researching something you already researched

"I'm sure I looked this up before" — but you cannot remember where you wrote it down. Or
you never wrote it down at all. Either way you do the work twice.

### What dejavu does about it

All three have the same root cause: **too little of what Claude learns is retained.**

dejavu gives it a place on your machine to write things down. Claude saves there
automatically as it works, and reads back automatically when it needs to.

```
Day 1                            Day 2
────────                         ────────
Claude investigates              You: "continue from yesterday"
Claude works it out              Claude reads what it wrote
Claude writes it down            Claude picks up where it stopped
      │                                    ▲
      └────────── .dejavu/ ────────────────┘
              (a store on your machine)
```

---

## What dejavu remembers

The previous section described the problem. This one covers what you actually get.

Roughly, dejavu keeps four kinds of thing:

| Kind | Example |
| --- | --- |
| **Where you stopped** | "Finished the migration. Next: rollback tests" |
| **What an investigation found** | "This runs in three phases, and here is why" |
| **Decisions** | "Chose B over A, because…" |
| **Work put off** | "Not touching that warning today. Fix it later" |

Which lets conversations like this happen:

```
You:     continue from yesterday

Claude:  Yesterday you got the document reorganised as far as chapter 3 and stopped
         there. The next step was checking the references. Shall we carry on?
```

```
You:     what have I been working on?

Claude:  Over the last three days: Monday you settled the approach, Tuesday you drafted
         it, and Wednesday you were investigating a bug.
```

### There are no commands to learn

This is the part that matters most. **You will hardly ever type a dejavu command.**

When to save and when to recall is decided by Claude, from the flow of the conversation.
You just talk to it the way you always have. In practice, there are about four things
worth saying deliberately:

| Say this | Claude does this |
| --- | --- |
| "continue from yesterday" | Reads the last handoff note and resumes |
| "save what we did today" | Writes today up for next time |
| "remember that for later" | Records a side task without breaking your focus |
| "note down where we've got to" | Saves this conversation's state for a different session |
| "what have I been working on?" | Summarises recent activity |

---

## How this differs from Claude's own memory

"Claude Code already has memory of its own (`CLAUDE.md`, `MEMORY.md`). Isn't that enough?"

—— It does. And **it does not compete with dejavu. They do different jobs, so use both.**

What Claude Code has is a **notepad** left open on the desk. It is opened automatically at
the start of a conversation, so you can read and write it straight away with no setup. But
the notepad is thin: **there is a limit to how much fits, and no way to search what has
piled up.** The more that gets written, the more the older pages are pushed out and lost.

dejavu is more like a **diary**. What you did, what you decided, what comes next — written
down with the date on it. Then, when you say "continue from yesterday", it opens that
day's page. **Because it is not all re-read every time, no number of volumes slows the
conversation down.** A page from six months ago is still there if you go looking.

The other difference is **reach**. Claude Code's notepad belongs to Claude Code on that one
machine; chat and Cowork cannot see it. With dejavu, every surface reads and writes the
same diary.

| | Claude's own memory | dejavu |
| --- | --- | --- |
| Think of it as | **a thin notepad on the desk** | **a diary / daily log** |
| Good at | working immediately, no setup | being found and pulled back out |
| As it grows | anything past the limit is buried, then lost | nothing gets buried |
| Where it works | Claude Code only | every surface |

To be straight about it: **if you have few notes, one project, and only ever use Claude
Code, Claude's own memory is enough.** dejavu starts to pay off once knowledge accumulates.

> The mechanics (how `CLAUDE.md` and auto memory divide the work, the size limit on what
> is loaded, how claude.ai's memory relates to all this) are in
> [REFERENCE.md](docs/REFERENCE.md).

---

## What changes when you add Obsidian

Everything above works with **dejavu alone.** Obsidian is not required.

But two gaps remain if you stop there:

- **You cannot read back what was saved.** dejavu's store is a database, so Claude reads
  and writes it happily, but you cannot open it
- **Claude Desktop chat cannot use it.** More on why below — chat has no way to reach
  files on your machine

Adding Obsidian solves both.

### What Obsidian is

[Obsidian](https://obsidian.md) is a free notes app. What matters here is that its notes
are **not stored in a proprietary format** — they are ordinary text files (Markdown)
sitting in a folder on your machine.

Obsidian calls that folder a **vault**. It is a folder, with text files in it.

### The three memories

The previous section called Claude's own memory a **notepad** and dejavu a **diary**.
Following that line, Obsidian is **documents filed on a bookshelf**.

Where a diary records *when you did what*, these documents hold **knowledge you will reach
for again**. They are filed by subject, they stay on the shelf after a project ends, and
they can still be pulled out years later. And the decisive difference: **you can take them
down and read them yourself.**

| | Claude's own memory | dejavu | Obsidian |
| --- | --- | --- | --- |
| Think of it as | **a notepad on the desk** | **a diary / daily log** | **documents on a bookshelf** |
| What goes in | whatever it just noticed | what you did and decided today | knowledge you reach for again; facts about you |
| When it is read | every time, automatically | when that project comes up | whenever it might be relevant, any project |
| How long it lasts | pushed out as it fills | as long as the project runs | indefinitely |
| **Can you read it?** | no | no | **yes** |
| Where it works | Claude Code only | every surface | every surface |

### What dejavu does here

Notepad, diary and bookshelf all do different jobs, so they are not replacements for one
another — you **stack them.** dejavu is what covers the gaps in Claude's own memory and in
Obsidian: hand it something and it files it into the diary or the bookshelf as
appropriate, on its own.

### Change 1: you can read it back yourself

When dejavu writes into Obsidian, what it saved becomes a text file — plain text, nothing
more. **Claude's memory becomes your notes.**

You can open them, search them, link them together, and read them on your phone. The
uneasy "I have no idea what Claude thinks it knows" feeling goes away — and if something
was remembered wrongly, you can edit the text.

### Change 2: every surface reaches the same knowledge

There are several ways to reach Claude: Claude Code in the terminal, Claude Desktop chat,
Cowork, and the Claude Agents built into Xcode. Same Claude, slightly different abilities.

**A vault is just a folder, so any surface that can read files can read it directly.**
That covers Claude Code in the terminal and Xcode's Claude Agents. But **Claude Desktop
chat cannot read files at all**, and while Cowork can read Obsidian's data, you have to
reattach the folder by hand every time you use it.

This is the gap dejavu covers. It is already reachable from all four ways of getting to
Claude, so if you tell dejavu where the vault is, **dejavu reads and writes the vault on
Claude's behalf** — and the same notes become available everywhere.

| | Terminal | Xcode | Desktop chat | Cowork |
| --- | :-: | :-: | :-: | :-: |
| Obsidian on its own | ✅ | ✅ | ❌ no | △ attach the folder each time |
| **Through dejavu** | ✅ | ✅ | ✅ | ✅ |

---

## What goes where

With Obsidian connected there are now two places to save things, which raises the
question of which one to use. The rule is short.

> **dejavu remembers the project. Obsidian remembers you.**

One diary per project; one bookshelf across all of them. Framed that way it is hard to
get wrong.

In more detail:

| Where | What goes there | Example |
| --- | --- | --- |
| `.dejavu/` (inside the project) | **This project only** | "Stopped here", "next: that bug" |
| `docs/knowledge/` | This project, **shared with the team** | "How we use this API" |
| Obsidian `Knowledge/` | **True in any project** | "This pattern has a trap in it" |
| Obsidian `UserInfo/` | **You** | Background, preferences, how you work |
| Obsidian `Research/` | **What an investigation found** | "A vs B, measured" |

One question settles it:

> **Would this still be true in a different project?**
> If yes, Obsidian. If it only holds here, dejavu.

### Claude does the sorting

You are not asked to make this call every time. **Claude decides.** When it is unsure,
it asks you:

```
Claude:  What we just found looks general rather than specific to this project.
         Save it to Obsidian as shared knowledge?

         1. yes   2. no   3. always, stop asking   4. never, stop asking
```

Pick 3 or 4 and it stops asking. You can change your mind later.

---

## What it looks like in use

Here is all of the above as actual conversation — once for someone writing code, once for
someone who is not.

### If you write code

**Starting the day**

```
You:     continue from yesterday
```

> Yesterday you finished Phase 4e of the recognition module split and left Phase 5 for
> later. The files that changed were `FoodAnalysisService.swift` and `GIService.swift`.
> Shall we carry on?

**Mid-task, after a fix**

> Fixed. The cause was that `safeAreaInsets` reads as 0 inside `ignoresSafeArea()`.
>
> That is not specific to this app — it holds for SwiftUI generally.
> Save it to Obsidian as shared knowledge?

**Six months later, in a completely different app**

```
You:     the layout is shifted down here
```

> You have hit this before. There is a note in Obsidian's `Knowledge/` saying
> `safeAreaInsets` reads as 0 inside `ignoresSafeArea()`. The same fix should apply.

Knowledge follows you across projects, so **you never run the same investigation twice.**
What you worked out six months ago reaches the you of today.

**Handing something to the team**

Put a text file in `docs/knowledge/` and git shares it with everyone. dejavu searches it
just the same, so moving something there changes nothing about how it feels to use.

### If you do not write code

You do not need a project folder at all — just connect a vault.

**If your work is research**

```
You:     what were the conditions on that grant I looked into last week?

Claude:  It is in Obsidian's Research/. From the 20 July investigation: fewer than 50
         employees, applications close at the end of September, three documents required.
```

**If your work is writing**

```
You:     edit this draft the usual way

Claude:  There are style notes in UserInfo/: short sentences, no noun-ending phrases,
         always gloss the jargon. Editing along those lines.
```

The habit is exactly the same as for the code case: **say "remember this"**, and it comes
back next time you ask. And what comes back is something you can open and read yourself.

---

## Install

There are at most five steps. Work down the list; it takes about ten minutes (step 5
adds a little more, for the model download).

| | Step | Who needs it |
| --- | --- | --- |
| 1 | Install dejavu | **everyone** |
| 2 | Connect Obsidian | optional (recommended) |
| 3 | Enable it in Claude Desktop | if you use chat or Cowork |
| 4 | Add it to a project | if you write code |
| 5 | Link your notes to each other | optional (needs Ollama) |

### 1. Install dejavu

Open Terminal, paste these two lines, and press Enter after each.

```bash
brew install alohayos/tap/dejavu
dejavu init --global
```

The first installs dejavu itself. The second teaches Claude how to use it. Both are
one-time; you never need to run them again.

> - If you do not have [Homebrew](https://brew.sh), install that first
> - The shorter alias `deja` works everywhere `dejavu` does
> - When a newer version comes out, `brew upgrade dejavu` updates it

### 2. Connect Obsidian (optional)

Never used Obsidian? It is free, and as written above a vault is just a folder.

First, set Obsidian up:

1. Download and install it from <https://obsidian.md/download>
2. Open it and choose **Create new vault**
3. Give it a name and a location. If you have no preference, `MyVault` in your Documents
   folder is fine (→ [official guide](https://help.obsidian.md/vault))

Then tell dejavu where it is. Back in Terminal — replace `~/Documents/MyVault` with
whatever you chose in step 3:

```bash
dejavu obsidian init ~/Documents/MyVault
dejavu obsidian doctor
```

The second command, `doctor`, inspects the current state and prints it. If you see the
vault path and how dejavu intends to write to it, it worked.

This creates three folders in the vault — `Knowledge/`, `UserInfo/` and `Research/` —
unless they already exist. **Nothing else in the vault is touched.**

#### Whether the vault is on this Mac or in the cloud changes how it writes

| Vault location | Readable on your phone | How dejavu writes |
| --- | :-: | --- |
| A folder on this Mac | no | creates, appends, **rewrites** |
| iCloud / Dropbox / Google Drive / Obsidian Sync | yes | creates and appends only |

It works out which case applies on its own, and `dejavu obsidian doctor` will tell you
which — and why — at any time.

### 3. Enable it in Claude Desktop

To use dejavu from chat or Cowork, run:

```bash
dejavu install-mcp
```

Then quit Claude Desktop and open it again. Chat and Cowork can now reach dejavu.

### 4. Add it to a project folder

In the project folder (the repository), run:

```bash
cd ~/your-project
dejavu init
```

It creates a `.dejavu/` folder and appends a single line each to `CLAUDE.md` and
`.gitignore`. **It never touches your source code.** It is safe on a project already in
progress, and safe to run twice by accident.

Running it in a project is what creates that project's diary.

### 5. Link your notes to each other (optional)

When dejavu writes a note into Obsidian, this **links it to your earlier notes on the same
subject**. "I think I looked into this before" becomes something you notice without going
looking for it.

It needs a model running on your own machine ([Ollama](https://ollama.com)).
**Everything above works without it.**

1. Install Ollama from <https://ollama.com/download> and start it
2. Run these three lines in Terminal

```bash
ollama pull bge-m3
dejavu config relate embed
dejavu obsidian relate --backfill
```

In order: fetch the model that reads text, tell dejavu to use it, and let it read the
notes already in your vault. Only the third line takes a few minutes.

That is all. From here on, links appear as notes are written.

- Check it is working → `dejavu obsidian doctor`
- **While Ollama is stopped, only the links wait.** Notes save as usual and are linked
  the next time it runs. To do it now: `dejavu obsidian relate --start` (which offers to
  start it for you)
- Turn it off → `dejavu config relate off` (links already written stay)
- Nothing leaves your machine

The settings are in
[REFERENCE](docs/REFERENCE.md#automatic-linking-between-notes-ollama).

---

## Using it from each surface

Once installed, every surface reaches the same knowledge. They differ slightly in how,
so here is each in turn.

### Claude Desktop — chat

Chat cannot read files on your machine, but with step 3 done, dejavu reads and writes on
its behalf.

```
You:     write a 200-word speaker bio from my profile

Claude:  (reads UserInfo/Profile.md in Obsidian)
         In 1998, developed a Japanese input system for the Apple Newton MessagePad. …
```

```
You:     remember that approach from now on, everywhere

Claude:  Saved to Obsidian's Knowledge/. It will come back in other chats and in Cowork.
```

> **Say which project you mean** — "about Project A, could you write up the minutes"
> and so on. Chat and Cowork have no way of knowing which folder you are working in.
> Without a project named, only your personal knowledge and the vault are used.

### Claude Desktop — Cowork

Cowork uses the same mechanism as chat, which means **you do not have to attach the
Obsidian folder to Cowork by hand.**

```
You:     where did this project get to?

Claude:  (checks the project's records, then Research/ in Obsidian)
         Phase 4e is complete and Phase 5 was deferred.
         There is also a related measurement from 17 July.
```

### Claude Desktop — Code

It can read files on your machine directly, so it behaves exactly like Claude Code in the
terminal. Nothing extra to configure.

### Claude Code in the terminal

Change to the project folder and start it as usual:

```bash
cd ~/your-project
claude
```

Then just talk. Saving and recalling are Claude's judgement calls. The only things worth
saying deliberately are the four phrases listed earlier.

### Xcode's Claude Agents

The Claude Agent built into Xcode 26 and later reads files just like the terminal does, so
it works as-is. The project's `CLAUDE.md` is picked up automatically, so as long as step 4
is done there is nothing else to configure.

> Occasionally you may see `dejavu: command not found` — Xcode launches the agent in an
> environment where dejavu is not on the path. The fix is in [REFERENCE.md](docs/REFERENCE.md).

---

## If you already use Obsidian

If you already keep a vault, the question on your mind is whether dejavu will make a mess
of it. There are three things worth explaining, in turn.

### 1. Your existing notes are never modified

**Not one note you wrote will be changed.**

Every note dejavu creates carries `source: dejavu` at the top of the file. **A note
without that marker is read-only to dejavu, permanently** — no appends, no rewrites.

If dejavu is ever asked to write to one, it stops with an error:

```
error: my-handwritten-note.md was not written by dejavu
       (no `source: dejavu` in its frontmatter).
       Notes you wrote by hand are never modified.
```

### 2. Your folder structure stays yours

`Knowledge/` starts empty. Build subfolders however you like — PARA, Zettelkasten,
Johnny.Decimal, whatever you already use.

dejavu **files notes into folders that already exist and never creates one of its own.**
Classification is also written into the top of each note, so rearranging folders later
does not break search or grouping.

### 3. You choose what it can see

Folders you do not list are not read at all. The default is just `Knowledge/`, `UserInfo/`
and `Research/`, so a personal journal or your travel notes will not surface mid-task.

To match names you already use:

```bash
dejavu config userinfo_dir Profile     # use Profile/ instead of UserInfo/
```

---

## FAQ

**Do I have to remember to save things?**
Claude saves as it works, so mostly no. The one habit worth building is saying "save what
we did today" before you stop. That is what makes "continue from yesterday" work.

**Does anything get sent anywhere?**
No. dejavu never talks to anything outside your machine, and needs no account. With
[note linking](#5-link-your-notes-to-each-other-optional) turned on, the only thing that
ever sees your text is the Ollama running on that same machine.

**Does it slow Claude down?**
It speeds things up. A search finishes in tens of milliseconds and saves Claude from
re-reading several files. The instructions loaded each turn are about 40 lines.

**What if Claude remembers something wrong?**
Tell it: "that note is wrong, fix it." To delete one outright, `dejavu rm <uid>` — the uid
is the short code in brackets in every search result.

**What if the project and Obsidian disagree?**
Both are shown, and you are asked which to adopt. dejavu never decides silently: a wrong
answer written into the vault would follow you into every other project.

**Does it work in Japanese?**
Yes. Two-character Japanese words like 検索 and 認証 — short enough that most search
mechanisms miss them — are matched reliably by design.

**Is Obsidian required?**
No. dejavu is complete on its own. Adding Obsidian lets you read the knowledge back
yourself, makes it reachable from chat and Cowork, and lets you keep far more of it.

**Can people who do not program use it?**
Yes. Steps 1 and 2 are enough (plus 3 if you want chat) to run it as your personal
knowledge store. Step 4 is not needed.

**Claude Code already has auto memory (MEMORY.md) — why this too?**
They do different jobs and work together. Auto memory loads every session but is capped at
its first 200 lines and has no search. dejavu stays out of the context and searches on
demand, so it keeps working as the knowledge grows. See
[How this differs from Claude's own memory](#how-this-differs-from-claudes-own-memory).

**Can I use it without Claude Code?**
You can. It is an ordinary CLI command, so `dejavu add` and `dejavu search` work by hand.
It is built for an agent to drive, though, and that is where it earns its keep.

**How do I stop using it?**
Delete `.dejavu/` from the project and remove the one line added to `CLAUDE.md`. Nothing
was left anywhere else. Vault notes are plain text files and simply stay where they are.

---

## Appendix: connecting a pile of your own notes

As described in "Link your notes to each other", dejavu can link the notes it saves into
Obsidian to your other notes automatically. It leaves the notes it did not write alone,
though — that restraint is what stops it from rewriting your own notes behind your back.

But you may well want this:

> I want to pull every document on my computer into Obsidian and link them all together.
> Having an AI do that work would mean handing private material to a service somewhere
> else. I want the linking done using nothing but what is on this machine.

That is what this utility is for.  
Once notes are linked to each other like this, dejavu can follow the trail from one to the
next, and gets much better at bringing back things you had forgotten you knew.

### The one feature that changes your own vault files

The rule is that dejavu only touches notes it wrote itself. This is the exception.
**It adds links to notes you wrote.** Because it works on your own notes directly, it is
guarded from several directions at once — confirmation before it runs, and undo after.

### When to use it

After moving a stack of scattered files into Obsidian, when you want **the ones about the
same subject linked to each other**. "I'm sure I looked into this before" becomes
something you notice without going looking, and related material becomes easier to find.
Think of it as doing the work of linking each note by hand, on your behalf, in one pass.

### What to say to Claude

Make a folder in your vault (`Inbox`, say), drop the files in, and ask:

> "Link up the notes I put in Inbox"

dejavu looks first and answers with what it found:

> "42 notes. I can add 118 links between the ones about the same subject. 12 of them are
> notes you wrote, so those files would change. This can be undone. Go ahead?"

**Nothing changes until you say yes.**

### Checking the result

Open one of the notes in Obsidian and you will find this at the end:

```
## Related

- [[Sorting out receipts]]
- [[Filing as a sole trader]]
```

Click a link to jump straight to the other note. Open Obsidian's **graph view** and the
connections between your material start to become visible.

### Removing the links

Tell Claude "undo those links" and **only the added links go away**. Anything you wrote
after they were added stays where it is, so there is nothing to worry about.

The files as they were before are backed up elsewhere on your machine (and dejavu tells
you where it put them).

> - This feature uses [Ollama](#5-link-your-notes-to-each-other-optional). Finish step 5
>   before running it
> - Your notes are never sent off your machine. Everything happens locally
> - Text files (`.txt`) are converted to `.md` before they are linked — you are asked first
> - Settings and troubleshooting are written up in
>   [REFERENCE.md](docs/REFERENCE.md#connecting-a-pile-of-your-own-notes)

---

## Going deeper

This README covers what you need to get started. The finer detail lives in separate files.

- **[REFERENCE.md](docs/REFERENCE.md)** — every command, config options, how the stores
  work, MCP tools, categories, staleness, troubleshooting
- [BACKLOG.md](docs/BACKLOG.md) — what is deliberately deferred

---

MIT License
