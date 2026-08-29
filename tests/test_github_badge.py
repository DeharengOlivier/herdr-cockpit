"""The GitHub login is a boundary, and it is validated as one.

The value comes from GITHUB_USER in spaces.conf and is dropped straight into
an API path. A login is a narrow shape, so the fix is to refuse anything that
is not one rather than to escape whatever arrives: "../orgs/somebody" is not a
login that needs encoding, it is not a login at all.
"""

from __future__ import annotations

import io
import json

import pytest


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exception):
        return False


@pytest.fixture
def github(badge, monkeypatch):
    """Records the URL asked for, and answers with a canned profile."""
    asked = []

    def urlopen(request, timeout=None):
        asked.append(request.full_url)
        return FakeResponse(
            json.dumps(
                {
                    "login": "someone",
                    "name": "Some One",
                    "html_url": "https://github.com/someone",
                    "public_repos": 12,
                }
            ).encode()
        )

    monkeypatch.setattr(badge.urllib.request, "urlopen", urlopen)
    return asked


# --- what a login is --------------------------------------------------------


@pytest.mark.parametrize(
    "login",
    ["someone", "Some-One", "a", "user123", "a" * 39, "a-b-c", "0", "DeharengOlivier"],
)
def test_a_real_login_is_accepted(badge, login):
    assert badge.validate_login(login) == login


@pytest.mark.parametrize(
    "login,why",
    [
        ("../orgs/anthropic", "climbs out of the /users/ path"),
        ("someone/repos", "reaches another endpoint"),
        ("someone?per_page=1", "appends a query string"),
        ("someone#fragment", "appends a fragment"),
        ("some one", "a space is not encoded by urllib"),
        ("someone@example.com", "an email is not a login"),
        ("-someone", "a login cannot start with a hyphen"),
        ("someone-", "a login cannot end with a hyphen"),
        ("some--one", "consecutive hyphens are not allowed"),
        ("", "empty"),
        ("a" * 40, "longer than GitHub allows"),
        ("someone\n", "a trailing newline from a badly edited spaces.conf"),
        ("héros", "not in the allowed alphabet"),
    ],
)
def test_anything_that_is_not_a_login_is_refused(badge, login, why):
    with pytest.raises(badge.InvalidLogin):
        badge.validate_login(login)


# --- what reaches the network ----------------------------------------------


def test_a_valid_login_is_queried_on_the_public_users_endpoint(badge, github):
    badge.build("someone")

    assert github == ["https://api.github.com/users/someone"]


def test_a_traversing_login_never_reaches_the_network(badge, github):
    with pytest.raises(badge.InvalidLogin):
        badge.build("../orgs/anthropic")

    assert github == []


def test_the_profile_is_reduced_to_the_four_fields_the_panel_shows(badge, github):
    profile = badge.build("someone")

    assert profile == {
        "login": "someone",
        "name": "Some One",
        "url": "https://github.com/someone",
        "public_repos": 12,
    }


def test_a_profile_with_no_name_falls_back_to_the_login(badge, monkeypatch):
    monkeypatch.setattr(
        badge.urllib.request,
        "urlopen",
        lambda request, timeout=None: FakeResponse(b'{"login": "someone"}'),
    )

    profile = badge.build("someone")

    assert profile["name"] == "someone"
    assert profile["url"] == "https://github.com/someone"


# --- the command line -------------------------------------------------------


def test_a_refused_login_exits_non_zero_and_writes_nothing(badge, monkeypatch, tmp_path, capsys):
    destination = tmp_path / "badge.json"
    monkeypatch.setattr(badge.sys, "argv", ["github-badge.py", "../orgs/x", "--out", str(destination)])

    assert badge.main() == 1
    assert not destination.exists()
    assert "not a GitHub username" in capsys.readouterr().err


def test_a_valid_login_writes_the_badge_where_it_was_asked(badge, github, monkeypatch, tmp_path):
    destination = tmp_path / "nested" / "badge.json"
    monkeypatch.setattr(badge.sys, "argv", ["github-badge.py", "someone", "--out", str(destination)])

    assert badge.main() == 0
    assert json.loads(destination.read_text())["login"] == "someone"
