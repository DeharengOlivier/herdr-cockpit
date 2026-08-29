"""bootstrap.sh: how spaces.conf is read, and what is done with it.

The script is what WezTerm runs at startup, so a misread line is a space that
never appears and no error anyone sees. --list exists to make that readable,
and it is also the cheapest way to assert the parsing.
"""

from __future__ import annotations

TAB = "\t"


def conf(*lines: str) -> str:
    return "\n".join(lines) + "\n"


# --- reading the file -------------------------------------------------------


def test_a_relative_path_is_resolved_from_the_projects_root(bootstrap):
    (bootstrap.root / "dev" / "acme").mkdir(parents=True)
    bootstrap.write_conf(conf(f"PROJECTS_ROOT={bootstrap.root}/dev", f"acme{TAB}acme"))

    result = bootstrap.run("--list")

    assert f"ok       acme{' ' * 21}{bootstrap.root}/dev/acme" in result.stdout


def test_without_a_projects_root_a_relative_path_falls_back_to_home(bootstrap):
    bootstrap.write_conf(conf(f"acme{TAB}work/acme"))

    result = bootstrap.run("--list")

    assert str(bootstrap.home / "work" / "acme") in result.stdout
    assert "(not set)" in result.stdout


def test_a_tilde_path_is_expanded_against_home(bootstrap):
    (bootstrap.home / ".dotfiles").mkdir()
    bootstrap.write_conf(conf(f"dotfiles{TAB}~/.dotfiles"))

    result = bootstrap.run("--list")

    assert "ok       dotfiles" in result.stdout
    assert str(bootstrap.home / ".dotfiles") in result.stdout


def test_a_bare_tilde_is_home_itself(bootstrap):
    bootstrap.write_conf(conf(f"home{TAB}~"))

    result = bootstrap.run("--list")

    assert f"ok       home{' ' * 21}{bootstrap.home}" in result.stdout


def test_an_absolute_path_is_taken_as_is(bootstrap):
    bootstrap.write_conf(conf(f"tmp{TAB}/usr"))

    result = bootstrap.run("--list")

    assert "ok       tmp" in result.stdout
    assert "/usr" in result.stdout


def test_the_projects_root_itself_understands_a_tilde(bootstrap):
    (bootstrap.home / "dev" / "acme").mkdir(parents=True)
    bootstrap.write_conf(conf("PROJECTS_ROOT=~/dev", f"acme{TAB}acme"))

    result = bootstrap.run("--list")

    assert str(bootstrap.home / "dev" / "acme") in result.stdout


def test_labels_and_paths_may_contain_spaces(bootstrap):
    # The separator is a tab precisely so that this works.
    (bootstrap.root / "my projects").mkdir()
    bootstrap.write_conf(conf(f"client acme{TAB}{bootstrap.root}/my projects"))

    result = bootstrap.run("--list")

    assert "client acme" in result.stdout
    assert f"{bootstrap.root}/my projects" in result.stdout


def test_comments_and_blank_lines_are_skipped(bootstrap):
    bootstrap.write_conf(conf("# a comment", "", f"acme{TAB}/usr", "   ", ""))

    result = bootstrap.run("--list")

    assert "spaces         : 1" in result.stdout


def test_a_line_without_a_tab_is_reported_and_ignored(bootstrap):
    # Spaces instead of a tab is the mistake this file invites.
    bootstrap.write_conf(conf("acme /usr", f"other{TAB}/usr"))

    result = bootstrap.run("--list")

    assert "missing tab separator" in result.stderr
    assert "acme /usr" in result.stderr
    assert "spaces         : 1" in result.stdout


def test_directives_meant_for_other_scripts_are_ignored_silently(bootstrap):
    # GITHUB_USER is read by install.sh. bootstrap.sh must not choke on it, nor
    # take it for a space.
    bootstrap.write_conf(conf("GITHUB_USER=someone", f"acme{TAB}/usr"))

    result = bootstrap.run("--list")

    assert result.stderr == ""
    assert "spaces         : 1" in result.stdout


def test_a_missing_directory_is_marked_rather_than_hidden(bootstrap):
    # The most frequent cause of a space that never shows up.
    bootstrap.write_conf(conf(f"gone{TAB}/nowhere/at/all"))

    result = bootstrap.run("--list")

    assert "MISSING  gone" in result.stdout


def test_a_last_line_without_a_newline_is_still_read(bootstrap):
    bootstrap.spaces_conf.write_text(f"acme{TAB}/usr")

    result = bootstrap.run("--list")

    assert "spaces         : 1" in result.stdout


def test_a_missing_spaces_conf_is_not_an_error(bootstrap):
    result = bootstrap.run("--list")

    assert result.returncode == 0
    assert "spaces         : 0" in result.stdout


def test_listing_creates_nothing(bootstrap):
    bootstrap.write_conf(conf(f"acme{TAB}/usr"))

    bootstrap.run("--list")

    assert bootstrap.read_state().get("workspaces", []) == []
