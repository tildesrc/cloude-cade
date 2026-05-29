"""End-to-end tests for ``bin/cloude-on-stop``.

The Stop hook does two distinct jobs (tag hand-back + one-shot DoD
check). Each test sets up the precondition (task state + marker
presence) and asserts the observable result: the printed JSON block
on a DoD violation, the on-disk tag flip on a quiet turn, or silence.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


from cloude_org import dod_marker_path, parse_heading


def _stop_input(**overrides) -> str:
    """Build a Stop-hook JSON payload. The hook only reads a couple of
    keys (``stop_hook_active``, ``cwd``, ``transcript_path``); the rest
    are tolerated as extras."""
    payload = {
        "session_id": "test",
        "transcript_path": None,
        "cwd": None,
        "stop_hook_active": False,
    }
    payload.update(overrides)
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# Transcript-fixture helpers
#
# Real Claude Code transcripts are JSONL with assorted entry shapes.
# The Stop hook only cares about three of them, mirrored here as
# minimal dicts that the parser accepts:
#
#   * assistant tool_use for Bash with run_in_background=True
#   * queue-operation enqueue with a <task-notification>...<status>
#     completed</status>... payload
#   * assistant tool_use for ScheduleWakeup paired with a user
#     tool_result whose outer entry has toolUseResult.scheduledFor
# ---------------------------------------------------------------------------


def _write_transcript(tmp_path: Path, *entries: dict) -> Path:
    """Write JSONL `entries` into a fresh transcript file under tmp_path."""
    path = tmp_path / "transcript.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")
    return path


def _bash_start(tool_use_id: str) -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": "Bash",
                    "input": {"command": "sleep 999", "run_in_background": True},
                }
            ],
        },
    }


def _bash_completion(tool_use_id: str) -> dict:
    return {
        "type": "queue-operation",
        "operation": "enqueue",
        "content": (
            "<task-notification>"
            f"<tool-use-id>{tool_use_id}</tool-use-id>"
            "<status>completed</status>"
            "</task-notification>"
        ),
    }


def _wakeup_start(tool_use_id: str) -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": "ScheduleWakeup",
                    "input": {"delaySeconds": 60, "reason": "test", "prompt": "test"},
                }
            ],
        },
    }


def _wakeup_result(tool_use_id: str, scheduled_for_ms: int) -> dict:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": "Next wakeup scheduled.",
                }
            ],
        },
        "toolUseResult": {
            "scheduledFor": scheduled_for_ms,
            "clampedDelaySeconds": 60,
            "wasClamped": False,
        },
    }


class TestTagHandback:
    def test_planning_agent_flips_to_user_on_quiet_turn(
        self, run_script, task_file_factory
    ):
        task = task_file_factory(todo="PLANNING", tag="agent")
        result = run_script(
            "cloude-on-stop",
            stdin=_stop_input(),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        assert result.returncode == 0, result.stderr
        _, tags = parse_heading(task.read_text())
        assert tags == ["user"]

    def test_iterating_agent_flips_to_user(
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
            "**** [0/1] PENDING DoD\n"
            "     - [ ] A.\n"
        )
        task = task_file_factory(
            todo="ITERATING", tag="agent", log_entries=log
        )
        run_script(
            "cloude-on-stop",
            stdin=_stop_input(),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        _, tags = parse_heading(task.read_text())
        assert tags == ["user"]

    def test_blocked_tag_is_left_alone(
        self, run_script, task_file_factory
    ):
        task = task_file_factory(todo="PLANNING", tag="blocked")
        run_script(
            "cloude-on-stop",
            stdin=_stop_input(),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        _, tags = parse_heading(task.read_text())
        assert tags == ["blocked"]

    def test_terminal_state_is_full_noop(
        self, run_script, task_file_factory
    ):
        task = task_file_factory(todo="COMPLETE", tag="user")
        result = run_script(
            "cloude-on-stop",
            stdin=_stop_input(),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        assert result.returncode == 0
        # No tag mutation, no output.
        _, tags = parse_heading(task.read_text())
        assert tags == ["user"]
        assert result.stdout == ""

    def test_missing_task_env_is_silent(self, run_script):
        result = run_script(
            "cloude-on-stop",
            stdin=_stop_input(),
            env={"CLOUDE_TASK_FILE": ""},
        )
        assert result.returncode == 0
        assert result.stdout == ""


class TestDodCheck:
    def _arm_marker(self, task):
        dod_marker_path(task).touch()

    def test_pending_verdict_with_marker_blocks_once(
        self, run_script, task_file_factory
    ):
        task = task_file_factory(todo="PLANNING", tag="agent")
        self._arm_marker(task)
        result = run_script(
            "cloude-on-stop",
            stdin=_stop_input(),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        assert result.returncode == 0
        decision = json.loads(result.stdout)
        assert decision["decision"] == "block"
        assert "PENDING" in decision["reason"]
        # Marker should be consumed (one-shot guarantee).
        assert not dod_marker_path(task).exists()

    def test_pass_verdict_passes_silently(
        self, run_script, task_file_factory
    ):
        # All-ticked PASS DoD.
        log = (
            "*** [2026-01-01 Mon 10:00] PLANNING (via /promote)\n"
            "    :PROPERTIES:\n"
            "    :STAGE:       PLANNING\n"
            "    :ENTERED:     [2026-01-01 Mon 10:00]\n"
            "    :ENTERED_VIA: /promote\n"
            "    :END:\n"
            "**** Request\n"
            "**** Work\n"
            "**** [3/3] PASS DoD\n"
            "     - [X] One.\n"
            "     - [X] Two.\n"
            "     - [-] Three.\n"
        )
        task = task_file_factory(todo="PLANNING", tag="agent", log_entries=log)
        self._arm_marker(task)
        result = run_script(
            "cloude-on-stop",
            stdin=_stop_input(),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        assert result.returncode == 0
        assert result.stdout == ""
        # Tag gets flipped on the quiet path.
        _, tags = parse_heading(task.read_text())
        assert tags == ["user"]

    def test_unsatisfiable_with_open_box_passes_silently(
        self, run_script, task_file_factory
    ):
        log = (
            "*** [2026-01-01 Mon 10:00] PLANNING (via /promote)\n"
            "    :PROPERTIES:\n"
            "    :STAGE:       PLANNING\n"
            "    :ENTERED:     [2026-01-01 Mon 10:00]\n"
            "    :ENTERED_VIA: /promote\n"
            "    :END:\n"
            "**** Request\n"
            "**** Work\n"
            "**** [1/2] UNSATISFIABLE DoD\n"
            "     - [X] Done.\n"
            "     - [ ] Cannot be done.\n"
        )
        task = task_file_factory(todo="PLANNING", tag="agent", log_entries=log)
        self._arm_marker(task)
        result = run_script(
            "cloude-on-stop",
            stdin=_stop_input(),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_no_marker_no_dod_check(
        self, run_script, task_file_factory
    ):
        # Default fixture has a PENDING DoD with three open boxes —
        # would block if the marker were armed.
        task = task_file_factory(todo="PLANNING", tag="agent")
        assert not dod_marker_path(task).exists()
        result = run_script(
            "cloude-on-stop",
            stdin=_stop_input(),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        assert result.returncode == 0
        # No JSON block — silent except the tag flip.
        assert result.stdout == ""

    def test_stop_hook_active_skips_dod_check(
        self, run_script, task_file_factory
    ):
        task = task_file_factory(todo="PLANNING", tag="agent")
        self._arm_marker(task)
        result = run_script(
            "cloude-on-stop",
            stdin=_stop_input(stop_hook_active=True),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        assert result.returncode == 0
        assert result.stdout == ""
        # The marker was still consumed (one-shot, regardless).
        assert not dod_marker_path(task).exists()

    def test_pass_with_open_box_blocks_with_mismatch_reason(
        self, run_script, task_file_factory
    ):
        log = (
            "*** [2026-01-01 Mon 10:00] PLANNING (via /promote)\n"
            "    :PROPERTIES:\n"
            "    :STAGE:       PLANNING\n"
            "    :ENTERED:     [2026-01-01 Mon 10:00]\n"
            "    :ENTERED_VIA: /promote\n"
            "    :END:\n"
            "**** Request\n"
            "**** Work\n"
            "**** [1/2] PASS DoD\n"
            "     - [X] Done.\n"
            "     - [ ] Still open.\n"
        )
        task = task_file_factory(todo="PLANNING", tag="agent", log_entries=log)
        self._arm_marker(task)
        result = run_script(
            "cloude-on-stop",
            stdin=_stop_input(),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        decision = json.loads(result.stdout)
        assert decision["decision"] == "block"
        assert "PASS" in decision["reason"]


class TestSchemaErrors:
    def test_missing_log_section_blocks_with_migration_reason(
        self, run_script, task_file_factory
    ):
        task = task_file_factory(todo="PLANNING", tag="agent", log_entries=None)
        dod_marker_path(task).touch()
        result = run_script(
            "cloude-on-stop",
            stdin=_stop_input(),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        decision = json.loads(result.stdout)
        assert decision["decision"] == "block"
        assert "** Log" in decision["reason"]

    def test_stage_mismatch_blocks(
        self, run_script, task_file_factory
    ):
        # Level-1 says ITERATING but latest log entry's :STAGE: says PLANNING.
        task = task_file_factory(todo="ITERATING", tag="agent")
        dod_marker_path(task).touch()
        result = run_script(
            "cloude-on-stop",
            stdin=_stop_input(),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        decision = json.loads(result.stdout)
        assert decision["decision"] == "block"
        assert "mismatch" in decision["reason"].lower()


class TestBackgroundCarveOut:
    def test_babysit_state_file_keeps_hook_silent(
        self, run_script, task_file_factory, tmp_path
    ):
        task = task_file_factory(todo="PLANNING", tag="agent")
        dod_marker_path(task).touch()
        # Drop a babysit-ci sentinel in the cwd we pass to the hook.
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / ".cloude-babysit-state.json").write_text("{}")
        result = run_script(
            "cloude-on-stop",
            stdin=_stop_input(cwd=str(worktree)),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        assert result.returncode == 0
        # Silent: no tag flip, no DoD block, marker preserved.
        _, tags = parse_heading(task.read_text())
        assert tags == ["agent"]
        assert result.stdout == ""
        assert dod_marker_path(task).exists()
        # Clean up the marker we armed.
        dod_marker_path(task).unlink()

    def test_in_flight_background_bash_keeps_hook_silent(
        self, run_script, task_file_factory, tmp_path
    ):
        task = task_file_factory(todo="PLANNING", tag="agent")
        transcript = _write_transcript(
            tmp_path, _bash_start("toolu_bg_1")
        )
        result = run_script(
            "cloude-on-stop",
            stdin=_stop_input(transcript_path=str(transcript)),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        assert result.returncode == 0
        _, tags = parse_heading(task.read_text())
        assert tags == ["agent"]
        assert result.stdout == ""

    def test_completed_background_bash_lets_hook_flip(
        self, run_script, task_file_factory, tmp_path
    ):
        task = task_file_factory(todo="PLANNING", tag="agent")
        transcript = _write_transcript(
            tmp_path,
            _bash_start("toolu_bg_2"),
            _bash_completion("toolu_bg_2"),
        )
        result = run_script(
            "cloude-on-stop",
            stdin=_stop_input(transcript_path=str(transcript)),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        assert result.returncode == 0
        _, tags = parse_heading(task.read_text())
        assert tags == ["user"]

    def test_pending_schedule_wakeup_keeps_hook_silent(
        self, run_script, task_file_factory, tmp_path
    ):
        task = task_file_factory(todo="PLANNING", tag="agent")
        dod_marker_path(task).touch()
        # `scheduledFor` an hour in the future, in unix-ms.
        future_ms = (int(time.time()) + 3600) * 1000
        transcript = _write_transcript(
            tmp_path,
            _wakeup_start("toolu_w_1"),
            _wakeup_result("toolu_w_1", future_ms),
        )
        result = run_script(
            "cloude-on-stop",
            stdin=_stop_input(transcript_path=str(transcript)),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        assert result.returncode == 0
        _, tags = parse_heading(task.read_text())
        assert tags == ["agent"]
        assert result.stdout == ""
        assert dod_marker_path(task).exists()
        dod_marker_path(task).unlink()

    def test_fired_schedule_wakeup_lets_hook_flip(
        self, run_script, task_file_factory, tmp_path
    ):
        task = task_file_factory(todo="PLANNING", tag="agent")
        past_ms = (int(time.time()) - 3600) * 1000
        transcript = _write_transcript(
            tmp_path,
            _wakeup_start("toolu_w_2"),
            _wakeup_result("toolu_w_2", past_ms),
        )
        result = run_script(
            "cloude-on-stop",
            stdin=_stop_input(transcript_path=str(transcript)),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        assert result.returncode == 0
        _, tags = parse_heading(task.read_text())
        assert tags == ["user"]

    def test_latest_wakeup_supersedes_earlier_one(
        self, run_script, task_file_factory, tmp_path
    ):
        """An earlier wakeup scheduled far in the future is canceled by a
        later call whose scheduledFor is already in the past. The hook
        should look at the *latest* call, not the maximum scheduledFor.
        """
        task = task_file_factory(todo="PLANNING", tag="agent")
        future_ms = (int(time.time()) + 3600) * 1000
        past_ms = (int(time.time()) - 60) * 1000
        transcript = _write_transcript(
            tmp_path,
            _wakeup_start("toolu_w_3a"),
            _wakeup_result("toolu_w_3a", future_ms),
            _wakeup_start("toolu_w_3b"),
            _wakeup_result("toolu_w_3b", past_ms),
        )
        result = run_script(
            "cloude-on-stop",
            stdin=_stop_input(transcript_path=str(transcript)),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        assert result.returncode == 0
        _, tags = parse_heading(task.read_text())
        assert tags == ["user"]

    def test_no_schedule_wakeup_in_transcript_is_no_op(
        self, run_script, task_file_factory, tmp_path
    ):
        """A transcript that has no ScheduleWakeup entries at all should
        not change today's behavior — the hook flips :agent: -> :user:.
        """
        task = task_file_factory(todo="PLANNING", tag="agent")
        transcript = _write_transcript(tmp_path)  # empty file
        result = run_script(
            "cloude-on-stop",
            stdin=_stop_input(transcript_path=str(transcript)),
            env={"CLOUDE_TASK_FILE": str(task)},
        )
        assert result.returncode == 0
        _, tags = parse_heading(task.read_text())
        assert tags == ["user"]
