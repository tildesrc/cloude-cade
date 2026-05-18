"""Tests for the workflow hooks, driven through their real entry points.

Each hook is run as a subprocess exactly as Claude Code's hook runner
would invoke it: with `$CLOUDE_TASK_FILE` pointing at a task file and
the hook's JSON payload on stdin. The payload is where the "LLM" is
mocked — e.g. the plan-accepted hook is fed a fake ExitPlanMode plan
instead of a real one.

The hooks resolve the workflow from the repo's `workflows/active`
pointer, so these exercise the default workflow (the live config).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"

DEFAULT_TODO = "PLANNING(p!) ITERATING(i!) REVIEW(r!) MERGING(m!) | COMPLETE(c!) DROPPED(x@)"


def make_task(tmp_path: Path, state: str, tag: str) -> Path:
    """Write a minimal active task .org file and return its path."""
    content = (
        f"#+TITLE: T\n"
        f"#+TODO: {DEFAULT_TODO}\n"
        f"#+STARTUP: overview logdrawer\n"
        f"\n"
        f"* {state} A sample task :{tag}:\n"
        f"  :PROPERTIES:\n"
        f"  :ID:       x\n"
        f"  :END:\n"
        f"\n"
        f"** Acceptance criteria\n"
        f"   - [ ]\n"
        f"\n"
        f"** Notes\n"
        f"   scratch.\n"
    )
    task = tmp_path / "task.org"
    task.write_text(content)
    return task


def run_hook(name: str, task: Path, payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BIN / name)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={**os.environ, "CLOUDE_TASK_FILE": str(task)},
    )


def heading_line(task: Path) -> str:
    for line in task.read_text().splitlines():
        if line.startswith("* "):
            return line
    raise AssertionError("no heading found")


# --- cloude-on-stop ----------------------------------------------------------


def test_on_stop_blocks_an_agent_tagged_in_flight_task(tmp_path):
    task = make_task(tmp_path, "ITERATING", "agent")
    result = run_hook("cloude-on-stop", task, {})
    out = json.loads(result.stdout)
    assert out["decision"] == "block"
    # The DoD bullets are sourced from the workflow definition.
    assert "The plan is implemented in code." in out["reason"]
    assert "Definition of Done" in out["reason"]


def test_on_stop_is_silent_when_tag_is_user(tmp_path):
    task = make_task(tmp_path, "ITERATING", "user")
    result = run_hook("cloude-on-stop", task, {})
    assert result.stdout.strip() == ""


def test_on_stop_respects_stop_hook_active(tmp_path):
    task = make_task(tmp_path, "ITERATING", "agent")
    result = run_hook("cloude-on-stop", task, {"stop_hook_active": True})
    assert result.stdout.strip() == ""


def test_on_stop_is_silent_for_terminal_states(tmp_path):
    task = make_task(tmp_path, "COMPLETE", "agent")
    result = run_hook("cloude-on-stop", task, {})
    assert result.stdout.strip() == ""


def test_on_stop_merging_offers_the_agent_driven_forward(tmp_path):
    task = make_task(tmp_path, "MERGING", "agent")
    out = json.loads(run_hook("cloude-on-stop", task, {}).stdout)
    reason = out["reason"]
    # MERGING's forward driver is 'agent', so the message points at /advance.
    assert "/advance" in reason
    assert "agent-driven forward transition" in reason
    assert "MERGING → COMPLETE" in reason


def test_on_stop_non_merging_says_user_driven(tmp_path):
    task = make_task(tmp_path, "ITERATING", "agent")
    out = json.loads(run_hook("cloude-on-stop", task, {}).stdout)
    assert "Forward transitions out of ITERATING are user-driven" in out["reason"]


# --- cloude-on-user-prompt ---------------------------------------------------


def test_on_user_prompt_flips_user_to_agent(tmp_path):
    task = make_task(tmp_path, "PLANNING", "user")
    result = run_hook("cloude-on-user-prompt", task, {})
    assert ":agent:" in heading_line(task)
    assert "flipped" in result.stdout


def test_on_user_prompt_leaves_blocked_alone(tmp_path):
    task = make_task(tmp_path, "REVIEW", "blocked")
    run_hook("cloude-on-user-prompt", task, {})
    assert ":blocked:" in heading_line(task)


def test_on_user_prompt_ignores_terminal_states(tmp_path):
    task = make_task(tmp_path, "COMPLETE", "user")
    run_hook("cloude-on-user-prompt", task, {})
    assert ":user:" in heading_line(task)


# --- cloude-on-plan-accepted -------------------------------------------------


def test_on_plan_accepted_advances_planning_and_writes_plan(tmp_path):
    task = make_task(tmp_path, "PLANNING", "agent")
    # Mock the LLM: the plan that ExitPlanMode would have produced.
    payload = {"tool_input": {"plan": "# Plan\n\n- step one\n- step two"}}
    result = run_hook("cloude-on-plan-accepted", task, payload)

    text = task.read_text()
    assert heading_line(task).startswith("* ITERATING A sample task :agent:")
    assert "** Plan" in text
    assert "step one" in text
    assert "step two" in text
    assert "PLANNING → ITERATING" in result.stdout


def test_on_plan_accepted_is_noop_outside_planning(tmp_path):
    task = make_task(tmp_path, "ITERATING", "agent")
    before = task.read_text()
    run_hook("cloude-on-plan-accepted", task, {"tool_input": {"plan": "x"}})
    assert task.read_text() == before


def test_on_plan_accepted_is_noop_without_a_task_file(tmp_path):
    missing = tmp_path / "absent.org"
    result = subprocess.run(
        [sys.executable, str(BIN / "cloude-on-plan-accepted")],
        input="{}",
        capture_output=True,
        text=True,
        env={**os.environ, "CLOUDE_TASK_FILE": str(missing)},
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""
