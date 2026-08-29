"""The usage cache: what it saves, when it re-reads, and how it fails.

collect() walks every transcript under ~/.claude/projects on each refresh. The
cache is what keeps that from re-parsing hundreds of megabytes every two
minutes, so its invalidation rule is load-bearing: too eager and the panel is
slow, too lazy and it shows figures that no longer exist on disk.
"""

from __future__ import annotations

import json
import os

import pytest


@pytest.fixture
def sessions(panel, tmp_path, monkeypatch):
    """A fake ~/.claude/projects and a cache file, both under tmp_path."""
    projects = tmp_path / "projects"
    projects.mkdir()
    cache = tmp_path / "cache" / "usage-cache.json"
    monkeypatch.setattr(panel, "PROJECTS_DIR", projects)
    monkeypatch.setattr(panel, "CACHE_PATH", cache)
    monkeypatch.setattr(panel, "PROJECTS_ROOT", "")
    return projects, cache


def transcript(directory, name, cwd, tok_in, date="2026-08-01"):
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "timestamp": f"{date}T10:00:00Z",
                "cwd": cwd,
                "message": {
                    "model": "claude-sonnet-5",
                    "usage": {"input_tokens": tok_in, "output_tokens": 0},
                },
            }
        )
        + "\n"
    )
    return path


def test_transcripts_are_found_recursively_and_attributed_to_their_project(panel, sessions):
    projects, _ = sessions
    transcript(projects, "a/one.jsonl", "/work/acme", 100)
    transcript(projects, "b/nested/two.jsonl", "/work/other", 200)

    records = panel.collect()

    assert sorted((row[2], row[3]) for row in records) == [
        ("work/acme", 100),
        ("work/other", 200),
    ]


def test_a_missing_projects_directory_yields_nothing_rather_than_raising(panel, sessions, tmp_path):
    panel.PROJECTS_DIR = tmp_path / "never-created"

    assert panel.collect() == []


def test_the_first_pass_writes_a_cache_entry_per_file(panel, sessions):
    projects, cache = sessions
    path = transcript(projects, "one.jsonl", "/work/acme", 100)

    panel.collect()

    entry = json.loads(cache.read_text())[str(path)]
    assert entry["cwd"] == "/work/acme"
    assert entry["sig"] == [int(path.stat().st_mtime), path.stat().st_size]


def test_an_unchanged_file_is_not_parsed_again(panel, sessions):
    # Measured rather than asserted on a counter: the file content is replaced
    # while mtime and size are kept identical. Getting the OLD number back is
    # proof the cache was read and the file was not.
    projects, _ = sessions
    path = transcript(projects, "one.jsonl", "/work/acme", 100)
    panel.collect()
    stat = path.stat()

    path.write_text(path.read_text().replace('"input_tokens": 100', '"input_tokens": 999'))
    os.utime(path, (stat.st_atime, stat.st_mtime))
    assert path.stat().st_size == stat.st_size, "the rewrite must keep the size identical"

    records = panel.collect()

    assert records[0][3] == 100


def test_a_file_whose_size_changed_is_parsed_again(panel, sessions):
    projects, _ = sessions
    transcript(projects, "one.jsonl", "/work/acme", 100)
    panel.collect()

    transcript(projects, "one.jsonl", "/work/acme", 12345)

    assert panel.collect()[0][3] == 12345


def test_a_deleted_transcript_drops_out_of_the_cache(panel, sessions):
    # Otherwise the cache grows for ever with sessions that no longer exist.
    projects, cache = sessions
    gone = transcript(projects, "gone.jsonl", "/work/acme", 100)
    transcript(projects, "kept.jsonl", "/work/acme", 200)
    panel.collect()
    assert str(gone) in json.loads(cache.read_text())

    gone.unlink()
    panel.collect()

    assert str(gone) not in json.loads(cache.read_text())


def test_a_truncated_cache_is_rebuilt_instead_of_crashing_the_panel(panel, sessions):
    # What a panel killed mid-write used to leave behind.
    projects, cache = sessions
    transcript(projects, "one.jsonl", "/work/acme", 100)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text('{"/some/path": {"sig": [1, 2], "cwd": "/work/acme", "ro')

    records = panel.collect()

    assert records[0][3] == 100
    assert json.loads(cache.read_text())  # rewritten as valid JSON


def test_a_cache_entry_from_an_older_format_is_ignored(panel, sessions):
    # Entries written before cwd was cached carry no "cwd" key.
    projects, cache = sessions
    path = transcript(projects, "one.jsonl", "/work/acme", 100)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({str(path): {"sig": [int(path.stat().st_mtime), path.stat().st_size]}})
    )

    records = panel.collect()

    assert records[0][2] == "work/acme"


def test_a_cache_that_cannot_be_written_does_not_stop_the_panel(panel, sessions, tmp_path):
    # A read-only state directory must cost the cache, never the figures.
    projects, _ = sessions
    transcript(projects, "one.jsonl", "/work/acme", 100)
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    panel.CACHE_PATH = blocked / "usage-cache.json"

    assert panel.collect()[0][3] == 100


def test_the_progress_callback_is_told_the_total(panel, sessions):
    projects, _ = sessions
    transcript(projects, "one.jsonl", "/work/acme", 100)
    seen = []

    panel.collect(progress=lambda index, total: seen.append((index, total)))

    assert seen == [(0, 1)]


def test_a_save_that_fails_leaves_the_previous_cache_in_place(panel, sessions, monkeypatch):
    """The cache is either the old one or the new one, never half of one.

    A panel killed mid-save used to leave a truncated file behind. That was
    survivable (the next start fails to parse it and re-reads everything) but
    it threw away a cache that was perfectly good a moment earlier.

    The fault is injected on the step that swaps the new file in: whatever
    happens there, what stays on disk is the cache that was already valid, and
    no half-written debris next to it.
    """
    projects, cache = sessions
    transcript(projects, "one.jsonl", "/work/acme", 100)
    panel.collect()
    intact = cache.read_text()

    transcript(projects, "two.jsonl", "/work/other", 200)

    def fails(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(panel.os, "replace", fails)
    panel.collect()  # a failed save must never stop the panel

    assert cache.read_text() == intact
    assert list(cache.parent.iterdir()) == [cache], "a temporary file was left behind"


# --- the cache is only written when it changed ------------------------------


def test_a_refresh_that_changes_nothing_does_not_rewrite_the_cache(panel, sessions):
    """Measured on the real corpus, 2026-08-29: a 1.61 MB cache rewritten every
    120 s is 1.16 GB written per day for a set of transcripts that never
    changed. The panel sits open in the statistics space for days at a time.
    """
    projects, cache = sessions
    transcript(projects, "one.jsonl", "/work/acme", 100)
    panel.collect()
    stamp = cache.stat().st_mtime_ns

    panel.collect()
    panel.collect()

    assert cache.stat().st_mtime_ns == stamp


def test_a_new_transcript_does_get_written_to_the_cache(panel, sessions):
    # The saving must not be so eager that a real change is dropped.
    projects, cache = sessions
    transcript(projects, "one.jsonl", "/work/acme", 100)
    panel.collect()

    transcript(projects, "two.jsonl", "/work/other", 200)
    panel.collect()

    assert str(projects / "two.jsonl") in json.loads(cache.read_text())


def test_a_deleted_transcript_gets_written_out_too(panel, sessions):
    projects, cache = sessions
    gone = transcript(projects, "gone.jsonl", "/work/acme", 100)
    transcript(projects, "kept.jsonl", "/work/acme", 200)
    panel.collect()

    gone.unlink()
    panel.collect()

    assert str(gone) not in json.loads(cache.read_text())


def test_the_records_are_the_same_whether_or_not_the_cache_was_written(panel, sessions):
    projects, _ = sessions
    transcript(projects, "one.jsonl", "/work/acme", 100)

    first = panel.collect()
    second = panel.collect()

    assert first == second
