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
import sys
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT = 15


def build(login):
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
