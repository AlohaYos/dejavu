# Installing dejavu on Windows

dejavu runs on Windows — the code is cross-platform Python — but the one-line Homebrew
install in the [README](../README.md) is macOS/Linux only. On Windows you install from
source with `git` and `pip`. Everything else in the README (enabling it in Claude
Desktop, adding it to a project, Obsidian, the handful of things you say) applies
unchanged.

Tested on Windows 11 Pro with Python 3.10+.

## 1. Prerequisites

- **Python 3.10 or newer.** Install from <https://www.python.org/downloads/> and tick
  *"Add python.exe to PATH"* in the installer. Verify with `python --version`.
- **git.** From <https://git-scm.com/download/win>, or `winget install Git.Git`.

## 2. Install dejavu from source

Open **PowerShell** and run:

```powershell
git clone https://github.com/AlohaYos/dejavu.git
cd dejavu
pip install -e .
```

`pip install -e .` installs dejavu in editable mode, so a later `git pull` is enough to
update — there is no Homebrew formula to upgrade.

Confirm it is on your PATH:

```powershell
dejavu --help
```

If `dejavu` is not found, the Python `Scripts` directory is not on your PATH. Reopen
PowerShell, or run it as a module: `python -m dejavu --help`.

Then teach Claude how to use it (the same as the README's second line):

```powershell
dejavu init --global
```

## 3. Register the MCP server for Claude Desktop / Cowork

On macOS, `dejavu install-mcp` finds the Claude Desktop config on its own. On Windows
that file lives elsewhere, so point the command at it explicitly with `--config`:

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

## 4. Notes and known limitations

- **UTF-8 console — handled for you.** Japanese Windows uses the cp932 code page, which
  cannot print dejavu's `✓`/`⚠` and would otherwise crash almost every command (and
  corrupt `dejavu mcp`'s JSON-RPC). dejavu forces its own streams to UTF-8 at startup
  (`_force_utf8_streams` in `cli.py`), so you do not need to change the console code page
  yourself.
- **Obsidian sync detection.** Automatic write-mode detection recognises macOS sync
  paths (iCloud / CloudStorage). On Windows, if your vault lives in a synced folder
  (OneDrive, Dropbox, iCloud), set append-only explicitly so dejavu never rewrites a
  file mid-sync:

  ```powershell
  dejavu config write_mode append-only
  ```

  Run `dejavu obsidian doctor` to see the write mode dejavu will actually use.
- **Real-hardware testing.** The Windows-specific code paths are covered by unit tests;
  broad day-to-day use on Windows is still being validated, so please report anything
  that looks off.
