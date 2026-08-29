"""The panel's pure functions: pricing, naming, parsing, aggregation.

These are where a wrong number would be believed. The curses interface around
them is left out on purpose: it renders what these functions return, and a
screen assertion would test the terminal, not the arithmetic.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

# --- rate ------------------------------------------------------------------


def test_a_known_model_gets_its_own_price(panel):
    assert panel.rate("claude-sonnet-5") == (3.0, 15.0)
    assert panel.rate("claude-haiku-4-5") == (1.0, 5.0)


def test_a_dated_variant_falls_back_to_its_prefix(panel):
    # The transcripts carry full ids such as claude-haiku-4-5-20251001.
    assert panel.rate("claude-haiku-4-5-20251001") == (1.0, 5.0)


def test_the_bracketed_suffix_is_stripped_before_pricing(panel):
    assert panel.rate("claude-sonnet-5[1m]") == (3.0, 15.0)


def test_an_unknown_model_is_priced_at_the_fallback_rather_than_at_zero(panel):
    # Guessing zero would quietly under-report spend on any new model.
    assert panel.rate("some-model-released-tomorrow") == panel.FALLBACK


# --- cost ------------------------------------------------------------------


def test_cost_is_expressed_per_million_tokens(panel):
    assert panel.cost("claude-sonnet-5", 1_000_000, 0, 0, 0, 0) == pytest.approx(3.0)
    assert panel.cost("claude-sonnet-5", 0, 1_000_000, 0, 0, 0) == pytest.approx(15.0)


def test_cache_reads_are_billed_at_a_tenth_of_the_input_rate(panel):
    assert panel.cost("claude-sonnet-5", 0, 0, 1_000_000, 0, 0) == pytest.approx(0.3)


def test_cache_writes_cost_more_the_longer_they_live(panel):
    five_minutes = panel.cost("claude-sonnet-5", 0, 0, 0, 1_000_000, 0)
    one_hour = panel.cost("claude-sonnet-5", 0, 0, 0, 0, 1_000_000)
    assert five_minutes == pytest.approx(3.75)
    assert one_hour == pytest.approx(6.0)
    assert one_hour > five_minutes


def test_an_empty_session_costs_nothing(panel):
    assert panel.cost("claude-sonnet-5", 0, 0, 0, 0, 0) == 0.0


# --- pretty_project --------------------------------------------------------


def test_a_project_under_the_home_directory_is_shown_relative_to_it(panel, monkeypatch):
    monkeypatch.setattr(panel, "PROJECTS_ROOT", "")
    home = panel.Path.home()
    assert panel.pretty_project(str(home / "dev" / "acme")) == "dev/acme"


def test_the_projects_root_shortens_the_name_further(panel, monkeypatch):
    home = panel.Path.home()
    monkeypatch.setattr(panel, "PROJECTS_ROOT", str(home / "dev"))
    assert panel.pretty_project(str(home / "dev" / "clients" / "acme")) == "clients/acme"


def test_at_most_two_segments_are_kept(panel, monkeypatch):
    monkeypatch.setattr(panel, "PROJECTS_ROOT", "")
    home = panel.Path.home()
    assert panel.pretty_project(str(home / "a" / "b" / "c" / "d")) == "c/d"


def test_a_path_outside_every_root_is_still_named(panel, monkeypatch):
    monkeypatch.setattr(panel, "PROJECTS_ROOT", "")
    assert panel.pretty_project("/opt/tools/widget") == "tools/widget"


def test_a_missing_working_directory_is_named_unknown_not_left_blank(panel):
    # A blank name would collapse every unattributed session into one nameless
    # row that reads as a real project.
    assert panel.pretty_project("") == "unknown"
    assert panel.pretty_project(None) == "unknown"


def test_a_project_name_containing_a_dash_survives(panel, monkeypatch):
    # The reason cwd is read rather than the directory name under
    # ~/.claude/projects: that one encodes both separators and spaces as
    # dashes, so "my-project" and "my/project" become indistinguishable.
    monkeypatch.setattr(panel, "PROJECTS_ROOT", "")
    home = panel.Path.home()
    assert panel.pretty_project(str(home / "dev" / "my-project")) == "dev/my-project"


# --- parse_file ------------------------------------------------------------


def write_session(path, entries):
    path.write_text("".join(json.dumps(entry) + "\n" for entry in entries))


def usage_entry(date="2026-08-01", model="claude-sonnet-5", cwd="/home/x/dev/acme", **usage):
    fields = {
        "input_tokens": usage.get("tok_in", 0),
        "output_tokens": usage.get("tok_out", 0),
        "cache_read_input_tokens": usage.get("read", 0),
        "cache_creation": {
            "ephemeral_5m_input_tokens": usage.get("w5m", 0),
            "ephemeral_1h_input_tokens": usage.get("w1h", 0),
        },
    }
    return {
        "timestamp": f"{date}T10:00:00.000Z",
        "cwd": cwd,
        "message": {"model": model, "usage": fields},
    }


def test_usage_is_summed_per_day_and_per_model(panel, tmp_path):
    session = tmp_path / "session.jsonl"
    write_session(
        session,
        [
            usage_entry(tok_in=100, tok_out=10),
            usage_entry(tok_in=50, tok_out=5),
            usage_entry(date="2026-08-02", tok_in=7),
        ],
    )

    cwd, rows = panel.parse_file(session)

    assert cwd == "/home/x/dev/acme"
    by_date = {row[0]: row for row in rows}
    assert by_date["2026-08-01"][2:4] == [150, 15]
    assert by_date["2026-08-02"][2] == 7


def test_lines_that_are_not_json_are_skipped_rather_than_crashing_the_panel(panel, tmp_path):
    # A transcript being written to can end mid-line.
    session = tmp_path / "session.jsonl"
    session.write_text(json.dumps(usage_entry(tok_in=100)) + "\n" + '{"usage": broken\n')

    _, rows = panel.parse_file(session)

    assert len(rows) == 1
    assert rows[0][2] == 100


def test_synthetic_models_are_not_billed(panel, tmp_path):
    # Herdr writes placeholders such as <synthetic> for turns with no model.
    session = tmp_path / "session.jsonl"
    write_session(session, [usage_entry(model="<synthetic>", tok_in=999)])

    _, rows = panel.parse_file(session)

    assert rows == []


def test_an_entry_without_a_usable_timestamp_is_skipped(panel, tmp_path):
    session = tmp_path / "session.jsonl"
    entry = usage_entry(tok_in=5)
    entry["timestamp"] = "2026"
    write_session(session, [entry])

    _, rows = panel.parse_file(session)

    assert rows == []


def test_a_file_that_cannot_be_read_yields_nothing_instead_of_raising(panel, tmp_path):
    cwd, rows = panel.parse_file(tmp_path / "does-not-exist.jsonl")

    assert (cwd, rows) == ("", [])


def test_missing_token_fields_count_as_zero(panel, tmp_path):
    session = tmp_path / "session.jsonl"
    session.write_text(
        json.dumps(
            {
                "timestamp": "2026-08-01T10:00:00Z",
                "cwd": "/home/x",
                "message": {"model": "claude-sonnet-5", "usage": {"input_tokens": 3}},
            }
        )
        + "\n"
    )

    _, rows = panel.parse_file(session)

    assert rows[0][2:] == [3, 0, 0, 0, 0]


# --- bucket_key ------------------------------------------------------------


@pytest.mark.parametrize(
    "view,expected",
    [
        ("project", "dev/acme"),
        ("model", "sonnet-5"),
        ("month", "2026-08"),
        ("day", "2026-08-01"),
    ],
)
def test_each_view_groups_by_its_own_key(panel, view, expected):
    assert panel.bucket_key(view, "2026-08-01", "claude-sonnet-5", "dev/acme") == expected


# --- aggregate -------------------------------------------------------------


def records(*rows):
    """(date, model, project, in, out, read, w5m, w1h)."""
    return list(rows)


SAMPLE = records(
    ("2026-08-01", "claude-sonnet-5", "dev/acme", 1_000_000, 0, 0, 0, 0),
    ("2026-08-01", "claude-haiku-4-5", "dev/acme", 1_000_000, 0, 0, 0, 0),
    ("2026-07-15", "claude-sonnet-5", "dev/other", 2_000_000, 0, 0, 0, 0),
)


def test_all_time_keeps_every_record(panel):
    rows, total_cost, total_tokens = panel.aggregate(SAMPLE, None, "project", {}, "cost", "")

    assert {row[0] for row in rows} == {"dev/acme", "dev/other"}
    assert total_tokens == 4_000_000
    assert total_cost == pytest.approx(3.0 + 1.0 + 6.0)


def test_the_period_cuts_off_older_records(panel):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    long_ago = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%d")
    sample = records(
        (today, "claude-sonnet-5", "dev/acme", 1_000_000, 0, 0, 0, 0),
        (long_ago, "claude-sonnet-5", "dev/acme", 9_000_000, 0, 0, 0, 0),
    )

    rows, _, total_tokens = panel.aggregate(sample, 1, "project", {}, "cost", "")

    assert total_tokens == 1_000_000
    assert len(rows) == 1


def test_today_includes_today(panel):
    # days=1 must mean "since this morning", not "since yesterday": an
    # off-by-one here shows an empty panel for the whole first day of use.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sample = records((today, "claude-sonnet-5", "dev/acme", 10, 0, 0, 0, 0))

    _, _, total_tokens = panel.aggregate(sample, 1, "project", {}, "cost", "")

    assert total_tokens == 10


def test_filters_stack_and_every_one_of_them_has_to_pass(panel):
    rows, _, tokens = panel.aggregate(
        SAMPLE, None, "day", {"project": "dev/acme", "model": "sonnet-5"}, "cost", ""
    )

    assert tokens == 1_000_000
    assert rows == [["2026-08-01", pytest.approx(3.0), 1_000_000, 1_000_000, 0, 0, 0]]


def test_a_filter_matching_nothing_yields_an_empty_panel_not_everything(panel):
    rows, cost_total, tokens = panel.aggregate(
        SAMPLE, None, "project", {"project": "dev/nowhere"}, "cost", ""
    )

    assert rows == []
    assert (cost_total, tokens) == (0.0, 0)


def test_the_search_is_case_insensitive_and_matches_the_bucket_key(panel):
    rows, _, _ = panel.aggregate(SAMPLE, None, "project", {}, "cost", "ACME")

    assert [row[0] for row in rows] == ["dev/acme"]


def test_sorting_by_cost_puts_the_most_expensive_first(panel):
    rows, _, _ = panel.aggregate(SAMPLE, None, "project", {}, "cost", "")

    assert [row[0] for row in rows] == ["dev/other", "dev/acme"]


def test_sorting_by_name_is_alphabetical_for_projects_and_recent_first_for_days(panel):
    by_project, _, _ = panel.aggregate(SAMPLE, None, "project", {}, "name", "")
    by_day, _, _ = panel.aggregate(SAMPLE, None, "day", {}, "name", "")

    assert [row[0] for row in by_project] == ["dev/acme", "dev/other"]
    assert [row[0] for row in by_day] == ["2026-08-01", "2026-07-15"]


def test_aggregating_nothing_is_not_an_error(panel):
    assert panel.aggregate([], 7, "project", {}, "cost", "") == ([], 0.0, 0)


# --- human -----------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "0"),
        (999, "999"),
        (1_000, "1.0k"),
        (1_500, "1.5k"),
        (1_000_000, "1.0M"),
        (2_500_000_000, "2.5G"),
    ],
)
def test_large_counts_are_shortened_with_a_unit(panel, value, expected):
    assert panel.human(value) == expected
