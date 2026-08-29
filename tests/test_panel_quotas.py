"""Where quota-axi is looked for, and what happens when it misbehaves.

install.sh accepts quota-axi anywhere on PATH and reports "quotas enabled".
The panel has to agree with that, or a user follows the installer's advice,
sees it confirmed, and still gets "missing" in the panel.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def elsewhere(panel, tmp_path, monkeypatch):
    """A quota-axi installed somewhere other than ~/.local/bin."""
    prefix = tmp_path / "opt" / "bin"
    prefix.mkdir(parents=True)
    binary = prefix / "quota-axi"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(prefix))
    monkeypatch.setattr(panel.Path, "home", staticmethod(lambda: tmp_path / "home"))
    return binary


def test_quota_axi_is_found_wherever_npm_put_it(panel, elsewhere):
    # npm's global prefix is /opt/homebrew or /usr/local as often as it is ~.
    assert panel.quota_binary() == str(elsewhere)


def test_quota_axi_is_still_found_in_local_bin_when_it_is_not_on_the_path(
    panel, tmp_path, monkeypatch
):
    # The Herdr pane does not necessarily inherit a PATH with ~/.local/bin in
    # it, and install.sh warns about exactly that.
    home = tmp_path / "home"
    binary = home / ".local" / "bin" / "quota-axi"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(panel.Path, "home", staticmethod(lambda: home))

    assert panel.quota_binary() == str(binary)


def test_a_missing_quota_axi_says_how_to_get_it(panel, tmp_path, monkeypatch):
    # Rather than making the whole section disappear without explanation.
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(panel.Path, "home", staticmethod(lambda: tmp_path / "home"))

    assert panel.quota_binary() is None
    rows = panel.quotas()
    assert len(rows) == 1
    assert "npm install -g quota-axi" in rows[0][4]


@pytest.fixture
def quota_axi(panel, tmp_path, monkeypatch):
    """Install a fake quota-axi with the body of your choice."""

    def install(body):
        prefix = tmp_path / "bin"
        prefix.mkdir(exist_ok=True)
        binary = prefix / "quota-axi"
        # echo, not cat: the fixture strips PATH, so only shell builtins run.
        binary.write_text(f"#!/bin/sh\n{body}\n")
        binary.chmod(0o755)
        monkeypatch.setenv("PATH", str(prefix))
        monkeypatch.setattr(panel.Path, "home", staticmethod(lambda: tmp_path / "home"))
        return binary

    return install


def test_a_quota_axi_that_answers_nonsense_says_so_rather_than_vanishing(panel, quota_axi):
    # Same principle as the missing case: the section explains itself instead
    # of disappearing and leaving the user to wonder where it went.
    quota_axi("echo 'Error: cannot find module'\nexit 1")

    rows = panel.quotas()

    assert len(rows) == 1
    assert rows[0][:4] == ("quota-axi", "", "failed", None)
    assert "cannot find module" in rows[0][4]


def test_a_quota_axi_that_prints_nothing_reports_its_exit_status(panel, quota_axi):
    quota_axi("exit 3")

    assert "exit status 3" in panel.quotas()[0][4]


def test_a_failure_message_is_kept_short_enough_to_fit_a_row(panel, quota_axi):
    quota_axi(f"echo '{'x' * 500}'\nexit 1")

    assert len(panel.quotas()[0][4]) <= 70


def test_a_provider_without_windows_reports_why_rather_than_vanishing(panel, quota_axi):
    payload = json.dumps(
        {"providers": [{"label": "Claude", "plan": "max", "state": {"error": "not logged in"}}]}
    )
    quota_axi(f"echo '{payload}'")

    rows = panel.quotas()

    assert rows == [("Claude", "max", "", None, "not logged in")]


def test_a_percentage_is_read_from_either_direction(panel, quota_axi):
    payload = json.dumps(
        {
            "providers": [
                {
                    "label": "Claude",
                    "windows": [
                        {"percentUsed": 42.0, "resetsAt": "2026-09-01T10:00:00Z"},
                        {"percentRemaining": 25.0},
                    ],
                }
            ]
        }
    )
    quota_axi(f"echo '{payload}'")

    percentages = [row[3] for row in panel.quotas()]

    assert percentages == [42.0, 75.0]
