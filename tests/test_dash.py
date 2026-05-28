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
from pathlib import Path

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
        (tasks_dir / "done").mkdir()
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
        (tasks_dir / "done").mkdir()
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
        (tasks_dir / "done").mkdir()
        shutil.copy(fixtures_dir / "staging.org", tasks_dir / "staging.org")
        # Drop RECENT_LIMIT + 5 completed files in.
        n = dash.RECENT_LIMIT + 5
        for i in range(n):
            (tasks_dir / "done" / f"2026-01-{i + 1:02d}-task.org").write_text(
                render_task(todo="COMPLETE", title=f"task {i}", tag="user")
            )
        monkeypatch.setattr(dash, "TASKS", tasks_dir)
        groups = dash.load_tasks()
        assert len(groups[dash.RECENT]) == dash.RECENT_LIMIT

    def test_recent_state_drawn_from_heading_keyword(
        self, dash, tmp_path, fixtures_dir, monkeypatch
    ):
        # Now that completed/ and dropped/ are merged into done/, the
        # RECENT loader can no longer infer state from the directory
        # name. Pin that the per-task state comes from the heading TODO
        # keyword by dropping one COMPLETE and one DROPPED file into
        # done/ and checking the loaded states.
        tasks_dir = tmp_path / "tasks"
        (tasks_dir / "active").mkdir(parents=True)
        (tasks_dir / "done").mkdir()
        shutil.copy(fixtures_dir / "staging.org", tasks_dir / "staging.org")
        (tasks_dir / "done" / "2026-01-01-merged.org").write_text(
            render_task(todo="COMPLETE", title="merged t", tag="user")
        )
        (tasks_dir / "done" / "2026-01-02-abandoned.org").write_text(
            render_task(todo="DROPPED", title="abandoned t", tag="user")
        )
        monkeypatch.setattr(dash, "TASKS", tasks_dir)
        groups = dash.load_tasks()
        recent = groups[dash.RECENT]
        states = sorted(t.state for t in recent)
        assert states == ["COMPLETE", "DROPPED"]


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
        # A task file is moved active/ -> done/ as part of /finalize;
        # the filename is preserved. _task_key should match before and
        # after on (filename, title).
        before = tmp_path / "active" / "2026-01-01-foo.org"
        after = tmp_path / "done" / "2026-01-01-foo.org"
        before.parent.mkdir(parents=True)
        after.parent.mkdir(parents=True)
        for p in (before, after):
            p.write_text(render_task(todo="COMPLETE", title="title", tag="user"))
        t1 = dash._load_single_task_file(before, dash.ACTIVE)
        t2 = dash._load_single_task_file(after, dash.RECENT)
        assert dash._task_key(t1) == dash._task_key(t2)


class TestNewestActiveRowIndex:
    """The `P` keypath lands the highlight on the just-promoted ACTIVE
    row by picking the ACTIVE ROW_TASK with the freshest `Task.ctime`.
    The promote chain's last step writes `tasks/active/<date>-<slug>.org`,
    so that file's ctime overwhelmingly wins. The helper isolates the
    pick logic so the `P` branch in `_run` stays a one-liner.
    """

    @staticmethod
    def _task(dash, section, name, ctime):
        return dash.Task(
            section=section,
            state="ITERATING" if section == dash.ACTIVE else "COMPLETE",
            tag="agent",
            title=name,
            pr_url=None,
            repo=None,
            path=Path("/tmp") / name,
            ctime=ctime,
        )

    def test_returns_index_of_active_row_with_max_ctime(self, dash):
        a1 = self._task(dash, dash.ACTIVE, "a1.org", ctime=100.0)
        a2 = self._task(dash, dash.ACTIVE, "a2.org", ctime=200.0)  # freshest
        a3 = self._task(dash, dash.ACTIVE, "a3.org", ctime=150.0)
        rows = [
            (dash.ROW_HEADER, "ACTIVE (3)"),
            (dash.ROW_TASK, a1),
            (dash.ROW_TASK, a2),
            (dash.ROW_TASK, a3),
        ]
        assert dash._newest_active_row_index(rows) == 2

    def test_returns_none_when_no_active_rows(self, dash):
        # Filter that hides ACTIVE collapses the section entirely — the
        # helper sees no ACTIVE ROW_TASKs and signals "leave the
        # selection wherever reload's fallback put it".
        rows = [
            (dash.ROW_HEADER, "STAGING (1)"),
            (dash.ROW_TASK, self._task(dash, dash.STAGING, "idea.org", ctime=10.0)),
        ]
        assert dash._newest_active_row_index(rows) is None

    def test_ignores_recent_rows_with_fresher_ctime(self, dash):
        # A just-finalized task lives in done/ with a very fresh
        # ctime from the active/->done/ rename. The helper must
        # not jump the cursor onto it.
        active = self._task(dash, dash.ACTIVE, "act.org", ctime=100.0)
        recent = self._task(dash, dash.RECENT, "rec.org", ctime=999.0)
        rows = [
            (dash.ROW_HEADER, "ACTIVE (1)"),
            (dash.ROW_TASK, active),
            (dash.ROW_HEADER, "RECENT (1)"),
            (dash.ROW_TASK, recent),
        ]
        assert dash._newest_active_row_index(rows) == 1


class TestWrapLines:
    """`_wrap_lines` powers the promote-modal body renderer: it
    flattens a streamed output buffer into rows that fit the modal's
    inner width so `addnstr` can draw them without truncating at the
    border. The behaviour is tiny but load-bearing — if it ever
    truncates instead of wrapping, long paths in the orchestrator's
    summary block stop being visible.
    """

    def test_short_lines_unchanged(self, dash):
        assert dash._wrap_lines("abc\ndef", 10) == ["abc", "def"]

    def test_empty_lines_preserved(self, dash):
        assert dash._wrap_lines("a\n\nb", 10) == ["a", "", "b"]

    def test_long_line_hard_wraps(self, dash):
        assert dash._wrap_lines("abcdefghij", 4) == ["abcd", "efgh", "ij"]

    def test_mixed_wrap_and_short(self, dash):
        result = dash._wrap_lines("hello\nworldwide", 5)
        assert result == ["hello", "world", "wide"]

    def test_empty_input_yields_one_empty_line(self, dash):
        # split("\n") on "" returns [""], which preserves a single
        # empty row — important for the modal's "no output yet"
        # branch to know it has zero real content.
        assert dash._wrap_lines("", 10) == [""]

    def test_zero_width_returns_empty(self, dash):
        # Defensive: a degenerate width should not loop forever.
        assert dash._wrap_lines("abc", 0) == []

    def test_exact_width_no_wrap(self, dash):
        # A line exactly at the width fits on one row (no spillover).
        assert dash._wrap_lines("abcd", 4) == ["abcd"]


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


class TestFinalizeOverrides:
    """The exit-code → (prompt, flag) table the `f` key uses to walk
    the override-able failures from `bin/cloude-finalize-cleanup`.

    The contract this test locks in is twofold:

    * Codes 12 / 13 / 14 each map to the matching `--force-worktree` /
      `--skip-volume` / `--force-root` flag — the same overrides
      `/finalize`'s skill walks the user through. If
      cloude-finalize-cleanup's exit-code table changes, this test
      should fail loudly so the dashboard mapping stays in sync.
    * Code 10 (PR not MERGED) is intentionally absent — it's a hard
      fail with no retry on the dashboard, same as in `/finalize`.
    """

    def test_maps_exit_codes_to_matching_flags(self, dash):
        assert dash._FINALIZE_OVERRIDES[12][1] == "--force-worktree"
        assert dash._FINALIZE_OVERRIDES[13][1] == "--skip-volume"
        assert dash._FINALIZE_OVERRIDES[14][1] == "--force-root"

    def test_does_not_cover_hard_fail_exit_codes(self, dash):
        # 10 (PR not MERGED) and 11 (non-terminal, --force-drop not
        # given) must never appear here — both are non-retryable from
        # the dashboard side.
        assert 10 not in dash._FINALIZE_OVERRIDES
        assert 11 not in dash._FINALIZE_OVERRIDES

    def test_prompts_are_y_n_questions(self, dash):
        # The prompts are rendered in the finalize modal's footer and
        # answered via `_modal_read_yn` (y/Y → True; n/N/Esc/q/Enter →
        # False) — keep them in the same shape so the user always
        # knows what they're answering.
        for code, (prompt, _flag) in dash._FINALIZE_OVERRIDES.items():
            assert "[y/N]" in prompt, f"exit {code}: {prompt!r}"

    def test_override_codes_also_appear_in_exit_messages(self, dash):
        # Every override-able code must also have a human-readable
        # label in _FINALIZE_EXIT_MESSAGES — the modal uses that label
        # when the user answers N to the override prompt and we render
        # the final "finalize failed: <reason>" status line. If the two
        # tables drift, the failure-side copy would silently fall back
        # to `exit N` for codes the user actually saw a prompt for.
        for code in dash._FINALIZE_OVERRIDES:
            assert code in dash._FINALIZE_EXIT_MESSAGES, (
                f"override code {code} missing from _FINALIZE_EXIT_MESSAGES"
            )


class TestFinalizeExitMessages:
    """`_FINALIZE_EXIT_MESSAGES` powers the finalize modal's
    `exit N (reason) — Enter/q to close` footer and the dashboard's
    `finalize failed: <reason>` status-line copy. The reasons are
    sourced from `bin/cloude-finalize-cleanup`'s usage block; if a
    new exit code is added there without a matching entry here, the
    modal silently falls back to a bare `exit N` footer.
    """

    # Every exit code documented in cloude-finalize-cleanup's usage
    # block as of this commit. Drives the completeness check below.
    _DOCUMENTED_CODES = frozenset(
        {10, 11, 12, 13, 14, 15, 20, 21, 22, 23, 25, 26, 30}
    )

    def test_covers_every_documented_exit_code(self, dash):
        missing = self._DOCUMENTED_CODES - dash._FINALIZE_EXIT_MESSAGES.keys()
        assert not missing, (
            f"_FINALIZE_EXIT_MESSAGES is missing entries for: {sorted(missing)}"
        )

    def test_does_not_invent_codes_not_in_the_script(self, dash):
        extra = dash._FINALIZE_EXIT_MESSAGES.keys() - self._DOCUMENTED_CODES
        assert not extra, (
            f"_FINALIZE_EXIT_MESSAGES has codes not documented in "
            f"cloude-finalize-cleanup: {sorted(extra)}"
        )

    def test_reasons_are_non_empty_strings(self, dash):
        for code, reason in dash._FINALIZE_EXIT_MESSAGES.items():
            assert isinstance(reason, str) and reason.strip(), (
                f"exit {code} reason is empty: {reason!r}"
            )


class TestFinalizeStatusMessage:
    """`_finalize_status_message` is the pure copy-generator the
    dashboard's status line uses once the finalize modal dismisses.
    Locks in the four user-visible outcomes."""

    def test_success(self, dash):
        msg = dash._finalize_status_message(
            exit_code=0, aborted=False, title="my task"
        )
        assert msg == "finalized: my task"

    def test_aborted_at_initial_force_drop(self, dash):
        # Initial force-drop-N path: no subprocess ran, so exit_code
        # is 0 but aborted is True.
        msg = dash._finalize_status_message(
            exit_code=0, aborted=True, title="my task"
        )
        assert msg == "finalize aborted"

    def test_aborted_at_override_prompt(self, dash):
        # User answered N to an override prompt after a non-zero exit
        # (e.g. 12 / 13 / 14). Status line still reads "aborted" so
        # it reflects the user choice rather than blaming the exit
        # code the override would have papered over.
        msg = dash._finalize_status_message(
            exit_code=12, aborted=True, title="my task"
        )
        assert msg == "finalize aborted"

    def test_failure_uses_mapped_reason(self, dash):
        # An exit code present in _FINALIZE_EXIT_MESSAGES is rendered
        # with the human label.
        msg = dash._finalize_status_message(
            exit_code=10, aborted=False, title="my task"
        )
        assert msg == "finalize failed: PR not MERGED"

    def test_failure_falls_back_to_bare_exit_code(self, dash):
        # An unmapped exit code (shouldn't happen in practice, but
        # cheap to guard) renders as `exit N`.
        msg = dash._finalize_status_message(
            exit_code=99, aborted=False, title="my task"
        )
        assert msg == "finalize failed: exit 99"


class TestHandleResize:
    """`_handle_resize` is the small helper the dashboard calls on every
    `curses.KEY_RESIZE`. The contract is:

    * refresh curses' cached LINES/COLS so subsequent ``getmaxyx`` calls
      return the new dimensions,
    * clear stdscr so the next draw paints a clean canvas at the new
      size (no stale rows leaking from the old size),
    * refresh stdscr so the clear becomes visible immediately.

    Without this, modal helpers that redraw before blocking would paint
    on top of the old canvas at the old getmaxyx, which is exactly the
    bug this whole task is fixing.
    """

    def test_calls_update_lines_cols_then_erase_then_refresh(
        self, dash, monkeypatch
    ):
        import curses
        from unittest.mock import MagicMock

        order: list[str] = []
        monkeypatch.setattr(
            curses, "update_lines_cols", lambda: order.append("update_lines_cols")
        )
        stdscr = MagicMock()
        stdscr.erase.side_effect = lambda: order.append("erase")
        stdscr.refresh.side_effect = lambda: order.append("refresh")

        dash._handle_resize(stdscr)

        assert order == ["update_lines_cols", "erase", "refresh"]

    def test_tolerates_missing_update_lines_cols(self, dash, monkeypatch):
        # Defensive: `update_lines_cols` has been in CPython since 3.5
        # and this script requires 3.11, but the helper guards with
        # hasattr so it can't break on a stripped-down curses build.
        import curses
        from unittest.mock import MagicMock

        # Remove the attribute and assert _handle_resize still clears.
        monkeypatch.delattr(curses, "update_lines_cols", raising=False)
        stdscr = MagicMock()
        dash._handle_resize(stdscr)
        stdscr.erase.assert_called_once()
        stdscr.refresh.assert_called_once()


class TestModalReadYnResize:
    """`_modal_read_yn` blocks on stdscr.getch() until y/Y or
    n/N/Esc/q/Enter. The resize-handling contract is:

    * `redraw` is called once before the first getch (prompt visibility),
    * on a `curses.KEY_RESIZE` it calls `_handle_resize` and then
      `redraw` again before continuing — so the modal re-flows at the
      new terminal dimensions instead of staying frozen at old size,
    * idle ticks (`ch == -1`) do NOT re-call `redraw` — the modal
      contents are stable between resizes / keystrokes.

    Driven via a fake stdscr that returns a scripted sequence of getch
    return values.
    """

    def _fake_stdscr(self, getch_returns: list[int]):
        from unittest.mock import MagicMock

        stdscr = MagicMock()
        stdscr.getch.side_effect = list(getch_returns)
        return stdscr

    def test_redraws_once_on_initial_prompt(self, dash):
        from unittest.mock import MagicMock

        stdscr = self._fake_stdscr([ord("y")])
        redraw = MagicMock()
        assert dash._modal_read_yn(stdscr, redraw) is True
        assert redraw.call_count == 1

    def test_redraws_again_on_key_resize(self, dash, monkeypatch):
        import curses
        from unittest.mock import MagicMock

        handle_resize = MagicMock()
        monkeypatch.setattr(dash, "_handle_resize", handle_resize)
        stdscr = self._fake_stdscr([curses.KEY_RESIZE, ord("y")])
        redraw = MagicMock()

        assert dash._modal_read_yn(stdscr, redraw) is True
        # Once before the loop, once for the resize event.
        assert redraw.call_count == 2
        handle_resize.assert_called_once_with(stdscr)

    def test_idle_tick_does_not_redraw(self, dash):
        from unittest.mock import MagicMock

        # -1 from getch is the idle-tick (curses timeout). It should
        # NOT trigger a redraw — the modal isn't changing while we
        # wait. (If it did, every 500ms idle would flicker the screen.)
        stdscr = self._fake_stdscr([-1, -1, ord("n")])
        redraw = MagicMock()
        assert dash._modal_read_yn(stdscr, redraw) is False
        assert redraw.call_count == 1

    def test_returns_false_on_n_q_esc_enter(self, dash):
        import curses
        from unittest.mock import MagicMock

        for ch in (
            ord("n"), ord("N"), ord("q"), 27,
            curses.KEY_ENTER, 10, 13,
        ):
            stdscr = self._fake_stdscr([ch])
            assert dash._modal_read_yn(stdscr, MagicMock()) is False


class TestModalWaitDismissResize:
    """`_modal_wait_dismiss` blocks until q/Esc/Enter. Same
    resize-handling contract as `_modal_read_yn`: initial redraw,
    redraw again on KEY_RESIZE, no redraw on idle ticks.
    """

    def _fake_stdscr(self, getch_returns: list[int]):
        from unittest.mock import MagicMock

        stdscr = MagicMock()
        stdscr.getch.side_effect = list(getch_returns)
        return stdscr

    def test_redraws_on_initial_call_and_returns_on_dismiss(self, dash):
        from unittest.mock import MagicMock

        stdscr = self._fake_stdscr([ord("q")])
        redraw = MagicMock()
        dash._modal_wait_dismiss(stdscr, redraw)
        assert redraw.call_count == 1

    def test_redraws_again_on_key_resize(self, dash, monkeypatch):
        import curses
        from unittest.mock import MagicMock

        handle_resize = MagicMock()
        monkeypatch.setattr(dash, "_handle_resize", handle_resize)
        stdscr = self._fake_stdscr([curses.KEY_RESIZE, ord("q")])
        redraw = MagicMock()

        dash._modal_wait_dismiss(stdscr, redraw)
        assert redraw.call_count == 2
        handle_resize.assert_called_once_with(stdscr)

    def test_idle_tick_does_not_redraw(self, dash):
        from unittest.mock import MagicMock

        stdscr = self._fake_stdscr([-1, -1, 27])  # Esc
        redraw = MagicMock()
        dash._modal_wait_dismiss(stdscr, redraw)
        assert redraw.call_count == 1
