"""Enable ``python -m dejavu`` / ``py -m dejavu``.

This matters most on Windows. The pip console script (``dejavu.exe``) is installed into a
Scripts directory that is on the *Windows* PATH but frequently *not* on Git Bash's PATH,
so an agent (e.g. Claude Code) that shells out through Git Bash gets ``command not
found``. The ``py`` launcher lives in ``C:\\Windows`` and is therefore always visible from
every shell, which makes ``py -m dejavu ...`` a dependable, shell-agnostic way to run
dejavu when the bare ``dejavu`` command cannot be resolved.
"""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
