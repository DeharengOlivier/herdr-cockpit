#!/usr/bin/env python3
"""Interactive agent spend panel.

Stackable filters (project, model, month, day), four views, sorting, search.
Keyboard and mouse navigation. Run: python3 panel.py
"""

import curses
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------------- pricing
PRICING = {
    "claude-fable-5": (10.0, 50.0),
    "claude-mythos-5": (10.0, 50.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
FALLBACK = (5.0, 25.0)
READ_MULT, WRITE_5M_MULT, WRITE_1H_MULT = 0.10, 1.25, 2.00

PROJECTS_DIR = Path.home() / ".claude" / "projects"
CACHE_PATH = (
    Path(os.environ.get("HERDR_PLUGIN_STATE_DIR", Path.home() / ".cache" / "agent-stats"))
    / "usage-cache.json"
)

PERIODS = [
    ("Today", 1),
    ("7 days", 7),
    ("30 days", 30),
    ("90 days", 90),
    ("All", None),
]
# internal key, displayed label
VIEWS = [
    ("project", "Projects"),
    ("model", "Models"),
    ("month", "Months"),
    ("day", "Days"),
]
SORTS = [("cost", "cost"), ("tokens", "tokens"), ("name", "name")]


# ------------------------------------------------------------------ processing
def rate(model):
    base = model.split("[")[0].strip()
    if base in PRICING:
        return PRICING[base]
    for known, price in PRICING.items():
        if base.startswith(known):
            return price
    return FALLBACK


def cost(model, tok_in, tok_out, read, w5m, w1h):
    price_in, price_out = rate(model)
    return (
        tok_in * price_in
        + tok_out * price_out
        + read * price_in * READ_MULT
        + w5m * price_in * WRITE_5M_MULT
        + w1h * price_in * WRITE_1H_MULT
    ) / 1_000_000


# Shared projects root, set by the PROJECTS_ROOT directive in spaces.conf and
# passed along by bootstrap.sh. Its only purpose is to shorten the displayed
# names: without it we fall back to the home directory.
PROJECTS_ROOT = os.environ.get("COCKPIT_PROJECTS_ROOT", "")


def pretty_project(cwd):
    """Readable project name derived from a session's working directory.

    We read the cwd field of the session file, never the directory name under
    ~/.claude/projects: that one encodes both separators AND spaces as dashes,
    which makes decoding ambiguous as soon as a project name contains a dash
    itself: "my-project" becomes indistinguishable from "my/project".
    """
    if not cwd:
        return "unknown"
    path = Path(cwd)
    parts = None
    for base in (PROJECTS_ROOT, str(Path.home())):
        if not base:
            continue
        try:
            parts = path.relative_to(base).parts
            break
        except ValueError:
            continue
    if parts is None:
        parts = tuple(p for p in path.parts if p != "/")
    if not parts:
        return "~"
    # Two segments at most: enough to tell apart two same-named projects filed
    # under different groups, without overflowing the column.
    return "/".join(parts[-2:]) if len(parts) > 1 else parts[0]


def parse_file(path):
    rows = defaultdict(lambda: [0, 0, 0, 0, 0])
    cwd = ""
    try:
        with open(path, "r", errors="replace") as handle:
            for line in handle:
                if '"usage"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if not cwd:
                    cwd = entry.get("cwd") or ""
                message = entry.get("message") or {}
                usage = message.get("usage") or {}
                if not usage:
                    continue
                model = message.get("model") or "unknown"
                if model.startswith("<"):
                    continue
                stamp = entry.get("timestamp") or ""
                if len(stamp) < 10:
                    continue
                creation = usage.get("cache_creation") or {}
                acc = rows[(stamp[:10], model)]
                acc[0] += usage.get("input_tokens") or 0
                acc[1] += usage.get("output_tokens") or 0
                acc[2] += usage.get("cache_read_input_tokens") or 0
                acc[3] += creation.get("ephemeral_5m_input_tokens") or 0
                acc[4] += creation.get("ephemeral_1h_input_tokens") or 0
    except OSError:
        return "", []
    return cwd, [[date, model] + acc for (date, model), acc in rows.items()]


def collect(progress=None):
    cache = {}
    if CACHE_PATH.exists():
        try:
            cache = json.loads(CACHE_PATH.read_text())
        except ValueError:
            cache = {}
    records = []
    if not PROJECTS_DIR.is_dir():
        return records
    files = list(PROJECTS_DIR.rglob("*.jsonl"))
    for index, path in enumerate(files):
        if progress and index % 200 == 0:
            progress(index, len(files))
        try:
            stat = path.stat()
        except OSError:
            continue
        key = str(path)
        signature = [int(stat.st_mtime), stat.st_size]
        cached = cache.get(key)
        if cached and cached.get("sig") == signature and "cwd" in cached:
            cwd, rows = cached["cwd"], cached["rows"]
        else:
            cwd, rows = parse_file(path)
            cache[key] = {"sig": signature, "cwd": cwd, "rows": rows}
        project = pretty_project(cwd)
        for row in rows:
            records.append((row[0], row[1], project, *row[2:]))
    alive = {str(p) for p in files}
    cache = {k: v for k, v in cache.items() if k in alive}
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache))
    except OSError:
        pass
    return records


def bucket_key(view, date, model, project):
    if view == "project":
        return project
    if view == "model":
        return model.replace("claude-", "")
    if view == "month":
        return date[:7]
    return date


def aggregate(records, days, view, filters, sort_key, search):
    """Apply period + stacked filters + search, then group according to the view."""
    cut = (
        "0000-00-00"
        if days is None
        else (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    )
    buckets = defaultdict(lambda: [0.0, 0, 0, 0, 0, 0])
    total_cost, total_tokens = 0.0, 0
    needle = search.lower()
    for date, model, project, tok_in, tok_out, read, w5m, w1h in records:
        if date < cut:
            continue
        # Stackable filters: every one of them has to pass.
        if filters.get("project") and project != filters["project"]:
            continue
        if filters.get("model") and model.replace("claude-", "") != filters["model"]:
            continue
        if filters.get("month") and date[:7] != filters["month"]:
            continue
        if filters.get("day") and date != filters["day"]:
            continue
        key = bucket_key(view, date, model, project)
        if needle and needle not in str(key).lower():
            continue
        line_cost = cost(model, tok_in, tok_out, read, w5m, w1h)
        tokens = tok_in + tok_out + read + w5m + w1h
        acc = buckets[key]
        acc[0] += line_cost
        acc[1] += tokens
        acc[2] += tok_in
        acc[3] += tok_out
        acc[4] += read
        acc[5] += w5m + w1h
        total_cost += line_cost
        total_tokens += tokens
    rows = [[key] + values for key, values in buckets.items()]
    if sort_key == "cost":
        rows.sort(key=lambda r: r[1], reverse=True)
    elif sort_key == "tokens":
        rows.sort(key=lambda r: r[2], reverse=True)
    else:
        rows.sort(key=lambda r: str(r[0]), reverse=view in ("month", "day"))
    return rows, total_cost, total_tokens


def quotas():
    # quota-axi is an optional dependency: the panel works without it, it only
    # loses the subscription quota section. We say so instead of making the
    # section silently disappear.
    binary = Path.home() / ".local" / "bin" / "quota-axi"
    if not binary.exists():
        return [
            (
                "quota-axi",
                "",
                "missing",
                None,
                "npm install -g quota-axi  to show quotas",
            )
        ]
    try:
        result = subprocess.run(
            [str(binary), "--json", "--provider", "claude,codex,cursor,copilot,grok"],
            capture_output=True,
            text=True,
            timeout=25,
        )
        data = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return []
    out = []
    for provider in data.get("providers") or []:
        name = provider.get("label") or provider.get("provider") or "?"
        plan = provider.get("plan") or ""
        windows = provider.get("windows") or []
        if not windows:
            state = provider.get("state") or {}
            out.append((name, plan, "", None, state.get("error") or "percentage unavailable"))
            continue
        for entry in windows:
            if entry.get("percentUsed") is not None:
                pct = float(entry["percentUsed"])
            elif entry.get("percentRemaining") is not None:
                pct = 100.0 - float(entry["percentRemaining"])
            else:
                pct = None
            resets = str(entry.get("resetsAt") or "").replace("T", " ")[:16]
            out.append((name, plan, entry.get("label") or entry.get("id") or "", pct, resets))
    return out


# -------------------------------------------------------------- GitHub profile
BADGE_PATH = Path.home() / ".config" / "herdr-cockpit" / "github-badge.json"


def load_badge():
    """Profile produced by bin/github-badge.py. Missing as long as GITHUB_USER
    is not set in spaces.conf, in which case the panel simply never mentions it.
    """
    try:
        with open(BADGE_PATH, encoding="utf-8") as handle:
            badge = json.load(handle)
    except (OSError, ValueError):
        return None
    return badge if badge.get("url") else None


def open_url(url):
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        subprocess.run(
            [opener, url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def human(n):
    for unit, size in (("G", 1e9), ("M", 1e6), ("k", 1e3)):
        if n >= size:
            return f"{n / size:.1f}{unit}"
    return str(int(n))


# ------------------------------------------------------------------- interface
class Panel:
    def __init__(self, screen):
        self.screen = screen
        self.period = 2
        self.view = 0
        self.sort = 0
        self.selection = 0
        self.scroll = 0
        self.filters = {}
        self.order = []  # order of application, so we can drop the last one
        self.search = ""
        self.searching = False
        self.show_quotas = True
        self.records, self.quota_rows, self.rows = [], [], []
        self.total_cost, self.total_tokens = 0.0, 0
        self.hitboxes = {}
        self.compact = self.tiny = False
        self.badge = load_badge()
        self.show_badge = True

    # -- data ------------------------------------------------------------
    def load(self):
        self.records = collect(lambda d, t: self.flash(f"Reading sessions...  {d}/{t}"))
        self.quota_rows = quotas()
        self.recompute()

    def recompute(self):
        self.rows, self.total_cost, self.total_tokens = aggregate(
            self.records,
            PERIODS[self.period][1],
            VIEWS[self.view][0],
            self.filters,
            SORTS[self.sort][0],
            self.search,
        )
        self.selection = min(self.selection, max(0, len(self.rows) - 1))
        self.scroll = 0

    def flash(self, message):
        try:
            height, width = self.screen.getmaxyx()
            self.screen.addnstr(height - 1, 2, message.ljust(width - 4), width - 4, curses.A_DIM)
            self.screen.refresh()
        except curses.error:
            pass

    # -- filters ---------------------------------------------------------
    def apply_filter(self):
        """Pressing enter on a row turns it into a filter, whatever the view."""
        if not self.rows:
            return
        key = VIEWS[self.view][0]
        value = str(self.rows[self.selection][0])
        self.filters[key] = value
        if key not in self.order:
            self.order.append(key)
        # Switch to a view that still brings new information.
        remaining = [i for i, (name, _) in enumerate(VIEWS) if name not in self.filters]
        self.view = remaining[0] if remaining else self.view
        self.selection = 0
        self.recompute()

    def pop_filter(self):
        if not self.order:
            return False
        key = self.order.pop()
        self.filters.pop(key, None)
        self.recompute()
        return True

    def clear_filters(self):
        self.filters, self.order = {}, []
        self.search = ""
        self.recompute()

    # -- rendering -------------------------------------------------------
    def draw(self):
        self.screen.erase()
        self.hitboxes = {}
        height, width = self.screen.getmaxyx()
        if height < 9 or width < 34:
            self.screen.addnstr(0, 0, "Window too small", max(1, width - 1))
            self.screen.refresh()
            return
        self.compact = width < 92
        self.tiny = width < 62

        title = "  AGENT SPEND"
        totals = (
            f"  {PERIODS[self.period][0]}   ${self.total_cost:,.2f}   "
            f"{human(self.total_tokens)} tokens   ({len(self.rows)} rows)"
        )
        self.screen.addnstr(0, 0, title, width - 1, curses.color_pair(4) | curses.A_BOLD)
        self.screen.addnstr(1, 0, totals, width - 1, curses.color_pair(2) | curses.A_BOLD)

        # Actual occupancy of the first three rows. The badge relies on it to
        # never write over them, instead of guessing a floor.
        # Row 2 is empty: that is the one taking the longest text.
        occupied = [len(title), len(totals), 0]

        self.draw_chips(3, "period", [p[0] for p in PERIODS], self.period, "period")
        self.draw_chips(4, "view", [v[1] for v in VIEWS], self.view, "view")
        self.draw_chips(5, "sort", [s[1] for s in SORTS], self.sort, "sort")

        row = 6
        if self.filters or self.search or self.searching:
            bits = [f"{k}={v}" for k, v in self.filters.items()]
            if self.search or self.searching:
                bits.append(f"text='{self.search}'" + ("_" if self.searching else ""))
            self.screen.addnstr(
                row, 2, ("filters  " + "  ·  ".join(bits))[: width - 3],
                width - 3, curses.color_pair(3) | curses.A_BOLD,
            )
            row += 1

        # The badge is drawn last over the header area, whose right half is
        # empty. It shifts nothing: the table keeps its place.
        self.draw_badge(width, row, occupied)

        top = row + 1
        quota_height = min(len(self.quota_rows) + 2, 12) if self.show_quotas else 0
        self.draw_table(top, height - top - quota_height - 2, width)
        if self.show_quotas and quota_height > 2:
            self.draw_quotas(height - quota_height - 1, quota_height, width)

        hint = (
            "  1-5 period  tab view  s sort  / search  enter filter  "
            "esc remove  c clear  q quotas  r reload  x quit"
        )
        if self.badge:
            hint += "  p/o profile"
        self.screen.addnstr(height - 1, 0, hint[: width - 1], width - 1, curses.A_DIM)
        self.screen.refresh()

    def draw_badge(self, width, header_rows, occupied):
        """GitHub profile, pinned to the top right of the header.

        Each line decides on its own whether it fits, by comparing its length
        to the actual occupancy of its row rather than to a global threshold.
        A narrow pane therefore loses the repo counter first, then the name,
        and keeps the link to the very end, instead of losing everything at
        once.

        The URL is written as plain text, with no OSC 8 sequence: curses counts
        the characters it writes to track the cursor, so an escape sequence
        would shift the whole display. WezTerm recognises it and makes it
        clickable, and the click is handled here anyway.
        """
        if not self.badge or not self.show_badge:
            return

        url = self.badge.get("url") or ""
        name = self.badge.get("name") or ""
        repos = self.badge.get("public_repos")

        # Row 2 for the URL: it is empty, so it accepts the longest text. The
        # counter goes to row 1, the one most filled on the left by the totals,
        # and therefore disappears first.
        entries = [(2, url, curses.A_DIM), (0, name, curses.A_BOLD)]
        if repos is not None:
            entries.append((1, f"{repos} public repos", curses.A_DIM))

        for row, text, attribute in entries:
            if not text or row >= header_rows:
                continue
            start = width - len(text) - 2
            if start <= occupied[row] + 1:
                continue
            try:
                self.screen.addnstr(row, start, text, len(text), attribute)
            except curses.error:
                continue
            if text == url:
                self.hitboxes[(row, start, start + len(text))] = ("profile", 0)

    def draw_chips(self, row, label, items, active, kind):
        col = 2
        self.screen.addnstr(row, col, f"{label:<9}", 10, curses.A_DIM)
        col += 10
        for index, name in enumerate(items):
            text = f" {name} "
            style = (
                curses.color_pair(5) | curses.A_BOLD if index == active else curses.color_pair(6)
            )
            try:
                self.screen.addnstr(row, col, text, len(text), style)
            except curses.error:
                return
            self.hitboxes[(row, col, col + len(text))] = (kind, index)
            col += len(text) + 1

    def draw_table(self, top, table_height, width):
        name_width = 18 if self.tiny else (24 if self.compact else 30)
        if self.tiny:
            header = f"  {'':<{name_width}}{'cost':>11}"
        elif self.compact:
            header = f"  {'':<{name_width}}{'cost':>11}{'tokens':>10}"
        else:
            header = (
                f"  {'':<{name_width}}{'cost':>11}{'tokens':>10}"
                f"  {'in':>8}{'out':>8}{'cache':>9}"
            )
        try:
            self.screen.addnstr(top, 0, header[: width - 1], width - 1, curses.A_DIM)
        except curses.error:
            return
        visible = table_height - 1
        if visible < 1:
            return
        if self.selection >= self.scroll + visible:
            self.scroll = self.selection - visible + 1
        if self.selection < self.scroll:
            self.scroll = self.selection
        biggest = max((r[1] for r in self.rows), default=0) or 1

        for offset in range(visible):
            index = self.scroll + offset
            if index >= len(self.rows):
                break
            label, amount, tokens, tok_in, tok_out, read, write = self.rows[index]
            row = top + 1 + offset
            style = curses.color_pair(5) if index == self.selection else curses.A_NORMAL
            marker = "▸" if index == self.selection else " "
            name = str(label)[: name_width - 1]
            money = "$" + format(amount, ",.2f")
            if self.tiny:
                line = f" {marker}{name:<{name_width}}{money:>11}"
            elif self.compact:
                line = f" {marker}{name:<{name_width}}{money:>11}{human(tokens):>10}"
            else:
                line = (
                    f" {marker}{name:<{name_width}}{money:>11}{human(tokens):>10}"
                    f"  {human(tok_in):>8}{human(tok_out):>8}{human(read + write):>9}"
                )
            try:
                self.screen.addnstr(row, 0, line[: width - 1], width - 1, style)
            except curses.error:
                break
            self.hitboxes[(row, 0, width)] = ("row", index)
            bar_col = len(line) + 2
            if width > bar_col + 12:
                length = int((width - bar_col - 2) * amount / biggest)
                try:
                    self.screen.addnstr(
                        row, bar_col, "█" * max(0, length), width - bar_col - 1,
                        curses.color_pair(2),
                    )
                except curses.error:
                    pass

    def draw_quotas(self, top, box_height, width):
        try:
            self.screen.addnstr(
                top, 2, "QUOTAS", width - 3, curses.A_BOLD | curses.color_pair(4)
            )
        except curses.error:
            return
        for offset, (name, plan, label, pct, note) in enumerate(self.quota_rows):
            row = top + 1 + offset
            if offset >= box_height - 1:
                break
            head = f"  {name} {plan}".rstrip()
            head_w = 14 if self.tiny else 20
            label_w = 10 if self.tiny else 16
            bar_col = head_w + label_w
            if pct is None:
                try:
                    self.screen.addnstr(
                        row, 0, f"{head:<{bar_col}}{note}"[: width - 1], width - 1, curses.A_DIM
                    )
                except curses.error:
                    break
                continue
            width_bar = max(6, min(22, width - bar_col - 20))
            filled = max(0, min(width_bar, round(width_bar * pct / 100)))
            colour = (
                curses.color_pair(2)
                if pct < 60
                else (curses.color_pair(3) if pct < 90 else curses.color_pair(1))
            )
            try:
                self.screen.addnstr(
                    row, 0,
                    f"{head[: head_w - 1]:<{head_w}}{label[: label_w - 1]:<{label_w}}",
                    width - 1,
                )
                self.screen.addnstr(row, bar_col, "█" * filled, max(0, width - bar_col - 1), colour)
                self.screen.addnstr(
                    row, bar_col + filled, "░" * (width_bar - filled),
                    max(0, width - bar_col - filled - 1), curses.A_DIM,
                )
                tail = f" {pct:5.1f}%"
                if pct >= 100:
                    tail += " USED UP"
                elif not self.tiny:
                    tail += f"  {note}"
                room = max(0, width - bar_col - width_bar - 1)
                self.screen.addnstr(
                    row, bar_col + width_bar, tail[:room], room, colour | curses.A_BOLD
                )
            except curses.error:
                break

    # -- interactions ----------------------------------------------------
    def click(self, y, x):
        for (row, start, end), (kind, index) in self.hitboxes.items():
            if row == y and start <= x < end:
                if kind == "period":
                    self.period = index
                elif kind == "view":
                    self.view = index
                elif kind == "sort":
                    self.sort = index
                elif kind == "row":
                    if self.selection == index:
                        self.apply_filter()
                        return
                    self.selection = index
                    return
                elif kind == "profile":
                    url = (self.badge or {}).get("url") or ""
                    self.flash(f"Opened: {url}" if open_url(url) else "No browser available")
                    return
                self.recompute()
                return

    def handle_search(self, key):
        if key in (curses.KEY_ENTER, 10, 13):
            self.searching = False
        elif key == 27:
            self.searching = False
            self.search = ""
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            self.search = self.search[:-1]
        elif 32 <= key < 127:
            self.search += chr(key)
        self.recompute()

    def run(self):
        self.load()
        while True:
            self.draw()
            try:
                key = self.screen.getch()
            except KeyboardInterrupt:
                return
            if self.searching:
                self.handle_search(key)
                continue
            if key in (ord("x"), ord("X")):
                return
            if key == 27:
                if not self.pop_filter():
                    pass
            elif key == ord("/"):
                self.searching = True
            elif key in (curses.KEY_DOWN, ord("j")):
                self.selection = min(self.selection + 1, max(0, len(self.rows) - 1))
            elif key in (curses.KEY_UP, ord("k")):
                self.selection = max(0, self.selection - 1)
            elif key == curses.KEY_NPAGE:
                self.selection = min(self.selection + 10, max(0, len(self.rows) - 1))
            elif key == curses.KEY_PPAGE:
                self.selection = max(0, self.selection - 10)
            elif key in (curses.KEY_ENTER, 10, 13):
                self.apply_filter()
            elif key == ord("\t"):
                self.view = (self.view + 1) % len(VIEWS)
                self.recompute()
            elif key in (ord("s"), ord("S")):
                self.sort = (self.sort + 1) % len(SORTS)
                self.recompute()
            elif key in (ord("c"), ord("C")):
                self.clear_filters()
            elif ord("1") <= key <= ord("5"):
                self.period = key - ord("1")
                self.recompute()
            elif key in (ord("q"), ord("Q")):
                self.show_quotas = not self.show_quotas
            elif key in (ord("p"), ord("P")) and self.badge:
                self.show_badge = not self.show_badge
            elif key in (ord("o"), ord("O")) and self.badge:
                url = self.badge.get("url") or ""
                self.flash(f"Opened: {url}" if open_url(url) else "No browser available")
            elif key in (ord("r"), ord("R")):
                self.flash("Reloading...")
                self.load()
            elif key == curses.KEY_MOUSE:
                try:
                    _, x, y, _, _ = curses.getmouse()
                    self.click(y, x)
                except curses.error:
                    pass


def main(screen):
    curses.curs_set(0)
    curses.use_default_colors()
    for index, colour in enumerate(
        (curses.COLOR_RED, curses.COLOR_GREEN, curses.COLOR_YELLOW, curses.COLOR_CYAN), start=1
    ):
        curses.init_pair(index, colour, -1)
    curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(6, curses.COLOR_WHITE, -1)
    curses.mousemask(curses.ALL_MOUSE_EVENTS)
    screen.keypad(True)
    Panel(screen).run()


if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        sys.exit(0)
