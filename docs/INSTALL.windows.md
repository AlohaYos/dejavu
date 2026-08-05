# Installing dejavu on Windows

dejavu runs on Windows — the code is cross-platform Python — but the one-line Homebrew
install in the [README](../README.md) is macOS/Linux only. On Windows you install from
source. Everything else in the README (enabling it in Claude Desktop, adding it to a
project, Obsidian, the handful of things you say) applies unchanged.

Tested on Windows 11 Pro with Python 3.10+.

## 1. Prerequisites

- **Python 3.10 or newer.** Install from <https://www.python.org/downloads/> and tick
  *"Add python.exe to PATH"* in the installer. Verify with `python --version` (or
  `py --version`).
- **git.** From <https://git-scm.com/download/win>, or `winget install Git.Git`.

## 2. Install dejavu

Clone the repository first:

```powershell
git clone https://github.com/AlohaYos/dejavu.git
cd dejavu
```

**Recommended: pipx.** pipx installs the `dejavu` command into an isolated environment
and places its launcher on your PATH, which sidesteps most "command not found" trouble:

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
pipx install .
```

Close and reopen your shell after `ensurepath` so the new PATH takes effect.

**Alternative: pip (editable).** Easier to update — a later `git pull` is enough — but the
console script lands in Python's `Scripts` directory, which is not always on every shell's
PATH. If `dejavu` then comes back "not found", see [§4](#4-if-dejavu-is-not-found):

```powershell
pip install -e .
```

Confirm it works:

```powershell
dejavu --help
```

Then teach Claude how to use it (the same as the README's second line):

```powershell
dejavu init --global
```

## 3. Register the MCP server for Claude Desktop / Cowork

On macOS, `dejavu install-mcp` finds the Claude Desktop config on its own. On Windows that
file lives elsewhere, so point the command at it explicitly with `--config`:

```powershell
dejavu install-mcp --config "$env:APPDATA\Claude\claude_desktop_config.json"
```

That path is usually `C:\Users\<you>\AppData\Roaming\Claude\claude_desktop_config.json`.
Restart Claude Desktop afterwards so it picks up the server.

> Prefer Claude Code (the CLI)? Register it there instead — no config path needed:
>
> ```powershell
> claude mcp add --scope user dejavu -- dejavu mcp
> ```

## 4. If `dejavu` is not found

`dejavu: command not found` after a `pip` install almost always means the console script
(`dejavu.exe`) landed in a `Scripts` directory that the current shell's PATH does not
include. This bites hardest under **Git Bash**, and therefore under **Claude Code**, which
runs its shell commands through Git Bash: **Git Bash's PATH is not the same as the Windows
PATH**, so a `Scripts` folder that Windows can see may be invisible to Git Bash (and a PATH
you just edited only applies to shells started afterwards).

Any one of these fixes it, most reliable first:

- **Use the `py` launcher.** `py.exe` lives in `C:\Windows` and is on every shell's PATH,
  so this always works — from any shell, with no PATH surgery:

  ```bash
  py -m dejavu resume
  ```

- **Install with pipx** (see §2) and reopen the shell — its launcher is placed on PATH for
  you.

- **Put a tiny wrapper on a directory already on your shell's PATH.** For an agent driving
  dejavu through Git Bash this is the sturdiest option: it gives one short, stable command
  string. Create `~/bin/dejavu` (with `~/bin` on the Git Bash PATH):

  ```bash
  #!/usr/bin/env bash
  exec py -m dejavu "$@"
  ```

- **Add the Scripts directory to PATH.** Find it with `pip show -f dejavu` (look for the
  `dejavu.exe` path), add that folder to your PATH, and restart the shell.

> **Using Claude Code?** Once `dejavu` (or `py -m dejavu`) resolves to a single stable
> command, add one allow-rule so you are not re-prompted on every call — in the project's
> `.claude/settings.json`:
>
> ```json
> "Bash(dejavu:*)"
> ```
>
> The failure mode to avoid is wrapping dejavu in a fresh `powershell -Command "..."`
> one-liner each time: because the strings differ, the prefix-based permission model
> cannot batch-approve them, and you get a flood of prompts.

> **A note on "mojibake".** If, while hunting for a missing `dejavu`, you see garbled
> Japanese, that is almost certainly **PowerShell's or cmd's own cp932 error text** being
> read as UTF-8 by Git Bash — not dejavu's output. dejavu forces its own streams to UTF-8
> (see §5), so its own output is correct even on a cp932 console.

## 5. Notes and known limitations

- **UTF-8 console — handled for you.** Japanese Windows uses the cp932 code page, which
  cannot print dejavu's `✓`/`⚠` and would otherwise crash almost every command (and
  corrupt `dejavu mcp`'s JSON-RPC). dejavu forces its own streams to UTF-8 at startup
  (`_force_utf8_streams` in `cli.py`), so you do not need to change the console code page
  yourself, and `PYTHONUTF8=1` is not required.
- **Obsidian sync detection.** Automatic write-mode detection recognises macOS sync paths
  (iCloud / CloudStorage). On Windows, if your vault lives in a synced folder (OneDrive,
  Dropbox, iCloud), set append-only explicitly so dejavu never rewrites a file mid-sync:

  ```powershell
  dejavu config write_mode append-only
  ```

  Run `dejavu obsidian doctor` to see the write mode dejavu will actually use.
- **Real-hardware testing.** UTF-8 output is verified on Windows 11; the remaining
  Windows-specific paths are covered by unit tests. Broad day-to-day use is still being
  validated, so please report anything that looks off.
