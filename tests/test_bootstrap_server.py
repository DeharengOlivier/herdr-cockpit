"""bootstrap.sh against a running server: --extra, --prune, --ensure, attach.

Every one of these either creates or closes something a user is working in, so
the interesting assertions are about what is NOT touched: a space that already
exists is left alone, --extra closes nothing, --prune closes exactly what
--extra listed, and the statistics space is never counted as a stray.
"""

from __future__ import annotations

TAB = "\t"
STATS = "▦ Stats"


def workspace(label, ws_id=None, cwd="/somewhere"):
    return {"workspace_id": ws_id or f"ws-{label}", "label": label, "cwd": cwd}


def conf(*lines: str) -> str:
    return "\n".join(lines) + "\n"


# --- --extra ----------------------------------------------------------------


def test_extra_lists_spaces_that_are_not_declared(bootstrap):
    bootstrap.write_conf(conf(f"acme{TAB}/usr"))
    bootstrap.set_state(workspaces=[workspace("acme"), workspace("scratch")])

    result = bootstrap.run("--extra")

    assert "scratch" in result.stdout
    assert "  acme\n" not in result.stdout
    assert "1 space(s) outside spaces.conf" in result.stdout


def test_extra_never_reports_the_statistics_space(bootstrap):
    # It belongs to the cockpit even though it is not in spaces.conf. Reporting
    # it would invite --prune to close the panel.
    bootstrap.write_conf(conf(f"acme{TAB}/usr"))
    bootstrap.set_state(workspaces=[workspace("acme"), workspace(STATS)])

    result = bootstrap.run("--extra")

    assert "no space outside spaces.conf" in result.stdout


def test_extra_says_so_plainly_when_there_is_nothing(bootstrap):
    bootstrap.write_conf(conf(f"acme{TAB}/usr"))
    bootstrap.set_state(workspaces=[workspace("acme")])

    result = bootstrap.run("--extra")

    assert "no space outside spaces.conf" in result.stdout


def test_extra_closes_nothing(bootstrap):
    bootstrap.write_conf(conf(f"acme{TAB}/usr"))
    bootstrap.set_state(workspaces=[workspace("acme"), workspace("scratch")])

    bootstrap.run("--extra")

    assert [call for call in bootstrap.calls() if call[:2] == ["workspace", "close"]] == []
    assert len(bootstrap.read_state()["workspaces"]) == 2


def test_a_label_containing_spaces_is_matched_whole(bootstrap):
    bootstrap.write_conf(conf(f"client acme{TAB}/usr"))
    bootstrap.set_state(workspaces=[workspace("client acme")])

    result = bootstrap.run("--extra")

    assert "no space outside spaces.conf" in result.stdout


# --- --prune ----------------------------------------------------------------


def test_prune_closes_exactly_what_extra_listed(bootstrap):
    bootstrap.write_conf(conf(f"acme{TAB}/usr"))
    bootstrap.set_state(
        workspaces=[workspace("acme"), workspace("scratch"), workspace(STATS)]
    )

    result = bootstrap.run("--prune")

    assert "closed: scratch" in result.stdout
    remaining = {w["label"] for w in bootstrap.read_state()["workspaces"]}
    assert remaining == {"acme", STATS}


def test_prune_with_nothing_to_close_does_nothing(bootstrap):
    bootstrap.write_conf(conf(f"acme{TAB}/usr"))
    bootstrap.set_state(workspaces=[workspace("acme")])

    bootstrap.run("--prune")

    assert [call for call in bootstrap.calls() if call[:2] == ["workspace", "close"]] == []


def test_prune_reports_a_space_it_could_not_close(bootstrap):
    bootstrap.write_conf(conf(f"acme{TAB}/usr"))
    # No workspace_id: nothing to close it by.
    bootstrap.set_state(workspaces=[{"label": "scratch"}])

    result = bootstrap.run("--prune")

    assert "closed: scratch" not in result.stdout


# --- --ensure ---------------------------------------------------------------


def test_ensure_creates_a_declared_space_that_is_missing(bootstrap):
    target = bootstrap.root / "acme"
    target.mkdir()
    bootstrap.write_conf(conf(f"acme{TAB}{target}"))
    bootstrap.set_state(workspaces=[])

    result = bootstrap.run("--ensure")

    assert "space created: acme" in result.stdout
    created = {w["label"]: w for w in bootstrap.read_state()["workspaces"]}
    assert created["acme"]["cwd"] == str(target)


def test_ensure_leaves_an_existing_space_alone(bootstrap):
    target = bootstrap.root / "acme"
    target.mkdir()
    bootstrap.write_conf(conf(f"acme{TAB}{target}"))
    bootstrap.set_state(workspaces=[workspace("acme"), workspace(STATS)])

    bootstrap.run("--ensure")

    creations = [call for call in bootstrap.calls() if call[:2] == ["workspace", "create"]]
    assert creations == []


def test_ensure_skips_a_path_that_does_not_exist_and_says_why(bootstrap):
    # Creating a space on a missing directory would leave a shell in ~ that
    # looks like the project but is not.
    bootstrap.write_conf(conf(f"gone{TAB}/nowhere/at/all"))
    bootstrap.set_state(workspaces=[workspace(STATS)])

    result = bootstrap.run("--ensure")

    assert "/nowhere/at/all not found" in result.stderr
    assert "space created" not in result.stdout


def test_ensure_creates_the_statistics_space_with_its_autostart_command(bootstrap):
    bootstrap.set_state(workspaces=[])

    result = bootstrap.run("--ensure")

    assert f"space created: {STATS}" in result.stdout
    stats = [w for w in bootstrap.read_state()["workspaces"] if w["label"] == STATS][0]
    autostart = [value for value in stats["env"] if value.startswith("HERDR_AUTOSTART=")]
    assert autostart and autostart[0].endswith("stats/panel.py'")


def test_the_statistics_space_carries_the_projects_root_when_there_is_one(bootstrap):
    # The panel needs it to shorten the project names it displays.
    (bootstrap.root / "dev").mkdir()
    bootstrap.write_conf(conf(f"PROJECTS_ROOT={bootstrap.root}/dev"))
    bootstrap.set_state(workspaces=[])

    bootstrap.run("--ensure")

    stats = [w for w in bootstrap.read_state()["workspaces"] if w["label"] == STATS][0]
    assert f"COCKPIT_PROJECTS_ROOT={bootstrap.root}/dev" in stats["env"]


def test_ensure_does_nothing_at_all_when_the_server_is_down(bootstrap):
    # Every herdr call would fail anyway, and the errors would be noise.
    target = bootstrap.root / "acme"
    target.mkdir()
    bootstrap.write_conf(conf(f"acme{TAB}{target}"))
    bootstrap.set_state(up=False, workspaces=[])

    result = bootstrap.run("--ensure")

    assert result.returncode == 0
    assert bootstrap.read_state()["workspaces"] == []


def test_ensure_closes_the_extra_tabs_of_the_statistics_space_only(bootstrap):
    bootstrap.set_state(
        workspaces=[workspace(STATS, ws_id="ws-stats"), workspace("acme", ws_id="ws-acme")],
        tabs=[
            {"workspace_id": "ws-stats", "tab_id": "t1", "number": 1},
            {"workspace_id": "ws-stats", "tab_id": "t2", "number": 2},
            {"workspace_id": "ws-acme", "tab_id": "t3", "number": 1},
            {"workspace_id": "ws-acme", "tab_id": "t4", "number": 2},
        ],
    )

    bootstrap.run("--ensure")

    remaining = {tab["tab_id"] for tab in bootstrap.read_state()["tabs"]}
    assert remaining == {"t1", "t3", "t4"}


def test_the_lowest_numbered_tab_is_the_one_kept(bootstrap):
    # It is the one holding the panel: the others are necessarily later.
    bootstrap.set_state(
        workspaces=[workspace(STATS, ws_id="ws-stats")],
        tabs=[
            {"workspace_id": "ws-stats", "tab_id": "late", "number": 9},
            {"workspace_id": "ws-stats", "tab_id": "first", "number": 1},
        ],
    )

    bootstrap.run("--ensure")

    assert [tab["tab_id"] for tab in bootstrap.read_state()["tabs"]] == ["first"]


# --- the default: attach ----------------------------------------------------


def test_with_no_argument_it_attaches_the_session_and_creates_nothing(bootstrap):
    # The guarantee of 2026-08-06: a space exists only because it was asked for.
    target = bootstrap.root / "acme"
    target.mkdir()
    bootstrap.write_conf(conf(f"acme{TAB}{target}"))
    bootstrap.set_state(workspaces=[])

    bootstrap.run()

    assert ["session", "attach", "default"] in bootstrap.calls()
    assert bootstrap.read_state()["workspaces"] == []


def test_the_claude_code_markers_are_scrubbed_before_the_server_is_reached(bootstrap):
    # A server that inherits CLAUDE_CODE_CHILD_SESSION hands it to every pane,
    # and every agent in those panes then writes its transcript nowhere.
    bootstrap.run(
        env={
            "CLAUDE_CODE_CHILD_SESSION": "1",
            "CLAUDE_CODE_ENTRYPOINT": "cli",
            "KEEP_ME": "yes",
        }
    )

    handed_over = bootstrap.captured_env.read_text()
    assert "CLAUDE_CODE_CHILD_SESSION" not in handed_over
    assert "CLAUDE_CODE_ENTRYPOINT" not in handed_over
    assert "KEEP_ME=yes" in handed_over


def test_a_missing_herdr_says_so_and_drops_into_a_shell(bootstrap):
    # Rather than leaving WezTerm on a closed pane with no explanation.
    result = bootstrap.run(
        herdr=str(bootstrap.root / "no-such-herdr"), env={"SHELL": "/usr/bin/true"}
    )

    assert "herdr not found" in result.stderr
    assert "https://herdr.dev" in result.stderr
    assert result.returncode == 0
