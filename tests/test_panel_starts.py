"""The panel actually starts, draws, and quits.

Everything else about panel.py is tested through its functions. This is the
one test that runs the program: curses initialisation, the first draw and the
quit key are exactly what a pure-function test cannot reach, and a panel that
crashes on startup would pass every other test in the suite.

It runs on a pseudo-terminal, because curses refuses to initialise on a pipe.
"""

from __future__ import annotations

import json
import os
import pty
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parent.parent
STARTUP_BUDGET_SECONDS = 20


@pytest.fixture
def transcripts(tmp_path):
    """A HOME holding a couple of sessions for the panel to read.

    The dates are relative to today: the panel opens on the last 30 days, so
    fixed dates silently fall out of the window and the test starts failing
    a month after it was written.
    """
    today = datetime.now(timezone.utc)
    home = tmp_path / "home"
    sessions = home / ".claude" / "projects" / "acme"
    sessions.mkdir(parents=True)
    (sessions / "one.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "timestamp": (today - timedelta(days=day)).strftime("%Y-%m-%dT10:00:00Z"),
                    "cwd": str(home / "dev" / "acme"),
                    "message": {
                        "model": "claude-sonnet-5",
                        "usage": {"input_tokens": 1000, "output_tokens": 100},
                    },
                }
            )
            + "\n"
            for day in (0, 1, 2)
        )
    )
    return home


def run_panel(home, keys, columns=120, lines=40):
    """Start the panel on a pty, feed it keys, return (exit status, screen)."""
    controller, terminal = pty.openpty()
    environment = dict(os.environ)
    environment.update(
        {
            "HOME": str(home),
            "TERM": "xterm",
            "LINES": str(lines),
            "COLUMNS": str(columns),
            # Never let a test write to the real cache directory.
            "HERDR_PLUGIN_STATE_DIR": str(home / ".cache"),
            # A PATH without the real quota-axi on it. The panel would run it
            # for real, and it makes network calls: no test reaches the
            # network, and the fallback lookup lands in the throwaway HOME.
            "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
        }
    )
    environment.pop("HERDR_AUTOSTART", None)

    process = subprocess.Popen(
        [sys.executable, str(REPOSITORY / "stats" / "panel.py")],
        stdin=terminal,
        stdout=terminal,
        stderr=terminal,
        env=environment,
        close_fds=True,
    )
    os.close(terminal)

    screen = bytearray()
    deadline = time.monotonic() + STARTUP_BUDGET_SECONDS
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                os.write(controller, keys)
            except OSError:
                # The panel closed its side of the pty: it is on its way out.
                break
            time.sleep(0.4)
            screen += read_available(controller)
        else:
            process.kill()
            pytest.fail(
                f"the panel never exited. Screen so far:\n{screen.decode(errors='replace')}"
            )
        screen += read_available(controller)
        if process.poll() is None:
            process.wait(timeout=10)
    finally:
        os.close(controller)
        process.wait(timeout=10)
    return process.returncode, screen.decode(errors="replace")


def read_available(fd):
    """Everything the panel has written so far, without blocking on the pty."""
    import select

    chunks = bytearray()
    while select.select([fd], [], [], 0)[0]:
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            break
        if not chunk:
            break
        chunks += chunk
    return chunks


def test_the_panel_starts_draws_and_quits(transcripts):
    status, screen = run_panel(transcripts, b"x")

    assert status == 0
    assert "acme" in screen, "the project read from the transcripts was never drawn"


def test_the_panel_leaves_no_traceback_behind(transcripts):
    _, screen = run_panel(transcripts, b"x")

    assert "Traceback" not in screen


def test_the_panel_starts_with_no_transcripts_at_all(tmp_path):
    # A fresh machine, or an agent that has never run.
    home = tmp_path / "empty-home"
    home.mkdir()

    status, screen = run_panel(home, b"x")

    assert status == 0
    assert "Traceback" not in screen


def test_the_panel_writes_its_cache_where_it_was_told(transcripts):
    run_panel(transcripts, b"x")

    assert (transcripts / ".cache" / "usage-cache.json").is_file()
