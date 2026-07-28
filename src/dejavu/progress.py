"""Telling the user that something slow is happening, and why.

Starting the linking model takes anywhere from a second to half a minute the first time,
because a 1.2GB file has to be read off disk. Half a minute of silence reads as a hang,
and a hang is what makes people press Ctrl-C and never turn the feature on again.

Three rules hold this together.

**Nothing is printed for a wait the user would not have noticed.** If everything was
already running, the work finishes in milliseconds and a line that appears and vanishes is
pure noise. Output starts only once `QUIET_FOR` has passed.

**The elapsed seconds are always shown.** A number that keeps moving is the difference
between "this is slow" and "this is broken", and it costs one field to provide.

**Progress goes to stderr, never stdout.** stdout carries the result — a line a human
reads, or the JSON `--json` promised. Mixing the two means `--json` output that no parser
can read, so the separation is not a style choice.

The words avoid naming Ollama. Someone who installed it by pasting a command they did not
read gains nothing from "starting Ollama"; they do gain something from "getting ready to
link your notes". The name is used where the user has to act on it by name — installing
it, pulling a model, or reading `doctor` — and nowhere else.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import TextIO

# A wait shorter than this is not worth mentioning.
QUIET_FOR = 0.5

# Redrawing faster than this produces a flicker nobody can read.
REDRAW_EVERY = 0.5


class Progress:
    """A single line that updates in place on a terminal, and one line per step elsewhere."""

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        isatty: bool | None = None,
        quiet_for: float = QUIET_FOR,
    ) -> None:
        self._stream = stream if stream is not None else sys.stderr
        self._clock = clock
        self._tty = self._stream.isatty() if isatty is None else isatty
        self._quiet_for = quiet_for
        self._started = self._clock()
        self._last_drawn = 0.0
        self._message = ""
        self._dirty = False  # something was written that still needs clearing

    @property
    def elapsed(self) -> float:
        return self._clock() - self._started

    def step(self, message: str) -> None:
        """Move to a new stage. On a terminal this replaces the line; elsewhere it adds one."""
        self._message = message
        if not self._tty:
            if self.elapsed >= self._quiet_for:
                self._stream.write(f"{message}\n")
                self._stream.flush()
                self._dirty = True
            return
        self._last_drawn = 0.0  # a new stage always redraws
        self.tick()

    def tick(self, suffix: str = "") -> None:
        """Refresh the current line. Safe to call in a tight loop; it rate-limits itself."""
        if not self._tty or not self._message:
            return
        now = self.elapsed
        if now < self._quiet_for:
            return
        if self._last_drawn and now - self._last_drawn < REDRAW_EVERY:
            return
        self._last_drawn = now
        tail = f" {suffix}" if suffix else f" {now:.0f}s"
        line = f"  {self._message}…{tail}"
        self._stream.write("\r" + line.ljust(78)[:78])
        self._stream.flush()
        self._dirty = True

    def done(self, message: str | None = None) -> None:
        """Clear the working line. The *result* is printed by the caller, on stdout."""
        if self._dirty and self._tty:
            self._stream.write("\r" + " " * 78 + "\r")
        if message and self._dirty:
            self._stream.write(f"{message}\n")
        if self._dirty:
            self._stream.flush()
        self._dirty = False
        self._message = ""
