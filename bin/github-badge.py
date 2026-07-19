#!/usr/bin/env python3
"""Recupere le profil GitHub affiche en haut du panneau de statistiques.

    github-badge.py <login> [--out FICHIER]

Ecrit un petit JSON (nom, URL, nombre de depots) que panel.py se contente
d'afficher. L'appel reseau a lieu une fois a l'installation, jamais au
lancement du panneau, qui reste donc instantane et fonctionne hors ligne.

Aucune dependance : urllib suffit. Aucune authentification : seul le point
d'acces public /users/<login> est interroge, sans jeton.
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
    parser = argparse.ArgumentParser(description="Profil GitHub pour herdr-cockpit")
    parser.add_argument("login", help="identifiant GitHub")
    parser.add_argument(
        "--out",
        default=str(Path.home() / ".config" / "herdr-cockpit" / "github-badge.json"),
    )
    arguments = parser.parse_args()

    try:
        badge = build(arguments.login)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            print(f"compte GitHub introuvable : {arguments.login}", file=sys.stderr)
        elif error.code == 403:
            print("limite de requetes GitHub atteinte, reessayez plus tard", file=sys.stderr)
        else:
            print(f"erreur HTTP {error.code} en interrogeant GitHub", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError) as error:
        print(f"reseau indisponible : {error}", file=sys.stderr)
        return 1
    except (ValueError, KeyError) as error:
        print(f"reponse GitHub inattendue : {error}", file=sys.stderr)
        return 1

    destination = Path(arguments.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(badge), encoding="utf-8")
    print(f"profil ecrit : {destination}  ({badge['name']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
