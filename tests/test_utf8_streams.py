"""Tests for `_force_utf8_streams`.

The function only does anything on Windows, where a real reconfigure would touch the
actual process streams. So the platform and the streams are both monkeypatched and we
assert on what the function *tried* to do, not on real console state.
"""

from __future__ import annotations

import sys

import pytest

from dejavu import cli


class _Recorder:
    """A stand-in stream that records the kwargs passed to reconfigure()."""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self._raises = raises

    def reconfigure(self, **kwargs: object) -> None:
        if self._raises is not None:
            raise self._raises
        self.calls.append(dict(kwargs))


class _NoReconfigure:
    """A stream from before io.TextIOWrapper.reconfigure existed (getattr -> None)."""


def _install(monkeypatch: pytest.MonkeyPatch, stdin, stdout, stderr) -> None:
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)


def test_noop_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    streams = (_Recorder(), _Recorder(), _Recorder())
    _install(monkeypatch, *streams)
    cli._force_utf8_streams()
    assert all(s.calls == [] for s in streams)


def test_reconfigures_to_utf8_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    stdin, stdout, stderr = _Recorder(), _Recorder(), _Recorder()
    _install(monkeypatch, stdin, stdout, stderr)
    cli._force_utf8_streams()
    for s in (stdin, stdout, stderr):
        assert s.calls, "reconfigure should have been called"
        assert s.calls[0]["encoding"] == "utf-8"
    # Only stdout pins its newline, so `dejavu mcp` JSON-RPC framing survives Windows
    # text mode; stdin and stderr keep universal-newline behaviour.
    assert stdout.calls[0].get("newline") == ""
    assert "newline" not in stdin.calls[0]
    assert "newline" not in stderr.calls[0]


def test_missing_reconfigure_is_tolerated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    _install(monkeypatch, _NoReconfigure(), _NoReconfigure(), _NoReconfigure())
    cli._force_utf8_streams()  # must not raise


def test_reconfigure_errors_are_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    boom = _Recorder(raises=ValueError("cannot reconfigure after read"))
    after = _Recorder()
    # stdout raises; the loop must carry on and still reconfigure stderr.
    _install(monkeypatch, _Recorder(), boom, after)
    cli._force_utf8_streams()  # must not raise
    assert after.calls and after.calls[0]["encoding"] == "utf-8"
