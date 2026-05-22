"""Tests for ``bin/cloude-dash``'s pure data layer.

Imports the script as a module via the ``import_script`` fixture so
the curses entry point never runs. Covers task loading, repo-URL
canonicalization, sort/identity helpers, and the small
filename-derived utilities.

The curses rendering and the inotify watcher loop are intentionally
not covered — they sit behind ``main()`` and ``_run()``.
"""

from __future__ import annotations

import shutil

import pytest

from conftest import render_task


@pytest.fixture
def dash(import_script):
    return import_script("cloude-dash")


class TestRepoUrlHelpers:
    @pytest.mark.parametrize(
        "url,want",
        [
            ("https://github.com/owner/repo", "owner/repo"),
            ("https://github.com/owner/repo.git", "owner/repo"),
            ("https://github.com/owner/repo/", "owner/repo"),
            ("git@github.com:owner/repo", "owner/repo"),
            ("git@github.com:owner/repo.git", "owner/repo"),
            ("owner/repo", "owner/repo"),
        ],
    )
    def test_repo_path_normalizes_forms(self, dash, url, want):
        assert dash._repo_path(url) == want

    def test_repo_key_is_case_folded(self, dash):
        assert dash._repo_key("https://github.com/Owner/Repo") == "owner/repo"
        assert dash._repo_key("git@github.com:OWNER/REPO.git") == "owner/repo"

    def test_repo_label_falls_back_to_owner_repo(self, dash):
        # No matching project header; label is the owner/repo path.
        assert dash._repo_label("https://github.com/o/r", {}) == "o/r"

    def test_repo_label_uses_known_project_header(self, dash):
        names = {"owner/repo": "My nice project"}
        assert (
            dash._repo_label("https://github.com/owner/repo", names)
            == "My nice project"
        )

    def test_repo_label_empty_for_none(self, dash):
        assert dash._repo_label(None, {}) == ""


class TestFilenameHelpers:
    def test_date_from_filename_extracts_prefix(self, dash, tmp_path):
        p = tmp_path / "2026-05-20-foo.org"
        p.touch()
        assert dash._date_from_filename(p) == "2026-05-20"

    def test_date_from_filename_returns_empty_for_unprefixed(
        self, dash, tmp_path
    ):
        p = tmp_path / "no-date-prefix.org"
        p.touch()
        assert dash._date_from_filename(p) == ""

    def test_slug_from_filename(self, dash, tmp_path):
        p = tmp_path / "2026-05-20-my-task-slug.org"
        p.touch()
        assert dash._slug_from_filename(p) == "my-task-slug"

    def test_pr_number_extracts_int_tail(self, dash):
        assert dash._pr_number("https://github.com/o/r/pull/42") == "PR #42"

    def test_pr_number_returns_url_when_no_int(self, dash):
        url = "https://github.com/o/r/pull/abc"
        assert dash._pr_number(url) == url

    def test_pr_number_empty_for_none(self, dash):
        assert dash._pr_number(None) == ""


class TestLoadSingleTaskFile:
    def test_returns_task_for_valid_file(self, dash, tmp_path):
        p = tmp_path / "2026-05-20-foo.org"
        p.write_text(
            render_task(
                todo="ITERATING", tag="agent",
                properties={
                    "ID": "fixture",
                    "REPO": "https://github.com/example/example",
                    "PR": "https://github.com/example/example/pull/7",
                },
            )
        )
        task = dash._load_single_task_file(p, dash.ACTIVE)
        assert task is not None
        assert task.state == "ITERATING"
        assert task.tag == "agent"
        assert task.pr_url == "https://github.com/example/example/pull/7"
        assert task.repo == "https://github.com/example/example"

    def test_returns_none_for_empty_file(self, dash, tmp_path):
        p = tmp_path / "empty.org"
        p.write_text("")
        assert dash._load_single_task_file(p, dash.ACTIVE) is None


class TestLoadTasks:
    def test_active_sorted_by_stage_priority_then_filename(
        self, dash, tmp_path, fixtures_dir, monkeypatch
    ):
        tasks_dir = tmp_path / "tasks"
        (tasks_dir / "active").mkdir(parents=True)
        (tasks_dir / "completed").mkdir()
        (tasks_dir / "dropped").mkdir()
        shutil.copy(fixtures_dir / "staging.org", tasks_dir / "staging.org")
        (tasks_dir / "active" / "2026-01-01-aaa.org").write_text(
            render_task(todo="PLANNING", title="planning t", tag="user")
        )
        (tasks_dir / "active" / "2026-01-02-bbb.org").write_text(
            render_task(todo="MERGING", title="merging t", tag="agent")
        )
        monkeypatch.setattr(dash, "TASKS", tasks_dir)
        groups = dash.load_tasks()
        active = groups[dash.ACTIVE]
        # MERGING (priority 0) first, then PLANNING (priority 3).
        assert [t.state for t in active] == ["MERGING", "PLANNING"]

    def test_repo_labels_resolved_against_staging_projects(
        self, dash, tmp_path, fixtures_dir, monkeypatch
    ):
        tasks_dir = tmp_path / "tasks"
        (tasks_dir / "active").mkdir(parents=True)
        (tasks_dir / "completed").mkdir()
        (tasks_dir / "dropped").mkdir()
        shutil.copy(fixtures_dir / "staging.org", tasks_dir / "staging.org")
        (tasks_dir / "active" / "2026-01-01-t.org").write_text(
            render_task(
                todo="ITERATING", tag="agent",
                properties={
                    "ID": "t",
                    "REPO": "https://github.com/example/example",
                },
            )
        )
        monkeypatch.setattr(dash, "TASKS", tasks_dir)
        groups = dash.load_tasks()
        active = groups[dash.ACTIVE]
        # The active task's raw :REPO: URL got rewritten to the
        # staging-project header text.
        assert active[0].repo == "Example project"

    def test_recent_capped_at_limit(
        self, dash, tmp_path, fixtures_dir, monkeypatch
    ):
        tasks_dir = tmp_path / "tasks"
        (tasks_dir / "active").mkdir(parents=True)
        (tasks_dir / "completed").mkdir()
        (tasks_dir / "dropped").mkdir()
        shutil.copy(fixtures_dir / "staging.org", tasks_dir / "staging.org")
        # Drop RECENT_LIMIT + 5 completed files in.
        n = dash.RECENT_LIMIT + 5
        for i in range(n):
            (tasks_dir / "completed" / f"2026-01-{i + 1:02d}-task.org").write_text(
                render_task(todo="COMPLETE", title=f"task {i}", tag="user")
            )
        monkeypatch.setattr(dash, "TASKS", tasks_dir)
        groups = dash.load_tasks()
        assert len(groups[dash.RECENT]) == dash.RECENT_LIMIT


class TestStagingOrderMatchesListing:
    """The `P` key on the dashboard turns the highlighted STAGING row's
    position in `groups[STAGING]` into a `--select N` index for
    `cloude-list-staging`. The two code paths walk the same tree
    independently, so this regression test pins down that they agree
    on the order — if either side ever changes its filter or iteration
    direction, this test will catch it before the `P` key promotes the
    wrong idea.
    """

    def test_dash_staging_matches_cloude_list_staging_indices(
        self, dash, run_script, tmp_path, fixtures_dir, monkeypatch
    ):
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir(parents=True)
        shutil.copy(fixtures_dir / "staging.org", tasks_dir / "staging.org")
        monkeypatch.setattr(dash, "TASKS", tasks_dir)
        groups = dash.load_tasks()
        dash_titles = [t.title for t in groups[dash.STAGING]]
        # Now ask cloude-list-staging for each index in order and
        # collect the HEADING field. The two should match item-for-item.
        listing_titles: list[str] = []
        for i in range(1, len(dash_titles) + 1):
            r = run_script(
                "cloude-list-staging", "--select", str(i),
                env={"CLOUDE_ROOT": str(tmp_path)},
            )
            assert r.returncode == 0, r.stderr
            for line in r.stdout.splitlines():
                if line.startswith("HEADING="):
                    # Strip the shell-quoted value: HEADING='foo bar' or HEADING=foo
                    val = line.split("=", 1)[1]
                    if val.startswith("'") and val.endswith("'"):
                        val = val[1:-1]
                    listing_titles.append(val)
                    break
        assert dash_titles == listing_titles


class TestTaskKey:
    def test_stable_identity_across_directory_moves(self, dash, tmp_path):
        # A task file is moved active/ -> completed/ as part of /finalize;
        # the filename is preserved. _task_key should match before and
        # after on (filename, title).
        before = tmp_path / "active" / "2026-01-01-foo.org"
        after = tmp_path / "completed" / "2026-01-01-foo.org"
        before.parent.mkdir(parents=True)
        after.parent.mkdir(parents=True)
        for p in (before, after):
            p.write_text(render_task(todo="COMPLETE", title="title", tag="user"))
        t1 = dash._load_single_task_file(before, dash.ACTIVE)
        t2 = dash._load_single_task_file(after, dash.RECENT)
        assert dash._task_key(t1) == dash._task_key(t2)


class TestFlatten:
    def test_filters_to_matching_titles_and_drops_empty_sections(
        self, dash, tmp_path
    ):
        # Build two active tasks; filter to one of them.
        p1 = tmp_path / "2026-01-01-aaa.org"
        p2 = tmp_path / "2026-01-02-bbb.org"
        p1.write_text(render_task(todo="ITERATING", title="cat task", tag="agent"))
        p2.write_text(render_task(todo="ITERATING", title="dog task", tag="agent"))
        active = [
            dash._load_single_task_file(p1, dash.ACTIVE),
            dash._load_single_task_file(p2, dash.ACTIVE),
        ]
        groups = {
            dash.ACTIVE: active,
            dash.STAGING: [],
            dash.TODO: {},
            dash.RECENT: [],
        }
        rows = dash._flatten(groups, query="cat")
        # ACTIVE header with `(1/2)` cookie + one task row. STAGING and
        # RECENT sections are dropped entirely (empty after filtering).
        kinds = [kind for kind, _ in rows]
        assert kinds == [dash.ROW_HEADER, dash.ROW_TASK]
        header = rows[0][1]
        assert "(1/2)" in header

    def test_unfiltered_shows_all_top_sections_even_when_empty(
        self, dash
    ):
        groups = {dash.ACTIVE: [], dash.STAGING: [], dash.TODO: {}, dash.RECENT: []}
        rows = dash._flatten(groups)
        # ACTIVE, STAGING, RECENT each get a header + EMPTY row.
        headers = [v for kind, v in rows if kind == dash.ROW_HEADER]
        assert headers == ["ACTIVE (0)", "STAGING (0)", "RECENT (0)"]
