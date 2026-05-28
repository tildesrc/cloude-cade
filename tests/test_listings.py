"""Smoke tests for the read-only listing helpers.

Covers ``cloude-list-active``, ``cloude-list-staging``, and
``cloude-task-info``. Each script is exercised against a temp
``tasks/`` tree (the listers honor ``$CLOUDE_ROOT`` to find tasks).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from conftest import render_task


def _build_tasks_tree(
    tmp_path: Path, fixtures_dir: Path, vault: str = "personal"
) -> Path:
    """Lay out tasks/staging.org + vaults/<vault>/tasks/{active,done}/.

    Returns the top-level ``tasks/`` directory so callers can still
    access ``tasks/staging.org``. The vault's ``active/`` and ``done/``
    subdirs are reachable via ``tasks.parent / "vaults" / vault /
    "tasks" / {"active", "done"}`` or the ``_vault_tasks`` helper.
    """
    tasks = tmp_path / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    shutil.copy(fixtures_dir / "staging.org", tasks / "staging.org")
    vault_tasks = tmp_path / "vaults" / vault / "tasks"
    (vault_tasks / "active").mkdir(parents=True)
    (vault_tasks / "done").mkdir()
    return tasks


def _vault_tasks(tmp_path: Path, vault: str = "personal") -> Path:
    """Return the per-vault ``tasks/`` directory under ``tmp_path``."""
    return tmp_path / "vaults" / vault / "tasks"


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
        _build_tasks_tree(tmp_path, fixtures_dir)
        active = _vault_tasks(tmp_path) / "active"
        (active / "2026-01-01-aaa.org").write_text(
            render_task(todo="PLANNING", title="planning task", tag="user")
        )
        (active / "2026-01-02-bbb.org").write_text(
            render_task(todo="MERGING", title="merging task", tag="agent")
        )
        (active / "2026-01-03-ccc.org").write_text(
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
        _build_tasks_tree(tmp_path, fixtures_dir)
        (_vault_tasks(tmp_path) / "active" / "2026-01-01-aaa.org").write_text(
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
        _build_tasks_tree(tmp_path, fixtures_dir)
        active = _vault_tasks(tmp_path) / "active"
        (active / "2026-01-01-done.org").write_text(
            render_task(todo="COMPLETE", title="done task", tag="user")
        )
        (active / "2026-01-02-gone.org").write_text(
            render_task(todo="DROPPED", title="gone task", tag="user")
        )
        result = run_script(
            "cloude-list-active", "--terminal",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "done task" in result.stdout
        assert "gone task" in result.stdout

    def test_walks_all_vaults_and_tags_each_row(
        self, run_script, tmp_path, fixtures_dir
    ):
        # Seed both `personal` and `work` vaults with one task each;
        # the listing should include both, each tagged with its vault.
        _build_tasks_tree(tmp_path, fixtures_dir)
        personal_active = _vault_tasks(tmp_path, "personal") / "active"
        (personal_active / "2026-01-01-pers.org").write_text(
            render_task(
                todo="ITERATING", title="personal task", tag="agent",
                properties={"VAULT": "personal"},
            )
        )
        work_active = tmp_path / "vaults" / "work" / "tasks" / "active"
        work_active.mkdir(parents=True)
        (work_active / "2026-01-02-work.org").write_text(
            render_task(
                todo="ITERATING", title="work task", tag="agent",
                properties={"VAULT": "work"},
            )
        )
        result = run_script(
            "cloude-list-active",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0, result.stderr
        out = result.stdout
        assert "[personal]" in out
        assert "[work]" in out
        assert "personal task" in out
        assert "work task" in out

    def test_vault_filter_scopes_to_one_vault(
        self, run_script, tmp_path, fixtures_dir
    ):
        _build_tasks_tree(tmp_path, fixtures_dir)
        personal_active = _vault_tasks(tmp_path, "personal") / "active"
        (personal_active / "2026-01-01-pers.org").write_text(
            render_task(todo="ITERATING", title="personal task", tag="agent")
        )
        work_active = tmp_path / "vaults" / "work" / "tasks" / "active"
        work_active.mkdir(parents=True)
        (work_active / "2026-01-02-work.org").write_text(
            render_task(
                todo="ITERATING", title="work task", tag="agent",
                properties={"VAULT": "work"},
            )
        )
        result = run_script(
            "cloude-list-active", "--vault", "work",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0
        assert "work task" in result.stdout
        assert "personal task" not in result.stdout


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
        # Two promotable projects with four ideas total, each row
        # prefixed by its vault slug.
        assert "1) [personal/Example project] First idea" in out
        assert "2) [personal/Example project] Second idea  [ADOPT]" in out
        assert "3) [work/No-review project] Third idea" in out
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
        # Replace fixture wholesale with a vault carrying a single
        # project + idea that already has :SLUG:.
        (tasks / "staging.org").write_text(
            "#+TITLE: Staging\n"
            "* Personal\n"
            "  :PROPERTIES:\n"
            "  :SLUG: personal\n"
            "  :END:\n"
            "** Example project\n"
            "   :PROPERTIES:\n"
            "   :REPO: https://github.com/example/example\n"
            "   :END:\n"
            "*** First idea\n"
            "    :PROPERTIES:\n"
            "    :SLUG: first-idea\n"
            "    :END:\n"
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
            "* Personal\n"
            "  :PROPERTIES:\n"
            "  :SLUG: personal\n"
            "  :END:\n"
            "** Example project\n"
            "   :PROPERTIES:\n"
            "   :REPO: https://github.com/example/example\n"
            "   :END:\n"
            "*** Please suggest a slug\n"
            "    :PROPERTIES:\n"
            "    :SLUG:\n"
            "    :END:\n"
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
        _build_tasks_tree(tmp_path, fixtures_dir)
        task = _vault_tasks(tmp_path) / "active" / "2026-01-01-foo.org"
        task.write_text(
            render_task(
                todo="ITERATING", tag="agent",
                properties={
                    "ID": "fixture",
                    "VAULT": "personal",
                    "REPO": "https://github.com/example/example",
                    "BRANCH": "cloude/foo",
                    "WORKTREE": str(
                        tmp_path / "vaults" / "personal"
                        / "worktrees" / "example" / "foo"
                    ),
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
        assert "VAULT=personal" in out
        assert "REPO_NAME=example" in out
        assert "TMUX_SESSION=cloude-foo" in out
        assert "DIND_VOLUME=cloude-dind-foo" in out
        assert "CLAUDE_CREDS_VOLUME=cloude-claude-creds-personal" in out
        assert "SKIP_REVIEW=t" in out
        # SOURCE_CLONE lands under the vault's repos/ subdir.
        assert (
            f"SOURCE_CLONE={tmp_path}/vaults/personal/repos/example" in out
        )

    def test_missing_required_property_exits_3(
        self, run_script, tmp_path, fixtures_dir
    ):
        _build_tasks_tree(tmp_path, fixtures_dir)
        task = _vault_tasks(tmp_path) / "active" / "2026-01-01-foo.org"
        # render_task seeds VAULT=personal by default; pass an
        # explicit empty-properties dict so we can rebuild without it.
        # Easiest: render with a plain template, then strip VAULT
        # line so we can verify the VAULT-missing error path too.
        content = render_task(
            todo="PLANNING", tag="user",
            properties={"ID": "fixture", "VAULT": "personal",
                        "REPO": "https://github.com/example/example"},
        )
        task.write_text(content)
        # No BRANCH / WORKTREE / PR set — those are the missing requireds.
        result = run_script("cloude-task-info", str(task))
        assert result.returncode == 3
        assert "BRANCH" in result.stderr

    def test_missing_file_exits_2(self, run_script, tmp_path):
        result = run_script("cloude-task-info", str(tmp_path / "nope.org"))
        assert result.returncode == 2
