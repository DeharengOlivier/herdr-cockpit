"""The ~/.zshrc guard is added at most once, however it got there.

Defect, 2026-08-29: install.sh probed ~/.zshrc for the string HERDR_AUTOSTART,
but that string lives in shell/herdr-autostart.zsh, which the .zshrc merely
sources. The probe therefore never matched the installer's own block, and a
second run appended it again. Two guards mean two nested autostart loops, so
quitting the panel drops into a second copy of it instead of into the shell.

The battery covers the exact case, the invariant it violated, the shapes a
hand-written guard can take, and the uninstall that has to clean up after it.
"""

from __future__ import annotations

import pytest

GUARD_MARKER = "# >>> herdr-cockpit >>>"


def guard_count(cockpit) -> int:
    """How many lines source the autostart script, block or hand-written.

    Counted per line, not per occurrence: one guard line names the file twice,
    once in the `[ -f ... ]` test and once in the `source`.
    """
    return sum(
        1 for line in cockpit.zshrc.read_text().splitlines() if "herdr-autostart.zsh" in line
    )


# --- the reported case ------------------------------------------------------


def test_a_second_install_does_not_append_a_second_block(cockpit):
    cockpit.install()
    cockpit.install()

    assert cockpit.zshrc.read_text().count(GUARD_MARKER) == 1


def test_the_guard_line_itself_appears_once_after_a_second_install(cockpit):
    cockpit.install()
    cockpit.install()

    assert guard_count(cockpit) == 1


# --- the invariant, stated generally ----------------------------------------


@pytest.mark.parametrize("runs", [1, 2, 3])
def test_however_many_times_it_runs_there_is_exactly_one_guard(cockpit, runs):
    for _ in range(runs):
        cockpit.install()

    assert guard_count(cockpit) == 1


def test_the_second_run_reports_the_guard_as_already_present(cockpit):
    cockpit.install()

    result = cockpit.install()

    assert "already present" in result.stdout


# --- the shapes an existing guard can take ----------------------------------


def test_a_hand_written_source_line_is_recognised(cockpit):
    # What the installer tells the user to paste when they decline the prompt.
    guard = f'[ -f "{cockpit.repository}/shell/herdr-autostart.zsh" ] && source "{cockpit.repository}/shell/herdr-autostart.zsh"'
    cockpit.zshrc.write_text(f"{guard}\n")

    cockpit.install()

    assert GUARD_MARKER not in cockpit.zshrc.read_text()
    assert guard_count(cockpit) == 1


def test_a_hand_rolled_guard_using_the_variable_is_recognised(cockpit):
    # Someone who inlined the loop instead of sourcing our file.
    cockpit.zshrc.write_text('[[ -n "${HERDR_AUTOSTART:-}" ]] && eval "$HERDR_AUTOSTART"\n')

    cockpit.install()

    assert GUARD_MARKER not in cockpit.zshrc.read_text()


def test_an_unrelated_zshrc_still_gets_the_guard(cockpit):
    # The probe must not become so broad that it matches anything.
    cockpit.zshrc.write_text("export EDITOR=vim\nalias k=kubectl\n")

    cockpit.install()

    assert guard_count(cockpit) == 1
    assert "alias k=kubectl" in cockpit.zshrc.read_text()


def test_an_empty_zshrc_gets_the_guard(cockpit):
    cockpit.zshrc.write_text("")

    cockpit.install()

    assert guard_count(cockpit) == 1


# --- the neighbours: what the duplicate would have dragged along -------------


def test_a_second_install_does_not_record_a_second_zshrc_entry(cockpit):
    cockpit.install()
    cockpit.install()

    entries = [
        line for line in cockpit.manifest.read_text().splitlines() if line.startswith("zshrc\t")
    ]
    assert len(entries) == 1


def test_a_second_install_does_not_leave_a_second_zshrc_backup(cockpit):
    cockpit.zshrc.write_text("export EDITOR=vim\n")

    cockpit.install()
    cockpit.install()

    assert len(cockpit.backups_of(cockpit.zshrc)) == 1


# --- across the boundary: the round trip has to survive it -------------------


def test_uninstall_after_two_installs_restores_the_original_zshrc(cockpit):
    cockpit.zshrc.write_text("export EDITOR=vim\n")

    cockpit.install()
    cockpit.install()
    cockpit.uninstall()

    assert cockpit.zshrc.read_text() == "export EDITOR=vim\n"
