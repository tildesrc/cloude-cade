"""Unit tests for the cloude_stages workflow model.

This is the single-source-of-truth module the rest of the workflow
derives from (keyword list, in-flight / terminal / auto-handback
subsets, dashboard ordering, per-stage DoD bullets, default tags,
forward-transition map with the REVIEW-skip rule, /promote starting
stage, canonical `#+TODO:` line). These tests pin the model's
externally-observable shape so a downstream consumer that asks for
"the next stage after ITERATING" or "the per-stage default tag for
REVIEW" can rely on a stable answer.

`CLAUDE.md`'s Stage details are human-facing reference prose;
machine consumers (`/advance` via `bin/cloude-stages dod`, the
skeleton appender, the stop hook) all read DoD bullets from this
module directly, so drift in CLAUDE.md is a documentation lag,
not a correctness bug.
"""

from __future__ import annotations

import pytest

from cloude_stages import (
    BALL_TAGS,
    BY_NAME,
    PLAN_APPROVED_BULLET,
    WORKFLOW,
    Stage,
    auto_handback,
    dashboard_order_map,
    default_tag,
    dod_for,
    in_flight,
    keyword_list,
    next_stage,
    starting_stage,
    terminal,
    todo_directive,
    transition_via,
)


# ---------------------------------------------------------------------------
# Top-level identity
# ---------------------------------------------------------------------------


class TestKeywordList:
    def test_workflow_order_is_canonical(self):
        # Lock the ordering — every consumer (cloude-dash sort,
        # cloude-task-set-state transition table, /advance's next-state
        # lookup) depends on this exact sequence.
        assert keyword_list() == (
            "PLANNING", "ITERATING", "REVIEW", "MERGING", "COMPLETE", "DROPPED",
        )

    def test_by_name_covers_every_stage(self):
        assert set(BY_NAME) == set(keyword_list())
        assert all(isinstance(s, Stage) for s in BY_NAME.values())

    def test_workflow_tuple_and_by_name_agree(self):
        for stage in WORKFLOW:
            assert BY_NAME[stage.name] is stage


class TestPartitions:
    def test_in_flight_is_non_terminal_in_order(self):
        assert in_flight() == ("PLANNING", "ITERATING", "REVIEW", "MERGING")

    def test_terminal_is_complete_dropped(self):
        assert terminal() == ("COMPLETE", "DROPPED")

    def test_in_flight_and_terminal_partition_keyword_list(self):
        assert set(in_flight()) | set(terminal()) == set(keyword_list())
        assert set(in_flight()) & set(terminal()) == set()

    def test_auto_handback_is_planning_iterating(self):
        # REVIEW defaults to :blocked: (no agent-held ball to flip);
        # MERGING is agent-driven and owned by /babysit-merge.
        assert auto_handback() == ("PLANNING", "ITERATING")


class TestDashboardOrder:
    def test_in_flight_only_with_canonical_priority(self):
        # cloude-dash and cloude-list-active both sort by this map.
        # Lower priority sorts first: MERGING is the most urgent.
        assert dashboard_order_map() == {
            "MERGING": 0,
            "REVIEW": 1,
            "ITERATING": 2,
            "PLANNING": 3,
        }

    def test_terminals_excluded(self):
        # COMPLETE / DROPPED don't appear in the active-task list, so
        # they don't need an ordering key.
        assert "COMPLETE" not in dashboard_order_map()
        assert "DROPPED" not in dashboard_order_map()


# ---------------------------------------------------------------------------
# Per-stage attributes
# ---------------------------------------------------------------------------


class TestDefaultTag:
    @pytest.mark.parametrize(
        "stage,expected",
        [
            ("PLANNING",  "agent"),
            ("ITERATING", "agent"),
            ("REVIEW",    "blocked"),
            ("MERGING",   "agent"),
            ("COMPLETE",  "user"),
            ("DROPPED",   "user"),
        ],
    )
    def test_default_tag_per_stage(self, stage, expected):
        assert default_tag(stage) == expected

    def test_unknown_stage_raises(self):
        with pytest.raises(KeyError):
            default_tag("NOPE")


class TestDodBullets:
    def test_every_stage_has_at_least_one_bullet(self):
        for stage in keyword_list():
            assert dod_for(stage), f"{stage} has no DoD bullets"

    def test_planning_has_three_bullets(self):
        # The skeleton-appender pre-seeds one checkbox per bullet; a
        # PLANNING task starts at `[0/3] PENDING DoD`. Pin the count
        # so the conftest fixture stays in sync.
        assert len(dod_for("PLANNING")) == 3

    def test_iterating_has_six_bullets(self):
        assert len(dod_for("ITERATING")) == 6

    def test_plan_approved_bullet_is_second_planning_bullet(self):
        # cloude_org.mark_plan_approved matches against this exact
        # string; the auto-tick on /advance from PLANNING depends on
        # the bullet text staying identical.
        assert PLAN_APPROVED_BULLET == dod_for("PLANNING")[1]
        assert PLAN_APPROVED_BULLET == "The user has approved the plan."


class TestBallTags:
    def test_priority_order(self):
        # When several ball tags coexist on a heading (misconfigured),
        # the first one in BALL_TAGS wins.
        assert BALL_TAGS == ("agent", "user", "blocked")


# ---------------------------------------------------------------------------
# Transition map
# ---------------------------------------------------------------------------


class TestNextStage:
    def test_planning_to_iterating(self):
        assert next_stage("PLANNING") == "ITERATING"

    def test_iterating_to_review(self):
        assert next_stage("ITERATING") == "REVIEW"

    def test_iterating_to_merging_when_skip_review(self):
        # The :SKIP_REVIEW: t carve-out — repos that opt out of peer
        # review jump straight to MERGING.
        assert next_stage("ITERATING", skip_review=True) == "MERGING"

    def test_review_to_merging(self):
        assert next_stage("REVIEW") == "MERGING"

    def test_merging_to_complete(self):
        assert next_stage("MERGING") == "COMPLETE"

    def test_terminal_stages_have_no_next(self):
        assert next_stage("COMPLETE") is None
        assert next_stage("DROPPED") is None

    def test_skip_review_only_affects_iterating(self):
        # The flag is a no-op on every stage other than ITERATING.
        for stage in ("PLANNING", "REVIEW", "MERGING"):
            assert next_stage(stage, skip_review=True) == next_stage(stage)

    def test_unknown_stage_raises(self):
        with pytest.raises(KeyError):
            next_stage("NOPE")


class TestTransitionVia:
    def test_forward_is_advance(self):
        assert transition_via("PLANNING", "ITERATING") == "/advance"
        assert transition_via("ITERATING", "REVIEW") == "/advance"
        assert transition_via("REVIEW", "MERGING") == "/advance"
        assert transition_via("MERGING", "COMPLETE") == "/advance"
        # Skip-review path — forward by index.
        assert transition_via("ITERATING", "MERGING") == "/advance"

    def test_backward_is_iterate(self):
        # The MERGING → ITERATING kickback path (/babysit-merge,
        # /iterate from REVIEW).
        assert transition_via("MERGING", "ITERATING") == "/iterate"
        assert transition_via("REVIEW", "ITERATING") == "/iterate"

    def test_drop_is_drop(self):
        # Any move into DROPPED is a /drop regardless of source.
        for src in keyword_list():
            assert transition_via(src, "DROPPED") == "/drop"


# ---------------------------------------------------------------------------
# Promote starting stage
# ---------------------------------------------------------------------------


class TestStartingStage:
    def test_standard_is_planning(self):
        assert starting_stage("standard") == "PLANNING"

    def test_adopt_is_iterating(self):
        assert starting_stage("adopt") == "ITERATING"

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError):
            starting_stage("mystery")


# ---------------------------------------------------------------------------
# Canonical #+TODO: directive
# ---------------------------------------------------------------------------


class TestTodoDirective:
    def test_matches_template_format(self):
        # The drift test asserts tasks/TEMPLATE.org matches this
        # exactly; this test pins the format itself.
        assert todo_directive() == (
            "#+TODO: PLANNING(p!) ITERATING(i!) REVIEW(r!) MERGING(m!) "
            "| COMPLETE(c!) DROPPED(x@)"
        )

    def test_in_flight_keywords_come_before_separator(self):
        line = todo_directive()
        before, _, after = line.partition("|")
        for stage in in_flight():
            assert stage in before
        for stage in terminal():
            assert stage in after
