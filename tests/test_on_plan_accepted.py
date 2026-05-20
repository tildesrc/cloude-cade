"""End-to-end tests for ``bin/cloude-on-plan-accepted``.

The ExitPlanMode hook should: (1) insert/replace the ``** Plan``
section, (2) tick the canonical "user has approved" PLANNING DoD
bullet, (3) flip the heading PLANNING -> ITERATING + :agent:.
A no-op when the task isn't in PLANNING.
"""

from __future__ import annotations

import json

from cloude_org import dod_marker_path, parse_heading


def _hook_input(plan_text: str) -> str:
    return json.dumps({"tool_input": {"plan": plan_text}})


class TestHappyPath:
    def test_inserts_plan_section_when_absent(
        self, run_script, task_file_factory
    ):
        sections = "** Goal\n   thing\n\n** Notes\n   stuff\n\n"
        task = task_file_factory(
            todo="PLANNING", tag="user", sections=sections,
        )
        result = run_script(
            "cloude-on-plan-accepted",
            stdin=_hook_input("# Plan body\n- Step 1\n- Step 2\n"),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        assert result.returncode == 0, result.stderr
        content = task.read_text()
        assert "** Plan" in content
        assert "- Step 1" in content
        # Inserted before ** Notes (the closest anchor).
        assert content.index("** Plan") < content.index("** Notes")

    def test_replaces_existing_plan_section(
        self, run_script, task_file_factory
    ):
        sections = "** Plan\n   old plan\n\n** Notes\n   notes\n\n"
        task = task_file_factory(
            todo="PLANNING", tag="user", sections=sections,
        )
        run_script(
            "cloude-on-plan-accepted",
            stdin=_hook_input("brand new plan\n"),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        content = task.read_text()
        assert "brand new plan" in content
        assert "old plan" not in content
        # Notes is still present and after Plan.
        assert content.index("** Plan") < content.index("** Notes")

    def test_ticks_plan_approved_bullet(
        self, run_script, task_file_factory
    ):
        task = task_file_factory(todo="PLANNING", tag="user")
        run_script(
            "cloude-on-plan-accepted",
            stdin=_hook_input("plan"),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        content = task.read_text()
        assert "- [X] The user has approved the plan." in content

    def test_flips_planning_to_iterating(
        self, run_script, task_file_factory
    ):
        task = task_file_factory(todo="PLANNING", tag="user")
        run_script(
            "cloude-on-plan-accepted",
            stdin=_hook_input("plan"),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        todo, tags = parse_heading(task.read_text())
        assert todo == "ITERATING"
        assert tags == ["agent"]

    def test_arms_dod_marker(
        self, run_script, task_file_factory
    ):
        task = task_file_factory(todo="PLANNING", tag="user")
        assert not dod_marker_path(task).exists()
        run_script(
            "cloude-on-plan-accepted",
            stdin=_hook_input("plan"),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        assert dod_marker_path(task).exists()


class TestNoops:
    def test_iterating_task_unchanged(
        self, run_script, task_file_factory
    ):
        log = (
            "*** [2026-01-01 Mon 10:00] ITERATING (via /advance from PLANNING)\n"
            "    :PROPERTIES:\n"
            "    :STAGE:       ITERATING\n"
            "    :ENTERED:     [2026-01-01 Mon 10:00]\n"
            "    :ENTERED_VIA: /advance from PLANNING\n"
            "    :END:\n"
            "**** Request\n"
            "**** Work\n"
            "**** [0/6] PENDING DoD\n"
            "     - [ ] A.\n"
        )
        task = task_file_factory(
            todo="ITERATING", tag="agent", log_entries=log
        )
        before = task.read_text()
        run_script(
            "cloude-on-plan-accepted",
            stdin=_hook_input("plan"),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        # No mutations.
        assert task.read_text() == before
        assert not dod_marker_path(task).exists()

    def test_missing_task_env_is_silent(self, run_script):
        result = run_script(
            "cloude-on-plan-accepted",
            stdin=_hook_input("plan"),
            env={"CLOUDE_TASK_FILE": ""},
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_empty_plan_still_advances_and_ticks(
        self, run_script, task_file_factory
    ):
        # Even when plan text is empty (e.g. user accepted an
        # interactive plan with no body), the hook should still tick
        # approval and flip to ITERATING — that's the user's gesture.
        task = task_file_factory(todo="PLANNING", tag="user")
        run_script(
            "cloude-on-plan-accepted",
            stdin=_hook_input(""),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        content = task.read_text()
        todo, _ = parse_heading(content)
        assert todo == "ITERATING"
        assert "- [X] The user has approved the plan." in content
