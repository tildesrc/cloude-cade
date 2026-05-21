"""End-to-end tests for ``bin/cloude-on-user-question``.

``pre``  fires PreToolUse:AskUserQuestion — flips :agent: -> :user:.
``post`` fires PostToolUse:AskUserQuestion — flips :user: -> :agent:.
The hook never blocks the tool call; it always exits 0.
"""

from __future__ import annotations

import json

from cloude_org import parse_heading


HOOK_INPUT = json.dumps({"foo": "bar"})


class TestPre:
    def test_agent_flips_to_user(self, run_script, task_file_factory):
        task = task_file_factory(todo="PLANNING", tag="agent")
        result = run_script(
            "cloude-on-user-question", "pre",
            stdin=HOOK_INPUT,
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        assert result.returncode == 0
        _, tags = parse_heading(task.read_text())
        assert tags == ["user"]
        assert "Question opened" in result.stdout

    def test_user_tag_unchanged(self, run_script, task_file_factory):
        task = task_file_factory(todo="PLANNING", tag="user")
        run_script(
            "cloude-on-user-question", "pre",
            stdin=HOOK_INPUT,
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        _, tags = parse_heading(task.read_text())
        assert tags == ["user"]


class TestPost:
    def test_user_flips_to_agent(self, run_script, task_file_factory):
        task = task_file_factory(todo="PLANNING", tag="user")
        result = run_script(
            "cloude-on-user-question", "post",
            stdin=HOOK_INPUT,
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        assert result.returncode == 0
        _, tags = parse_heading(task.read_text())
        assert tags == ["agent"]
        assert "Question answered" in result.stdout

    def test_blocked_tag_left_alone(self, run_script, task_file_factory):
        task = task_file_factory(todo="REVIEW", tag="blocked")
        run_script(
            "cloude-on-user-question", "post",
            stdin=HOOK_INPUT,
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        _, tags = parse_heading(task.read_text())
        assert tags == ["blocked"]


class TestUsageErrors:
    def test_unknown_phase_warns_but_exits_0(
        self, run_script, task_file_factory
    ):
        task = task_file_factory(todo="PLANNING", tag="agent")
        result = run_script(
            "cloude-on-user-question", "BOGUS",
            stdin=HOOK_INPUT,
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        # Hook contract: never block the tool call.
        assert result.returncode == 0
        assert "expected one of" in result.stderr

    def test_missing_phase_exits_0(self, run_script, task_file_factory):
        task = task_file_factory(todo="PLANNING", tag="agent")
        result = run_script(
            "cloude-on-user-question",
            stdin=HOOK_INPUT,
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        assert result.returncode == 0
