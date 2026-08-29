"""The install and uninstall round trip, run against a throwaway HOME.

This is the mechanism that is supposed to save the user: uninstall.sh claims it
puts back whatever was there before. A claim that is never exercised is a
belief, so every test here installs for real and then looks at the filesystem.
"""

from __future__ import annotations

GUARD_MARKER = "# >>> herdr-cockpit >>>"
END_MARKER = "# <<< herdr-cockpit <<<"


# --- a fresh install --------------------------------------------------------


def test_install_links_the_two_commands_into_local_bin(cockpit):
    cockpit.install()

    bootstrap = cockpit.home_path(".local", "bin", "herdr-cockpit-bootstrap")
    panel = cockpit.home_path(".local", "bin", "herdr-cockpit-panel")

    assert bootstrap.is_symlink()
    assert bootstrap.resolve() == cockpit.repository / "bin" / "bootstrap.sh"
    assert panel.is_symlink()
    assert panel.resolve() == cockpit.repository / "stats" / "panel.py"


def test_install_links_wezterm_config_rather_than_copying_it(cockpit):
    # A link is what makes `git pull` update the installation. A copy would
    # silently freeze the config at the version installed that day.
    cockpit.install()

    assert cockpit.wezterm_config.is_symlink()
    assert cockpit.wezterm_config.resolve() == cockpit.repository / "config" / "wezterm.lua"


def test_install_generates_the_herdr_config_with_the_panel_path_resolved(cockpit):
    cockpit.install()

    content = cockpit.herdr_config.read_text()
    assert not cockpit.herdr_config.is_symlink(), "config.toml is generated, not linked"
    assert "@@COCKPIT_PANEL@@" not in content, "the placeholder was left unresolved"
    assert str(cockpit.repository / "stats" / "panel.py") in content


def test_install_adds_the_guard_to_zshrc_inside_its_markers(cockpit):
    cockpit.install()

    content = cockpit.zshrc.read_text()
    assert GUARD_MARKER in content
    assert END_MARKER in content
    assert str(cockpit.repository / "shell" / "herdr-autostart.zsh") in content


def test_install_creates_spaces_conf_from_the_example(cockpit):
    cockpit.install()

    spaces = cockpit.repository / "spaces.conf"
    assert spaces.is_file()
    assert spaces.read_text() == (cockpit.repository / "spaces.conf.example").read_text()


def test_install_records_every_write_in_the_manifest(cockpit):
    cockpit.install()

    targets = {line.split("\t")[1] for line in cockpit.manifest.read_text().splitlines() if line}
    assert str(cockpit.home_path(".local", "bin", "herdr-cockpit-bootstrap")) in targets
    assert str(cockpit.home_path(".local", "bin", "herdr-cockpit-panel")) in targets
    assert str(cockpit.wezterm_config) in targets
    assert str(cockpit.herdr_config) in targets
    assert str(cockpit.zshrc) in targets


# --- what was already there -------------------------------------------------


def test_install_backs_up_a_pre_existing_wezterm_config(cockpit):
    cockpit.wezterm_config.parent.mkdir(parents=True)
    cockpit.wezterm_config.write_text("-- mine\n")

    cockpit.install()

    backups = cockpit.backups_of(cockpit.wezterm_config)
    assert len(backups) == 1, f"expected exactly one backup, got {backups}"
    assert backups[0].read_text() == "-- mine\n"


def test_install_backs_up_zshrc_without_removing_the_original(cockpit):
    # ~/.zshrc is appended to, not replaced: the copy must stay in place.
    cockpit.zshrc.write_text("export EDITOR=vim\n")

    cockpit.install()

    backups = cockpit.backups_of(cockpit.zshrc)
    assert len(backups) == 1
    assert backups[0].read_text() == "export EDITOR=vim\n"
    assert "export EDITOR=vim" in cockpit.zshrc.read_text()


def test_a_pre_existing_herdr_config_is_kept_and_the_cockpit_version_written_beside_it(cockpit):
    # Without --force, a config.toml that may hold the user's own settings is
    # never overwritten: an approximate TOML merge would break both files.
    cockpit.herdr_config.parent.mkdir(parents=True)
    cockpit.herdr_config.write_text("[ui]\nmine = true\n")

    result = cockpit.run("install.sh", expect_success=True)

    assert cockpit.herdr_config.read_text() == "[ui]\nmine = true\n"
    sidecar = cockpit.herdr_config.with_name("config.toml.cockpit")
    assert sidecar.is_file()
    assert "@@COCKPIT_PANEL@@" not in sidecar.read_text()
    assert "config.toml kept" in result.stdout


def test_force_replaces_the_herdr_config_and_keeps_a_backup(cockpit):
    cockpit.herdr_config.parent.mkdir(parents=True)
    cockpit.herdr_config.write_text("[ui]\nmine = true\n")

    cockpit.install("--force")

    assert "mine = true" not in cockpit.herdr_config.read_text()
    backups = cockpit.backups_of(cockpit.herdr_config)
    assert len(backups) == 1
    assert backups[0].read_text() == "[ui]\nmine = true\n"


# --- running it twice -------------------------------------------------------


def test_installing_twice_does_not_back_up_links_it_laid_down_itself(cockpit):
    # A link already pointing at the right place is left alone. Backing it up
    # would fill the home directory with copies of our own symlinks.
    cockpit.install()
    cockpit.install()

    assert cockpit.backups_of(cockpit.wezterm_config) == []
    assert cockpit.backups_of(cockpit.home_path(".local", "bin", "herdr-cockpit-panel")) == []


# --- dry run ----------------------------------------------------------------


def test_dry_run_writes_nothing_at_all(cockpit):
    before = cockpit.tree()

    result = cockpit.install("--dry-run")

    assert cockpit.tree() == before
    assert not (cockpit.repository / "spaces.conf").exists()
    assert "[dry-run]" in result.stdout


# --- the round trip ---------------------------------------------------------


def test_uninstall_restores_the_home_directory_it_found(cockpit):
    cockpit.zshrc.write_text("export EDITOR=vim\n")
    cockpit.wezterm_config.parent.mkdir(parents=True)
    cockpit.wezterm_config.write_text("-- mine\n")
    cockpit.herdr_config.parent.mkdir(parents=True)
    cockpit.herdr_config.write_text("[ui]\nmine = true\n")

    cockpit.install("--force")
    cockpit.uninstall()

    assert cockpit.zshrc.read_text() == "export EDITOR=vim\n"
    assert cockpit.wezterm_config.read_text() == "-- mine\n"
    assert not cockpit.wezterm_config.is_symlink()
    assert cockpit.herdr_config.read_text() == "[ui]\nmine = true\n"


def test_uninstall_removes_what_it_created_when_there_was_nothing_before(cockpit):
    cockpit.install()
    cockpit.uninstall()

    assert not cockpit.home_path(".local", "bin", "herdr-cockpit-bootstrap").exists()
    assert not cockpit.home_path(".local", "bin", "herdr-cockpit-panel").exists()
    assert not cockpit.wezterm_config.exists()
    assert not cockpit.herdr_config.exists()
    assert not cockpit.manifest.exists()


def test_uninstall_removes_the_block_but_keeps_what_was_added_since(cockpit):
    cockpit.zshrc.write_text("export EDITOR=vim\n")
    cockpit.install()
    with cockpit.zshrc.open("a") as handle:
        handle.write("alias k=kubectl\n")

    cockpit.uninstall()

    content = cockpit.zshrc.read_text()
    assert "export EDITOR=vim" in content
    assert "alias k=kubectl" in content
    assert GUARD_MARKER not in content
    assert "herdr-autostart.zsh" not in content


def test_uninstall_leaves_the_repository_and_spaces_conf_alone(cockpit):
    cockpit.install()
    (cockpit.repository / "spaces.conf").write_text("mine\tsomewhere\n")

    cockpit.uninstall()

    assert (cockpit.repository / "spaces.conf").read_text() == "mine\tsomewhere\n"
    assert (cockpit.repository / "bin" / "bootstrap.sh").is_file()


def test_uninstall_dry_run_changes_nothing(cockpit):
    cockpit.install()
    before = cockpit.tree()

    result = cockpit.uninstall("--dry-run")

    assert cockpit.tree() == before
    assert cockpit.manifest.exists()
    assert "[dry-run]" in result.stdout


def test_uninstall_without_a_manifest_refuses_rather_than_guessing(cockpit):
    result = cockpit.uninstall(expect_success=False)

    assert result.returncode == 1
    assert "No manifest" in result.stderr


def test_uninstalling_twice_is_not_an_error_the_second_time_it_just_refuses(cockpit):
    cockpit.install()
    cockpit.uninstall()

    result = cockpit.uninstall(expect_success=False)

    assert result.returncode == 1
