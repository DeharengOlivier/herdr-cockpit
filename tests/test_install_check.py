"""`install.sh --check`: is this installation still the one that was made?

Everything the installer lays down can be undone by something else. A `git
clone` moved to another directory leaves dangling symlinks, a dotfile manager
overwrites `~/.zshrc`, a `brew` recipe replaces `wezterm.lua` with a real file.
All of those look identical from the outside: the cockpit simply stops
behaving. This is the command that says which one happened.
"""

from __future__ import annotations


def check(cockpit, **kwargs):
    return cockpit.run("install.sh", "--check", expect_success=False, **kwargs)


# --- the healthy case -------------------------------------------------------


def test_a_fresh_installation_reports_healthy(cockpit):
    cockpit.install()

    result = check(cockpit)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "nothing to repair" in result.stdout


def test_checking_writes_nothing(cockpit):
    cockpit.install()
    before = cockpit.tree()

    check(cockpit)

    assert cockpit.tree() == before


def test_without_a_manifest_it_says_nothing_is_installed(cockpit):
    result = check(cockpit)

    assert result.returncode == 1
    assert "nothing was installed" in result.stderr


# --- each way an installation decays ---------------------------------------


def test_a_deleted_command_is_named(cockpit):
    cockpit.install()
    cockpit.home_path(".local", "bin", "herdr-cockpit-panel").unlink()

    result = check(cockpit)

    assert result.returncode == 1
    assert "herdr-cockpit-panel" in result.stderr


def test_a_link_replaced_by_a_real_file_is_named(cockpit):
    # What a package manager or a dotfile tool does.
    cockpit.install()
    cockpit.wezterm_config.unlink()
    cockpit.wezterm_config.write_text("-- someone else's config\n")

    result = check(cockpit)

    assert result.returncode == 1
    assert "no longer a link" in result.stderr


def test_a_link_left_dangling_by_a_moved_repository_is_named(cockpit):
    # The single most likely failure: the clone was moved or renamed.
    cockpit.install()
    (cockpit.repository / "config" / "wezterm.lua").unlink()

    result = check(cockpit)

    assert result.returncode == 1
    assert "does not exist" in result.stderr


def test_a_link_pointing_outside_this_repository_is_named(cockpit):
    # Two clones, and the other one won.
    cockpit.install()
    other = cockpit.root / "other-clone"
    other.mkdir()
    (other / "wezterm.lua").write_text("-- the other clone\n")
    cockpit.wezterm_config.unlink()
    cockpit.wezterm_config.symlink_to(other / "wezterm.lua")

    result = check(cockpit)

    assert result.returncode == 1
    assert "outside this repository" in result.stderr


def test_a_deleted_herdr_config_is_named(cockpit):
    cockpit.install()
    cockpit.herdr_config.unlink()

    result = check(cockpit)

    assert result.returncode == 1
    assert "config.toml" in result.stderr


def test_a_herdr_config_pointing_at_a_panel_that_is_gone_is_named(cockpit):
    # A generated file holds an absolute path, so it is the one thing a moved
    # repository breaks silently: herdr config check still passes.
    cockpit.install()
    (cockpit.repository / "stats" / "panel.py").unlink()

    result = check(cockpit)

    assert result.returncode == 1
    assert "panel" in result.stderr.lower()


def test_a_guard_removed_from_zshrc_is_named_without_failing_the_check(cockpit):
    # Warned about rather than failed: running without the guard is a
    # supported, if degraded, cockpit. The panel still works, it just opens
    # behind a useless shell. Only a broken installation returns non-zero.
    cockpit.install()
    cockpit.zshrc.write_text("export EDITOR=vim\n")

    result = check(cockpit)

    assert result.returncode == 0
    assert "no autostart guard" in result.stdout


def test_every_problem_is_reported_not_just_the_first(cockpit):
    cockpit.install()
    cockpit.home_path(".local", "bin", "herdr-cockpit-panel").unlink()
    cockpit.wezterm_config.unlink()
    cockpit.zshrc.write_text("")

    result = check(cockpit)

    assert result.returncode == 1
    assert "2 problem" in result.stdout
    assert "herdr-cockpit-panel" in result.stderr
    assert "wezterm.lua" in result.stderr
    # The guard is missing too, but that one is a warning, not a problem.
    assert "no autostart guard" in result.stdout


# --- it survives a partial installation ------------------------------------


def test_checking_after_an_uninstall_says_nothing_is_installed(cockpit):
    cockpit.install()
    cockpit.uninstall()

    result = check(cockpit)

    assert result.returncode == 1
    assert "nothing was installed" in result.stderr


# --- a manifest that has grown over several installs ------------------------


def test_a_target_installed_twice_is_reported_once(cockpit):
    # The manifest is append-only, so a second install adds a second line for
    # the same target. Reporting it twice is noise that hides a real problem
    # further down the list.
    cockpit.install()
    cockpit.install("--force")

    result = check(cockpit)

    assert result.stdout.count("wezterm.lua") == 1
    assert result.stdout.count("config.toml") == 1


def test_the_most_recent_entry_for_a_target_is_the_one_checked(cockpit):
    cockpit.install()
    cockpit.install("--force")
    cockpit.wezterm_config.unlink()

    result = check(cockpit)

    assert result.returncode == 1
    assert result.stderr.count("wezterm.lua") == 1


# --- the guard is a property of the installation, not of the manifest -------


def test_a_guard_added_by_hand_is_recognised_even_with_no_manifest_entry(cockpit):
    # Declining the prompt and pasting the line yourself is a supported path,
    # and it leaves no zshrc entry behind.
    script = f"{cockpit.repository}/shell/herdr-autostart.zsh"
    cockpit.zshrc.write_text(f'[ -f "{script}" ] && source "{script}"\n')
    cockpit.install()

    result = check(cockpit)

    assert result.returncode == 0
    assert "autostart guard present" in result.stdout


def test_a_missing_guard_is_reported_even_when_it_was_never_installed(cockpit):
    # Declining the prompt is allowed, so this is a warning about a degraded
    # cockpit rather than a broken one: the panel still works, it just opens in
    # a second pane. It must not fail the check.
    cockpit.run("install.sh")  # interactive, no tty: every confirm declines

    result = check(cockpit)

    assert "guard" in result.stdout + result.stderr
    assert result.returncode == 0
