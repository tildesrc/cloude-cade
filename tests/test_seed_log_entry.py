"""Tests for ``bin/cloude-seed-log-entry``.

CLI-surface tests; the underlying ``append_log_entry_skeleton`` has
its own coverage in ``test_cloude_org.py``. Here we verify: a happy-
path append, the "no ** Log section" tolerance path (warn-and-zero),
file-not-found exits 2, and missing required flags exit 30.
"""

from __future__ import annotations

from pathlib import Path

from conftest import render_task


class TestSeedLogEntry:
    def test_appends_planning_entry(self, run_script, task_file_factory):
        # Seed a task with the ** Log section but no entries yet.
        task = task_file_factory(log_entries="")
        result = run_script(
            "cloude-seed-log-entry", str(task),
            "--stage", "PLANNING", "--via", "/promote",
        )
        assert result.returncode == 0, result.stderr
        body = task.read_text()
        assert "*** [" in body
        assert "PLANNING (via /promote)" in body
        assert "**** [0/3] PENDING DoD" in body

    def test_no_log_section_warns_and_zero(self, run_script, task_file_factory):
        # render_task(log_entries=None) omits the ** Log heading entirely.
        task = task_file_factory(log_entries=None)
        result = run_script(
            "cloude-seed-log-entry", str(task),
            "--stage", "PLANNING", "--via", "/promote",
        )
        # Best-effort: exits 0 but warns on stderr, file untouched.
        assert result.returncode == 0
        assert "no ** Log section" in result.stderr
        assert "** Log" not in task.read_text()

    def test_file_not_found_exits_2(self, run_script, tmp_path: Path):
        result = run_script(
            "cloude-seed-log-entry", str(tmp_path / "no-such.org"),
            "--stage", "PLANNING",
        )
        assert result.returncode == 2
        assert "file not found" in result.stderr

    def test_missing_stage_exits_30(self, run_script, task_file_factory):
        task = task_file_factory()
        result = run_script(
            "cloude-seed-log-entry", str(task),
            # no --stage
        )
        assert result.returncode == 30
