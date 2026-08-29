#!/usr/bin/env python3
"""Fetches the GitHub profile shown at the top of the stats panel.

    github-badge.py <login> [--out FILE]

Writes a small JSON blob (name, URL, repository count) that panel.py merely
displays. The network call happens once at install time, never when the panel
starts, which therefore stays instant and works offline.

No dependency: urllib is enough. No authentication: only the public
/users/<login> endpoint is queried, without a token.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT = 15

# A GitHub login is alphanumeric, may carry single hyphens between characters,
# and is 39 characters at most.
#
# The value arrives from GITHUB_USER in spaces.conf and is dropped into an API
# path, so it is a boundary. It is validated rather than percent-encoded, on
# purpose: "../orgs/anthropic" is not a login that needs escaping, it is not a
# login, and encoding it would turn a typo into a puzzling 404 instead of a
# sentence saying what is wrong. The alphabet below is URL-safe by
# construction, so nothing downstream has to escape it again.
# \Z rather than $: $ also matches just before a trailing newline, which would
# let "someone\n" through and put a control character in the URL.
LOGIN_PATTERN = re.compile(r"\A[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}\Z")


class InvalidLogin(ValueError):
    """The value in GITHUB_USER is not shaped like a GitHub username."""


def validate_login(login):
    """Return the login, or raise if it is not one.

    Args:
        login: The value read from GITHUB_USER.

    Returns:
        The same string, once it is known to be a login.

    Raises:
        InvalidLogin: The value is empty, too long, or carries a character
            that no GitHub username can contain.
    """
    if not LOGIN_PATTERN.match(login or ""):
        raise InvalidLogin(
            f"{login!r} is not a GitHub username. Expected letters, digits and "
            "single hyphens, 39 characters at most."
        )
    return login


def build(login):
    validate_login(login)
    request = urllib.request.Request(
        f"https://api.github.com/users/{login}",
        headers={"User-Agent": "herdr-cockpit"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        profile = json.load(response)

    return {
        "login": profile.get("login") or login,
        "name": profile.get("name") or profile.get("login") or login,
        "url": profile.get("html_url") or f"https://github.com/{login}",
        "public_repos": profile.get("public_repos"),
    }


def main():
    parser = argparse.ArgumentParser(description="GitHub profile for herdr-cockpit")
    parser.add_argument("login", help="GitHub username")
    parser.add_argument(
        "--out",
        default=str(Path.home() / ".config" / "herdr-cockpit" / "github-badge.json"),
    )
    arguments = parser.parse_args()

    try:
        badge = build(arguments.login)
    except InvalidLogin as error:
        print(error, file=sys.stderr)
        return 1
    except urllib.error.HTTPError as error:
        if error.code == 404:
            print(f"GitHub account not found: {arguments.login}", file=sys.stderr)
        elif error.code == 403:
            print("GitHub rate limit reached, try again later", file=sys.stderr)
        else:
            print(f"HTTP error {error.code} while querying GitHub", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError) as error:
        print(f"network unavailable: {error}", file=sys.stderr)
        return 1
    except (ValueError, KeyError) as error:
        print(f"unexpected GitHub response: {error}", file=sys.stderr)
        return 1

    destination = Path(arguments.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(badge), encoding="utf-8")
    print(f"profile written: {destination}  ({badge['name']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
