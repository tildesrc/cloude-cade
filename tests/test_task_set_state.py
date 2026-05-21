"""End-to-end tests for ``bin/cloude-task-set-state``.

Drives the script as a subprocess against fixture task files. The
in-process unit tests in ``test_cloude_org.py`` already cover the
core schema helpers; this file is here for the CLI surface and the
side effects (heading rewrite, log-entry append, DoD marker drop).
"""

from __future__ import annotations

from pathlib import Path

from cloude_org import dod_marker_path, iter_log_entries, parse_heading


class TestPlanningToIterating:
    def test_flips_heading_and_appends_log_entry(
        self, run_script, task_file_factory
    ):
        task = task_file_factory()
        result = run_script(
            "cloude-task-set-state", str(task), "--todo", "ITERATING"
        )
        assert result.returncode == 0, result.stderr

        content = task.read_text()
        todo, tags = parse_heading(content)
        assert todo == "ITERATING"
        # No --tag passed, so the prior tag is kept (here: 'agent').
        assert "agent" in tags

        entries = iter_log_entries(content)
        # Promote-seeded PLANNING + the just-appended ITERATING skeleton.
        assert [e["stage"] for e in entries] == ["PLANNING", "ITERATING"]
        # The new entry's via text records the source stage.
        assert entries[-1]["entered_via"] == "/advance from PLANNING"
        # The closing PLANNING entry got stamped.
        assert entries[0]["exited"] != ""
        assert entries[0]["duration"] != ""

    def test_auto_ticks_plan_approved_bullet(
        self, run_script, task_file_factory
    ):
        task = task_file_factory()
        run_script("cloude-task-set-state", str(task), "--todo", "ITERATING")
        content = task.read_text()
        assert "- [X] The user has approved the plan." in content

    def test_drops_dod_marker(self, run_script, task_file_factory):
        task = task_file_factory()
        marker = dod_marker_path(task)
        assert not marker.exists()
        run_script("cloude-task-set-state", str(task), "--todo", "ITERATING")
        assert marker.exists()
        # The cleanup hook in task_file_factory will remove the marker
        # after the test; ensure that path is what we expected to drop.

    def test_drop_to_dropped_does_not_tick_plan_approval(
        self, run_script, task_file_factory
    ):
        # /drop is abandonment, not approval — the auto-tick must not
        # fire for the DROPPED transition.
        task = task_file_factory()
        run_script("cloude-task-set-state", str(task), "--todo", "DROPPED")
        content = task.read_text()
        assert "- [ ] The user has approved the plan." in content
        assert "- [X] The user has approved the plan." not in content


class TestTagOnly:
    def test_tag_update_does_not_change_todo(
        self, run_script, task_file_factory
    ):
        task = task_file_factory(tag="agent")
        result = run_script(
            "cloude-task-set-state", str(task), "--tag", "user"
        )
        assert result.returncode == 0, result.stderr
        todo, tags = parse_heading(task.read_text())
        assert todo == "PLANNING"
        assert tags == ["user"]

    def test_tag_only_does_not_drop_dod_marker(
        self, run_script, task_file_factory
    ):
        task = task_file_factory(tag="agent")
        marker = dod_marker_path(task)
        run_script("cloude-task-set-state", str(task), "--tag", "user")
        assert not marker.exists()

    def test_tag_only_does_not_append_log_entry(
        self, run_script, task_file_factory
    ):
        task = task_file_factory(tag="agent")
        before = iter_log_entries(task.read_text())
        run_script("cloude-task-set-state", str(task), "--tag", "user")
        after = iter_log_entries(task.read_text())
        assert len(after) == len(before)


class TestDodStateFlip:
    def _all_ticked_iterating_task(self, task_file_factory) -> Path:
        log = (
            "*** [2026-01-01 Mon 10:00] ITERATING (via /advance from PLANNING)\n"
            "    :PROPERTIES:\n"
            "    :STAGE:       ITERATING\n"
            "    :ENTERED:     [2026-01-01 Mon 10:00]\n"
            "    :ENTERED_VIA: /advance from PLANNING\n"
            "    :END:\n"
            "**** Request\n"
            "**** Work\n"
            "**** [3/3] PENDING DoD\n"
            "     - [X] A.\n"
            "     - [X] B.\n"
            "     - [-] C.\n"
        )
        return task_file_factory(
            todo="ITERATING", tag="agent", log_entries=log
        )

    def test_pass_flip_on_all_ticked_succeeds(
        self, run_script, task_file_factory
    ):
        task = self._all_ticked_iterating_task(task_file_factory)
        result = run_script(
            "cloude-task-set-state", str(task), "--dod-state", "pass"
        )
        assert result.returncode == 0, result.stderr
        # shlex.quote leaves shell-safe strings unquoted.
        assert "DOD_VERDICT=PASS" in result.stdout
        content = task.read_text()
        assert "**** [3/3] PASS DoD" in content
        assert "CLOSED:" in content

    def test_pass_flip_on_open_box_exits_31(
        self, run_script, task_file_factory
    ):
        # Default fixture has an open PENDING DoD with 3 open boxes.
        task = task_file_factory()
        result = run_script(
            "cloude-task-set-state", str(task), "--dod-state", "pass"
        )
        assert result.returncode == 31
        assert "PASS" in result.stderr

    def test_dod_state_case_insensitive(
        self, run_script, task_file_factory
    ):
        task = self._all_ticked_iterating_task(task_file_factory)
        result = run_script(
            "cloude-task-set-state", str(task), "--dod-state", "PASS"
        )
        assert result.returncode == 0, result.stderr

    def test_unknown_dod_state_rejected(
        self, run_script, task_file_factory
    ):
        task = task_file_factory()
        result = run_script(
            "cloude-task-set-state", str(task), "--dod-state", "BOGUS"
        )
        assert result.returncode == 30
        assert "unknown DoD verdict" in result.stderr

    def test_reason_replaces_dod_prose(
        self, run_script, task_file_factory
    ):
        # UNSATISFIABLE flip with --reason: open boxes are required, so
        # start from the default fixture (3 open boxes).
        task = task_file_factory()
        result = run_script(
            "cloude-task-set-state", str(task),
            "--dod-state", "unsatisfiable",
            "--reason", "PR write access not granted.",
        )
        assert result.returncode == 0, result.stderr
        assert "PR write access not granted." in task.read_text()


class TestUsageErrors:
    def test_missing_file_exits_2(self, run_script, tmp_path):
        result = run_script(
            "cloude-task-set-state", str(tmp_path / "nope.org"),
            "--tag", "user",
        )
        assert result.returncode == 2

    def test_combining_dod_state_with_todo_rejected(
        self, run_script, task_file_factory
    ):
        task = task_file_factory()
        result = run_script(
            "cloude-task-set-state", str(task),
            "--dod-state", "pass", "--todo", "ITERATING",
        )
        assert result.returncode == 30
        assert "cannot be combined" in result.stderr

    def test_reason_without_dod_state_rejected(
        self, run_script, task_file_factory
    ):
        task = task_file_factory()
        result = run_script(
            "cloude-task-set-state", str(task), "--reason", "x",
        )
        assert result.returncode == 30
        assert "--reason requires --dod-state" in result.stderr

    def test_via_without_todo_rejected(
        self, run_script, task_file_factory
    ):
        task = task_file_factory()
        result = run_script(
            "cloude-task-set-state", str(task), "--via", "/advance",
        )
        assert result.returncode == 30
        assert "--via requires --todo" in result.stderr

    def test_unknown_todo_rejected(
        self, run_script, task_file_factory
    ):
        task = task_file_factory()
        result = run_script(
            "cloude-task-set-state", str(task), "--todo", "BOGUS",
        )
        assert result.returncode == 30
        assert "unknown TODO keyword" in result.stderr

    def test_invalid_tag_chars_rejected(
        self, run_script, task_file_factory
    ):
        task = task_file_factory()
        result = run_script(
            "cloude-task-set-state", str(task), "--tag", "bad-tag",
        )
        assert result.returncode == 30
        assert "invalid tag" in result.stderr

    def test_no_action_flags_rejected(
        self, run_script, task_file_factory
    ):
        task = task_file_factory()
        result = run_script("cloude-task-set-state", str(task))
        assert result.returncode == 30
        assert "nothing to do" in result.stderr


class TestRedundantTodoTransition:
    def test_todo_iterating_on_iterating_is_noop_for_log_entries(
        self, run_script, task_file_factory
    ):
        # Start in ITERATING with one prior log entry.
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
        before = iter_log_entries(task.read_text())
        # Re-iterate: same keyword. Should not append a duplicate entry.
        result = run_script(
            "cloude-task-set-state", str(task), "--todo", "ITERATING",
            "--tag", "agent",
        )
        assert result.returncode == 0, result.stderr
        after = iter_log_entries(task.read_text())
        assert len(after) == len(before)
