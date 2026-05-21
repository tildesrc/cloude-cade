"""End-to-end tests for ``bin/cloude-on-user-prompt``.

UserPromptSubmit hook flips ``:user:`` -> ``:agent:`` on any in-flight
stage. No-op for terminal stages, missing task file, ``:blocked:``,
or already-``:agent:``.
"""

from __future__ import annotations

import json

import pytest

from cloude_org import parse_heading


HOOK_INPUT = json.dumps({"prompt": "anything"})


@pytest.mark.parametrize("stage", ["PLANNING", "ITERATING", "REVIEW", "MERGING"])
def test_user_flips_to_agent_for_inflight_stages(
    stage, run_script, task_file_factory
):
    log_default = "default" if stage == "PLANNING" else (
        f"*** [2026-01-01 Mon 10:00] {stage} (via /advance from PLANNING)\n"
        "    :PROPERTIES:\n"
        f"    :STAGE:       {stage}\n"
        "    :ENTERED:     [2026-01-01 Mon 10:00]\n"
        "    :ENTERED_VIA: /advance from PLANNING\n"
        "    :END:\n"
        "**** Request\n"
        "**** Work\n"
        "**** [0/1] PENDING DoD\n"
        "     - [ ] A.\n"
    )
    task = task_file_factory(todo=stage, tag="user", log_entries=log_default)
    result = run_script(
        "cloude-on-user-prompt",
        stdin=HOOK_INPUT,
        env={"CLOUDE_TASK_FILE": str(task)},
    )
    assert result.returncode == 0, result.stderr
    _, tags = parse_heading(task.read_text())
    assert tags == ["agent"]
    assert "Task picked up" in result.stdout


@pytest.mark.parametrize("stage", ["COMPLETE", "DROPPED"])
def test_terminal_stages_left_alone(stage, run_script, task_file_factory):
    task = task_file_factory(todo=stage, tag="user")
    run_script(
        "cloude-on-user-prompt",
        stdin=HOOK_INPUT,
        env={"CLOUDE_TASK_FILE": str(task)},
    )
    _, tags = parse_heading(task.read_text())
    assert tags == ["user"]


def test_blocked_tag_is_not_silently_cleared(run_script, task_file_factory):
    task = task_file_factory(todo="REVIEW", tag="blocked")
    run_script(
        "cloude-on-user-prompt",
        stdin=HOOK_INPUT,
        env={"CLOUDE_TASK_FILE": str(task)},
    )
    _, tags = parse_heading(task.read_text())
    assert tags == ["blocked"]


def test_already_agent_is_noop(run_script, task_file_factory):
    task = task_file_factory(todo="PLANNING", tag="agent")
    result = run_script(
        "cloude-on-user-prompt",
        stdin=HOOK_INPUT,
        env={"CLOUDE_TASK_FILE": str(task)},
    )
    assert result.returncode == 0
    # No announcement message — the hook only prints when it flips.
    assert "Task picked up" not in result.stdout


def test_missing_task_env_is_silent(run_script):
    result = run_script(
        "cloude-on-user-prompt",
        stdin=HOOK_INPUT,
        env={"CLOUDE_TASK_FILE": ""},
    )
    assert result.returncode == 0
    assert result.stdout == ""
