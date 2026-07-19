#!/usr/bin/env python3
"""Fabrique le badge GitHub affiche en haut du panneau de statistiques.

    github-badge.py <login> [--out FICHIER] [--size N]

Recupere le profil et l'avatar, reduit l'image, la quantifie sur la palette
xterm-256 et ecrit un JSON que panel.py se contente de dessiner. Tout le
travail couteux (reseau, decodage PNG, reechantillonnage) est fait ici, une
fois a l'installation, pour que le panneau reste instantane et hors ligne.

Aucune dependance : urllib et zlib suffisent. Pas de Pillow, pas de sips,
donc le script marche aussi hors macOS.
"""

import argparse
import json
import struct
import sys
import urllib.error
import urllib.request
import zlib
from pathlib import Path

TIMEOUT = 15
AGENT = "herdr-cockpit"


# --- Decodage PNG ----------------------------------------------------------
def decode_png(blob):
    """Renvoie (largeur, hauteur, lignes de pixels RGB).

    Volontairement minimal : gere les PNG 8 bits RGB et RGBA non entrelaces,
    ce que servent les avatars GitHub. Tout le reste leve une erreur claire
    plutot que de produire une image fausse.
    """
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("ce n'est pas un PNG")

    position, data = 8, b""
    width = height = channels = None
    while position < len(blob):
        (length,) = struct.unpack(">I", blob[position : position + 4])
        kind = blob[position + 4 : position + 8]
        body = blob[position + 8 : position + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour, _, _, interlace = struct.unpack(
                ">IIBBBBB", body[:13]
            )
            if depth != 8 or colour not in (2, 6) or interlace:
                raise ValueError(
                    f"PNG non gere (profondeur {depth}, type {colour}, "
                    f"entrelace {interlace})"
                )
            channels = 3 if colour == 2 else 4
        elif kind == b"IDAT":
            data += body
        elif kind == b"IEND":
            break
        position += 12 + length

    if width is None:
        raise ValueError("en-tete IHDR absent")

    raw = zlib.decompress(data)
    stride = width * channels
    rows, previous, cursor = [], bytearray(stride), 0
    for _ in range(height):
        method = raw[cursor]
        cursor += 1
        line = bytearray(raw[cursor : cursor + stride])
        cursor += stride
        # Defiltrage PNG : chaque ligne est encodee par rapport a sa voisine
        # de gauche (a), du dessus (b) et diagonale (c).
        for x in range(stride):
            a = line[x - channels] if x >= channels else 0
            b = previous[x]
            c = previous[x - channels] if x >= channels else 0
            if method == 1:
                line[x] = (line[x] + a) & 0xFF
            elif method == 2:
                line[x] = (line[x] + b) & 0xFF
            elif method == 3:
                line[x] = (line[x] + (a + b) // 2) & 0xFF
            elif method == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                predictor = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + predictor) & 0xFF
        rows.append([tuple(line[x : x + 3]) for x in range(0, stride, channels)])
        previous = line
    return width, height, rows


def downsample(width, height, rows, target):
    """Reduit a target x target par moyenne de blocs.

    Une moyenne plutot qu'un echantillonnage : sur un avatar reduit d'un
    facteur 8 ou plus, prendre un pixel sur huit produit du bruit.
    """
    out = []
    for ty in range(target):
        y0, y1 = ty * height // target, max(ty * height // target + 1, (ty + 1) * height // target)
        line = []
        for tx in range(target):
            x0, x1 = tx * width // target, max(tx * width // target + 1, (tx + 1) * width // target)
            r = g = b = count = 0
            for y in range(y0, y1):
                for x in range(x0, x1):
                    pr, pg, pb = rows[y][x]
                    r, g, b, count = r + pr, g + pg, b + pb, count + 1
            line.append((r // count, g // count, b // count))
        out.append(line)
    return out


# --- Quantification xterm-256 ----------------------------------------------
CUBE = (0, 95, 135, 175, 215, 255)


def _palette():
    """Indices 16 a 255 seulement.

    Les seize premieres couleurs sont redefinies par le theme du terminal :
    les utiliser rendrait l'avatar dependant du theme actif.
    """
    table = []
    for index in range(216):
        r, g, b = index // 36, (index // 6) % 6, index % 6
        table.append((16 + index, (CUBE[r], CUBE[g], CUBE[b])))
    for index in range(24):
        level = 8 + 10 * index
        table.append((232 + index, (level, level, level)))
    return table


PALETTE = _palette()


def nearest(colour):
    r, g, b = colour
    best_index, best_distance = 16, None
    for index, (pr, pg, pb) in PALETTE:
        # Distance ponderee : l'oeil est plus sensible au vert qu'au bleu.
        distance = 2 * (r - pr) ** 2 + 4 * (g - pg) ** 2 + 3 * (b - pb) ** 2
        if best_distance is None or distance < best_distance:
            best_index, best_distance = index, distance
    return best_index


# --- Reseau ----------------------------------------------------------------
def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def build(login, size):
    profile = json.loads(fetch(f"https://api.github.com/users/{login}"))
    avatar_url = profile.get("avatar_url")
    if not avatar_url:
        raise ValueError(f"aucun avatar pour {login}")

    # On demande une taille superieure a la cible : la moyenne de blocs donne
    # un bien meilleur resultat en partant d'une source large.
    separator = "&" if "?" in avatar_url else "?"
    width, height, rows = decode_png(fetch(f"{avatar_url}{separator}s=128"))
    pixels = downsample(width, height, rows, size * 2)

    # Une cellule de texte porte deux pixels empiles, via le demi-bloc haut.
    cells = []
    for y in range(0, size * 2, 2):
        cells.append(
            [[nearest(pixels[y][x]), nearest(pixels[y + 1][x])] for x in range(size * 2)]
        )

    return {
        "login": profile.get("login") or login,
        "name": profile.get("name") or profile.get("login") or login,
        "url": profile.get("html_url") or f"https://github.com/{login}",
        "public_repos": profile.get("public_repos"),
        "followers": profile.get("followers"),
        "columns": size * 2,
        "lines": size,
        "cells": cells,
    }


def main():
    parser = argparse.ArgumentParser(description="Badge GitHub pour herdr-cockpit")
    parser.add_argument("login", help="identifiant GitHub")
    parser.add_argument(
        "--out",
        default=str(Path.home() / ".config" / "herdr-cockpit" / "github-badge.json"),
    )
    parser.add_argument(
        "--size",
        type=int,
        default=6,
        help="hauteur en lignes de texte (largeur = 2x). Defaut 6, soit 12x6 : "
        "c'est exactement la hauteur libre de l'en-tete du panneau, une ligne "
        "de plus serait rognee.",
    )
    arguments = parser.parse_args()

    try:
        badge = build(arguments.login, arguments.size)
    except urllib.error.HTTPError as error:
        code = error.code
        if code == 404:
            print(f"compte GitHub introuvable : {arguments.login}", file=sys.stderr)
        elif code == 403:
            print("limite de requetes GitHub atteinte, reessayez plus tard", file=sys.stderr)
        else:
            print(f"erreur HTTP {code} en interrogeant GitHub", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError) as error:
        print(f"reseau indisponible : {error}", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"avatar illisible : {error}", file=sys.stderr)
        return 1

    destination = Path(arguments.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(badge), encoding="utf-8")
    print(
        f"badge ecrit : {destination}  "
        f"({badge['login']}, {badge['columns']}x{badge['lines']} cellules)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
