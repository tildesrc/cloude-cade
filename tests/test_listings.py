"""Smoke tests for the read-only listing helpers.

Covers ``cloude-list-active``, ``cloude-list-staging``, and
``cloude-task-info``. Each script is exercised against a temp
``tasks/`` tree (the listers honor ``$CLOUDE_ROOT`` to find tasks).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from conftest import render_task


def _build_tasks_tree(tmp_path: Path, fixtures_dir: Path) -> Path:
    """Lay out tasks/{active,staging.org,completed,dropped} under tmp_path."""
    tasks = tmp_path / "tasks"
    (tasks / "active").mkdir(parents=True)
    (tasks / "completed").mkdir()
    (tasks / "dropped").mkdir()
    shutil.copy(fixtures_dir / "staging.org", tasks / "staging.org")
    return tasks


class TestListActive:
    def test_empty_active_dir(self, run_script, tmp_path, fixtures_dir):
        _build_tasks_tree(tmp_path, fixtures_dir)
        result = run_script(
            "cloude-list-active",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_orders_by_stage_priority(
        self, run_script, tmp_path, fixtures_dir
    ):
        tasks = _build_tasks_tree(tmp_path, fixtures_dir)
        (tasks / "active" / "2026-01-01-aaa.org").write_text(
            render_task(todo="PLANNING", title="planning task", tag="user")
        )
        (tasks / "active" / "2026-01-02-bbb.org").write_text(
            render_task(todo="MERGING", title="merging task", tag="agent")
        )
        (tasks / "active" / "2026-01-03-ccc.org").write_text(
            render_task(todo="ITERATING", title="iterating task", tag="agent")
        )
        result = run_script(
            "cloude-list-active",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        # MERGING (0) > ITERATING (2) > PLANNING (3).
        assert "merging task" in lines[0]
        assert "iterating task" in lines[1]
        assert "planning task" in lines[2]
        # Numbered 1..3.
        assert lines[0].startswith("1) ")
        assert lines[2].startswith("3) ")

    def test_terminal_filter_returns_idle_message_when_empty(
        self, run_script, tmp_path, fixtures_dir
    ):
        tasks = _build_tasks_tree(tmp_path, fixtures_dir)
        (tasks / "active" / "2026-01-01-aaa.org").write_text(
            render_task(todo="PLANNING", title="t", tag="user")
        )
        result = run_script(
            "cloude-list-active", "--terminal",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "No tasks awaiting finalize."

    def test_terminal_filter_lists_complete_and_dropped(
        self, run_script, tmp_path, fixtures_dir
    ):
        tasks = _build_tasks_tree(tmp_path, fixtures_dir)
        (tasks / "active" / "2026-01-01-done.org").write_text(
            render_task(todo="COMPLETE", title="done task", tag="user")
        )
        (tasks / "active" / "2026-01-02-gone.org").write_text(
            render_task(todo="DROPPED", title="gone task", tag="user")
        )
        result = run_script(
            "cloude-list-active", "--terminal",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "done task" in result.stdout
        assert "gone task" in result.stdout


class TestListStaging:
    def test_default_listing_shape(
        self, run_script, tmp_path, fixtures_dir
    ):
        _build_tasks_tree(tmp_path, fixtures_dir)
        result = run_script(
            "cloude-list-staging",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0
        out = result.stdout
        assert out.startswith("PROMOTABLE\n")
        # Two promotable projects with three ideas total.
        assert "1) [Example project] First idea" in out
        assert "2) [Example project] Second idea  [ADOPT]" in out
        assert "3) [No-review project] Third idea" in out
        assert "TODO_PROJECTS 1" in out

    def test_select_emits_eval_safe_kv_lines(
        self, run_script, tmp_path, fixtures_dir
    ):
        _build_tasks_tree(tmp_path, fixtures_dir)
        result = run_script(
            "cloude-list-staging", "--select", "2",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0
        out = result.stdout
        assert "REPO=https://github.com/example/example" in out
        assert "MODE=adopt" in out
        assert "PR_URL=https://github.com/example/example/pull/99" in out
        # SKIP_REVIEW from this project is empty.
        assert "SKIP_REVIEW=''" in out
        # SLUG is empty when the idea has no :SLUG: property.
        assert "SLUG=''" in out

    def test_select_emits_slug_when_present(
        self, run_script, tmp_path, fixtures_dir
    ):
        tasks = _build_tasks_tree(tmp_path, fixtures_dir)
        # Add an idea with a :SLUG: property to the existing fixture.
        staging = tasks / "staging.org"
        text = staging.read_text()
        text = text.replace(
            "** Third idea",
            "** Third idea\n"
            "   :PROPERTIES:\n"
            "   :SLUG: third-idea-slug\n"
            "   :END:",
            1,
        )
        staging.write_text(text)
        result = run_script(
            "cloude-list-staging", "--select", "3",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "SLUG=third-idea-slug" in result.stdout

    def test_slugless_lists_only_ideas_missing_slug(
        self, run_script, tmp_path, fixtures_dir
    ):
        tasks = _build_tasks_tree(tmp_path, fixtures_dir)
        # Give the second idea a slug; first and third stay slugless.
        staging = tasks / "staging.org"
        text = staging.read_text().replace(
            "   :ADOPT: https://github.com/example/example/pull/99\n",
            "   :ADOPT: https://github.com/example/example/pull/99\n"
            "   :SLUG: second-idea-slug\n",
            1,
        )
        staging.write_text(text)
        result = run_script(
            "cloude-list-staging", "--slugless",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0
        lines = [ln for ln in result.stdout.splitlines() if ln]
        assert any("First idea" in ln for ln in lines)
        assert any("Third idea" in ln for ln in lines)
        assert not any("Second idea" in ln for ln in lines)
        # Tab-separated <project>\t<heading>.
        for ln in lines:
            assert "\t" in ln

    def test_slugless_empty_when_all_have_slugs(
        self, run_script, tmp_path, fixtures_dir
    ):
        tasks = _build_tasks_tree(tmp_path, fixtures_dir)
        # Replace fixture wholesale with a single idea that already
        # carries :SLUG:.
        (tasks / "staging.org").write_text(
            "#+TITLE: Staging\n"
            "* Example project\n"
            "  :PROPERTIES:\n"
            "  :REPO: https://github.com/example/example\n"
            "  :END:\n"
            "** First idea\n"
            "   :PROPERTIES:\n"
            "   :SLUG: first-idea\n"
            "   :END:\n"
        )
        result = run_script(
            "cloude-list-staging", "--slugless",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0
        assert result.stdout == ""

    def test_slugless_treats_empty_slug_as_slugless(
        self, run_script, tmp_path, fixtures_dir
    ):
        tasks = _build_tasks_tree(tmp_path, fixtures_dir)
        (tasks / "staging.org").write_text(
            "#+TITLE: Staging\n"
            "* Example project\n"
            "  :PROPERTIES:\n"
            "  :REPO: https://github.com/example/example\n"
            "  :END:\n"
            "** Please suggest a slug\n"
            "   :PROPERTIES:\n"
            "   :SLUG:\n"
            "   :END:\n"
        )
        result = run_script(
            "cloude-list-staging", "--slugless",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "Please suggest a slug" in result.stdout

    def test_select_and_slugless_are_mutually_exclusive(
        self, run_script, tmp_path, fixtures_dir
    ):
        _build_tasks_tree(tmp_path, fixtures_dir)
        result = run_script(
            "cloude-list-staging", "--select", "1", "--slugless",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 2
        assert "mutually exclusive" in result.stderr

    def test_select_picks_up_skip_review(
        self, run_script, tmp_path, fixtures_dir
    ):
        _build_tasks_tree(tmp_path, fixtures_dir)
        result = run_script(
            "cloude-list-staging", "--select", "3",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "SKIP_REVIEW=t" in result.stdout
        assert "MODE=standard" in result.stdout

    def test_select_emits_slug_property(
        self, run_script, tmp_path, fixtures_dir
    ):
        """An idea's optional :SLUG: surfaces as a SLUG= line; absent → empty."""
        _build_tasks_tree(tmp_path, fixtures_dir)
        # Third idea has no :SLUG:.
        without = run_script(
            "cloude-list-staging", "--select", "3",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert without.returncode == 0
        assert "SLUG=''" in without.stdout
        # Fourth idea carries :SLUG: hand-picked-slug.
        with_slug = run_script(
            "cloude-list-staging", "--select", "4",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert with_slug.returncode == 0
        assert "SLUG=hand-picked-slug" in with_slug.stdout

    def test_select_out_of_range_exits_2(
        self, run_script, tmp_path, fixtures_dir
    ):
        _build_tasks_tree(tmp_path, fixtures_dir)
        result = run_script(
            "cloude-list-staging", "--select", "999",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 2

    def test_missing_staging_file_returns_empty_listing(
        self, run_script, tmp_path
    ):
        # No staging.org under tmp_path/tasks/.
        (tmp_path / "tasks").mkdir()
        result = run_script(
            "cloude-list-staging",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "PROMOTABLE" in result.stdout
        assert "TODO_PROJECTS 0" in result.stdout


class TestTaskInfo:
    def test_emits_keys_for_complete_file(
        self, run_script, tmp_path, fixtures_dir
    ):
        tasks = _build_tasks_tree(tmp_path, fixtures_dir)
        task = tasks / "active" / "2026-01-01-foo.org"
        task.write_text(
            render_task(
                todo="ITERATING", tag="agent",
                properties={
                    "ID": "fixture",
                    "REPO": "https://github.com/example/example",
                    "BRANCH": "cloude/foo",
                    "WORKTREE": str(tmp_path / "worktrees" / "example" / "foo"),
                    "PR": "https://github.com/example/example/pull/1",
                    "SKIP_REVIEW": "t",
                },
            )
        )
        result = run_script("cloude-task-info", str(task))
        assert result.returncode == 0, result.stderr
        out = result.stdout
        assert "TODO=ITERATING" in out
        assert "TAG=agent" in out
        assert "BRANCH=cloude/foo" in out
        assert "SLUG=foo" in out
        assert "REPO_NAME=example" in out
        assert "TMUX_SESSION=cloude-foo" in out
        assert "DIND_VOLUME=cloude-dind-foo" in out
        assert "SKIP_REVIEW=t" in out

    def test_missing_required_property_exits_3(
        self, run_script, tmp_path, fixtures_dir
    ):
        tasks = _build_tasks_tree(tmp_path, fixtures_dir)
        task = tasks / "active" / "2026-01-01-foo.org"
        # No BRANCH / WORKTREE / PR.
        task.write_text(render_task(todo="PLANNING", tag="user"))
        result = run_script("cloude-task-info", str(task))
        assert result.returncode == 3
        assert "BRANCH" in result.stderr

    def test_missing_file_exits_2(self, run_script, tmp_path):
        result = run_script("cloude-task-info", str(tmp_path / "nope.org"))
        assert result.returncode == 2
