"""Unit tests for ``bin/cloude_org.py``.

Ports every assertion from the inline ``_smoke()`` helper into focused
pytest cases, and expands coverage to the helpers ``_smoke()`` didn't
exercise (``parse_heading`` / ``ball_tag`` edge cases,
``_format_duration``, ``_parse_ts``, the missing-log error path).
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from cloude_org import (
    BALL_TAGS,
    DOD_KEYWORDS,
    DodConsistencyError,
    PLAN_APPROVED_BULLET,
    STAGE_DOD,
    STAGE_KEYWORDS,
    _format_duration,
    _parse_ts,
    append_log_entry_skeleton,
    ball_tag,
    dod_marker_path,
    find_log_section,
    iter_log_entries,
    latest_log_entry,
    mark_plan_approved,
    now_ts,
    parse_heading,
    set_dod_verdict,
)


SAMPLE = """\
#+TITLE: t
#+TODO: PLANNING ITERATING | COMPLETE
#+TODO: PENDING UNSATISFIABLE | PASS

* ITERATING title :agent:
  :PROPERTIES:
  :ID: t
  :END:

** Goal
   stuff

** Log
*** [2026-05-20 Wed 10:00] PLANNING (via /promote)
    :PROPERTIES:
    :STAGE:       PLANNING
    :ENTERED:     [2026-05-20 Wed 10:00]
    :ENTERED_VIA: /promote
    :EXITED:      [2026-05-20 Wed 11:30]
    :DURATION:    1h 30m
    :END:
**** Request
     do stuff
**** Work
     did stuff
**** [3/3] PASS DoD
     CLOSED: [2026-05-20 Wed 11:28]
     :LOGBOOK:
     - State "PASS"    from "PENDING" [2026-05-20 Wed 11:28]
     - State "PENDING" from ""        [2026-05-20 Wed 10:00]
     :END:
     - [X] One.
     - [X] Two.
     - [-] Three (N/A).

*** [2026-05-20 Wed 11:30] ITERATING (via /advance from PLANNING)
    :PROPERTIES:
    :STAGE:       ITERATING
    :ENTERED:     [2026-05-20 Wed 11:30]
    :ENTERED_VIA: /advance from PLANNING
    :END:
**** Request
     impl
**** Work
     in progress
**** [/] PENDING DoD
     - [ ] A.
     - [ ] B.
     - [ ] C.
"""


PLANNING_SAMPLE = """\
#+TITLE: t
#+TODO: PLANNING ITERATING | COMPLETE
#+TODO: PENDING UNSATISFIABLE | PASS

* PLANNING title :user:
  :PROPERTIES:
  :ID: t
  :END:

** Log
*** [2026-05-20 Wed 10:00] PLANNING (via /promote)
    :PROPERTIES:
    :STAGE:       PLANNING
    :ENTERED:     [2026-05-20 Wed 10:00]
    :ENTERED_VIA: /promote
    :END:
**** Request
**** Work
**** [0/3] PENDING DoD
     - [ ] The plan is written into the task's org file.
     - [ ] The user has approved the plan.
     - [ ] A draft PR has been created on GitHub.
"""


# ---------------------------------------------------------------------------
# Constants and trivial helpers
# ---------------------------------------------------------------------------


class TestConstants:
    def test_ball_tags_priority_order(self):
        assert BALL_TAGS == ("agent", "user", "blocked")

    def test_dod_keywords_full_set(self):
        assert DOD_KEYWORDS == ("PENDING", "UNSATISFIABLE", "PASS")

    def test_stage_keywords_match_state_machine(self):
        assert STAGE_KEYWORDS == (
            "PLANNING", "ITERATING", "REVIEW", "MERGING", "COMPLETE", "DROPPED",
        )

    def test_plan_approved_bullet_is_second_planning_dod_bullet(self):
        # The helper relies on this exact text — guard against drift.
        assert PLAN_APPROVED_BULLET == STAGE_DOD["PLANNING"][1]
        assert PLAN_APPROVED_BULLET == "The user has approved the plan."

    def test_every_stage_has_dod_bullets(self):
        for stage in STAGE_KEYWORDS:
            assert STAGE_DOD[stage], f"{stage} has no DoD bullets"


class TestNowTs:
    def test_format_round_trips_through_parse(self):
        body = now_ts()
        assert _parse_ts(body) is not None


class TestDodMarkerPath:
    def test_path_includes_task_filename(self):
        p = dod_marker_path("/some/dir/2026-01-01-foo.org")
        assert p == Path("/tmp/cloude-dod-pending.2026-01-01-foo.org")

    def test_accepts_pathlib_input(self):
        p = dod_marker_path(Path("/x/y/bar.org"))
        assert p.name == "cloude-dod-pending.bar.org"


# ---------------------------------------------------------------------------
# parse_heading / ball_tag
# ---------------------------------------------------------------------------


class TestParseHeading:
    def test_finds_keyword_and_tag(self):
        assert parse_heading("* ITERATING task :agent:\n") == ("ITERATING", ["agent"])

    def test_no_tag_returns_empty_list(self):
        assert parse_heading("* PLANNING bare task\n") == ("PLANNING", [])

    def test_multiple_tags(self):
        assert parse_heading("* REVIEW task :agent:user:\n") == (
            "REVIEW",
            ["agent", "user"],
        )

    def test_title_with_colon_word_inside(self):
        # Embedded `:user:` mid-title is not a tag chain — only the
        # one at end-of-line is.
        assert parse_heading("* PLANNING fix :user: feedback :agent:\n") == (
            "PLANNING",
            ["agent"],
        )

    def test_returns_none_when_no_heading(self):
        assert parse_heading("just some text\n") is None

    def test_finds_first_heading_only(self):
        text = "* PLANNING first :agent:\n** sub\n* ITERATING second :user:\n"
        # The first top-level heading wins.
        assert parse_heading(text) == ("PLANNING", ["agent"])


class TestBallTag:
    def test_priority_order_picks_agent_over_user(self):
        # When multiple ball tags coexist (a misconfigured state), the
        # higher-priority one wins by BALL_TAGS order.
        assert ball_tag(["user", "agent"]) == "agent"

    def test_picks_user_over_blocked(self):
        assert ball_tag(["blocked", "user"]) == "user"

    def test_no_ball_tag_in_list_returns_empty(self):
        assert ball_tag(["someproject", "tag1"]) == ""

    def test_empty_list(self):
        assert ball_tag([]) == ""


# ---------------------------------------------------------------------------
# find_log_section / iter_log_entries / latest_log_entry
# ---------------------------------------------------------------------------


class TestFindLogSection:
    def test_finds_log_in_sample(self):
        span = find_log_section(SAMPLE)
        assert span is not None
        start, end = span
        assert SAMPLE[start:start + 6] == "** Log"
        # End is just before the next ** heading or the local-vars block;
        # in SAMPLE there's neither, so end is len(SAMPLE).
        assert end == len(SAMPLE)

    def test_returns_none_when_log_missing(self):
        body = "* PLANNING title :user:\n** Goal\n   nope\n"
        assert find_log_section(body) is None

    def test_stops_at_next_second_level_heading(self):
        body = (
            "* PLANNING t :agent:\n"
            "** Log\n"
            "*** entry\n"
            "** Other\n"
            "   stuff\n"
        )
        span = find_log_section(body)
        assert span is not None
        start, end = span
        assert body[end:end + 8] == "** Other"


class TestIterLogEntries:
    def test_parses_two_entries(self):
        entries = iter_log_entries(SAMPLE)
        assert len(entries) == 2

    def test_first_entry_pass_planning(self):
        first = iter_log_entries(SAMPLE)[0]
        assert first["stage"] == "PLANNING"
        assert first["dod_verdict"] == "PASS"
        assert first["dod_cookie"] == "[3/3]"
        assert first["dod_checkboxes"] == ["ticked", "ticked", "na"]
        assert first["entered"] == "2026-05-20 Wed 10:00"
        assert first["exited"] == "2026-05-20 Wed 11:30"
        assert first["duration"] == "1h 30m"
        assert first["request"].strip() == "do stuff"
        assert first["work"].strip() == "did stuff"

    def test_second_entry_pending_iterating(self):
        second = iter_log_entries(SAMPLE)[1]
        assert second["stage"] == "ITERATING"
        assert second["dod_verdict"] == "PENDING"
        assert second["dod_checkboxes"] == ["open", "open", "open"]
        # No EXITED yet — still in flight.
        assert second["exited"] == ""
        assert second["duration"] == ""

    def test_no_log_section_returns_empty(self):
        assert iter_log_entries("* PLANNING t :agent:\n") == []

    def test_empty_log_section_returns_empty(self):
        body = "* PLANNING t :agent:\n** Log\n"
        assert iter_log_entries(body) == []


class TestLatestLogEntry:
    def test_returns_last_entry_in_document_order(self):
        entry = latest_log_entry(SAMPLE)
        assert entry is not None
        assert entry["stage"] == "ITERATING"

    def test_none_when_no_log(self):
        assert latest_log_entry("* PLANNING t :agent:\n") is None


# ---------------------------------------------------------------------------
# set_dod_verdict
# ---------------------------------------------------------------------------


class TestSetDodVerdict:
    def test_pass_with_open_boxes_raises(self):
        with pytest.raises(DodConsistencyError, match="PASS"):
            set_dod_verdict(SAMPLE, new_verdict="PASS", when="2026-05-20 Wed 12:00")

    def test_pass_when_all_ticked_flips_heading_and_logbook(self):
        ticked = SAMPLE.replace("- [ ] A.", "- [X] A.") \
                       .replace("- [ ] B.", "- [X] B.") \
                       .replace("- [ ] C.", "- [-] C.")
        flipped = set_dod_verdict(
            ticked, new_verdict="PASS", when="2026-05-20 Wed 12:00"
        )
        assert "**** [3/3] PASS DoD" in flipped
        assert "CLOSED: [2026-05-20 Wed 12:00]" in flipped
        assert 'State "PASS"' in flipped

    def test_unsatisfiable_when_all_ticked_raises(self):
        ticked = SAMPLE.replace("- [ ] A.", "- [X] A.") \
                       .replace("- [ ] B.", "- [X] B.") \
                       .replace("- [ ] C.", "- [-] C.")
        flipped = set_dod_verdict(
            ticked, new_verdict="PASS", when="2026-05-20 Wed 12:00"
        )
        with pytest.raises(DodConsistencyError, match="UNSATISFIABLE"):
            set_dod_verdict(
                flipped, new_verdict="UNSATISFIABLE", when="2026-05-20 Wed 12:10"
            )

    def test_unsatisfiable_when_one_box_open_succeeds(self):
        flipped = set_dod_verdict(
            SAMPLE, new_verdict="UNSATISFIABLE", when="2026-05-20 Wed 12:00"
        )
        assert "**** [0/3] UNSATISFIABLE DoD" in flipped
        # UNSATISFIABLE doesn't write a CLOSED line.
        assert "CLOSED:" not in flipped.split("ITERATING (via /advance")[1]

    def test_unknown_verdict_raises_value_error(self):
        with pytest.raises(ValueError, match="unknown DoD verdict"):
            set_dod_verdict(SAMPLE, new_verdict="WHATEVER")

    def test_no_log_section_raises_value_error(self):
        with pytest.raises(ValueError, match="no log entries"):
            set_dod_verdict(
                "* PLANNING t :agent:\n", new_verdict="PASS"
            )

    def test_body_replacement(self):
        # `body` replaces the prose after the checkboxes.
        result = set_dod_verdict(
            SAMPLE,
            new_verdict="UNSATISFIABLE",
            when="2026-05-20 Wed 13:00",
            body="Reason: can't ship until X is fixed.",
        )
        assert "Reason: can't ship until X is fixed." in result


# ---------------------------------------------------------------------------
# mark_plan_approved
# ---------------------------------------------------------------------------


class TestMarkPlanApproved:
    def test_ticks_the_approval_bullet_and_updates_cookie(self):
        out = mark_plan_approved(PLANNING_SAMPLE)
        assert "- [X] The user has approved the plan." in out
        assert "**** [1/3] PENDING DoD" in out
        # Other bullets untouched.
        assert "- [ ] The plan is written into the task's org file." in out
        assert "- [ ] A draft PR has been created on GitHub." in out

    def test_already_ticked_is_noop(self):
        once = mark_plan_approved(PLANNING_SAMPLE)
        twice = mark_plan_approved(once)
        assert twice == once

    def test_noop_when_latest_entry_is_not_planning(self):
        # SAMPLE has an ITERATING latest entry; even though a PLANNING
        # entry exists earlier, mark_plan_approved should not touch it.
        assert mark_plan_approved(SAMPLE) == SAMPLE

    def test_noop_when_bullet_text_differs(self):
        customized = PLANNING_SAMPLE.replace(
            "- [ ] The user has approved the plan.",
            "- [ ] User has signed off on the plan.",
        )
        assert mark_plan_approved(customized) == customized

    def test_noop_when_no_log_section(self):
        body = "* PLANNING t :agent:\n** Goal\n   x\n"
        assert mark_plan_approved(body) == body


# ---------------------------------------------------------------------------
# append_log_entry_skeleton
# ---------------------------------------------------------------------------


class TestAppendLogEntrySkeleton:
    def test_appends_new_iterating_entry_and_stamps_prior(self):
        # Build an all-ticked ITERATING + flip it to PASS first so the
        # prior closure is realistic.
        ticked = SAMPLE.replace("- [ ] A.", "- [X] A.") \
                       .replace("- [ ] B.", "- [X] B.") \
                       .replace("- [ ] C.", "- [-] C.")
        flipped = set_dod_verdict(
            ticked, new_verdict="PASS", when="2026-05-20 Wed 12:00"
        )
        appended = append_log_entry_skeleton(
            flipped, stage="MERGING", via="/advance", prev_stage="ITERATING",
            when="2026-05-20 Wed 13:00",
        )
        assert ":EXITED:      [2026-05-20 Wed 13:00]" in appended
        assert ":DURATION:    1h 30m" in appended
        assert (
            "*** [2026-05-20 Wed 13:00] MERGING (via /advance from ITERATING)"
            in appended
        )
        assert "PENDING DoD" in appended

    def test_seeds_one_checkbox_per_stage_dod_bullet(self):
        appended = append_log_entry_skeleton(
            PLANNING_SAMPLE, stage="ITERATING", via="/advance",
            prev_stage="PLANNING", when="2026-05-20 Wed 11:00",
        )
        # ITERATING has 6 DoD bullets.
        assert "**** [0/6] PENDING DoD" in appended
        for bullet in STAGE_DOD["ITERATING"]:
            assert f"- [ ] {bullet}" in appended

    def test_raises_without_log_section(self):
        body = "* PLANNING t :agent:\n** Goal\n   x\n"
        with pytest.raises(ValueError, match="missing the \\*\\* Log section"):
            append_log_entry_skeleton(
                body, stage="ITERATING", via="/advance",
            )

    def test_unknown_stage_gets_placeholder_bullet(self):
        appended = append_log_entry_skeleton(
            PLANNING_SAMPLE, stage="MYSTERYSTAGE", via="/advance",
            prev_stage="PLANNING", when="2026-05-20 Wed 11:00",
        )
        assert "no DoD bullets registered for stage MYSTERYSTAGE" in appended


# ---------------------------------------------------------------------------
# _format_duration / _parse_ts
# ---------------------------------------------------------------------------


class TestFormatDuration:
    @pytest.mark.parametrize(
        "start,end,want",
        [
            ("2026-01-01 Thu 10:00", "2026-01-01 Thu 10:30", "30m"),
            ("2026-01-01 Thu 10:00", "2026-01-01 Thu 11:30", "1h 30m"),
            ("2026-01-01 Thu 10:00", "2026-01-02 Fri 10:00", "24h 0m"),
            ("2026-01-01 Thu 10:00", "2026-01-01 Thu 10:00", "0m"),
        ],
    )
    def test_render(self, start, end, want):
        s = _parse_ts(start)
        e = _parse_ts(end)
        assert s is not None and e is not None
        assert _format_duration(s, e) == want

    def test_negative_delta_clamps_to_zero(self):
        s = _parse_ts("2026-01-01 Thu 12:00")
        e = _parse_ts("2026-01-01 Thu 10:00")
        assert _format_duration(s, e) == "0m"


class TestParseTs:
    def test_round_trip(self):
        ts = _dt.datetime(2026, 5, 20, 11, 30)
        body = ts.strftime("%Y-%m-%d %a %H:%M")
        assert _parse_ts(body) == ts

    def test_invalid_input_returns_none(self):
        assert _parse_ts("nonsense") is None
        assert _parse_ts("") is None
