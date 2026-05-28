"""Tests for ``bin/cloude-promote``.

Two layers:

  - In-process unit tests against ``derive_slug`` and ``parse_repo_url``
    (loaded via the ``import_script`` fixture, same pattern other tests
    use for the no-extension polyglot helpers).
  - Subprocess tests run the script under ``CLOUDE_PROMOTE_DRY_RUN=1``
    against a faked staging tree with a stubbed ``gh`` on PATH. The
    dry-run mode prints the assembled ``cloude-promote-setup`` argv —
    one arg per line — so the tests can assert against a deterministic
    layout without actually invoking the atomic chain (which would
    open git worktrees, call ``gh pr create``, start tmux, etc.).
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import pytest

from conftest import render_task  # noqa: F401  (kept for parity)


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class TestDeriveSlug:
    def test_basic_lowercases_and_dashes(self, import_script):
        promote = import_script("cloude-promote")
        assert promote.derive_slug("Hook to auto-move COMPLETE files") == (
            "hook-to-auto-move-complete-files"
        )

    def test_collapses_repeated_separators(self, import_script):
        promote = import_script("cloude-promote")
        assert promote.derive_slug("a  b...c!!!d") == "a-b-c-d"

    def test_strips_leading_and_trailing_punctuation(self, import_script):
        promote = import_script("cloude-promote")
        assert promote.derive_slug("???wrap???") == "wrap"

    def test_all_non_alphanumeric_yields_empty(self, import_script):
        promote = import_script("cloude-promote")
        assert promote.derive_slug("!!! @@@ ###") == ""

    def test_numbers_preserved(self, import_script):
        promote = import_script("cloude-promote")
        assert promote.derive_slug("v2 release pipeline") == "v2-release-pipeline"


class TestParseRepoUrl:
    def test_https_form(self, import_script):
        promote = import_script("cloude-promote")
        assert promote.parse_repo_url("https://github.com/owner/repo") == (
            "owner",
            "repo",
        )

    def test_https_form_with_git_suffix(self, import_script):
        promote = import_script("cloude-promote")
        assert promote.parse_repo_url("https://github.com/owner/repo.git") == (
            "owner",
            "repo",
        )

    def test_scp_form_ssh(self, import_script):
        promote = import_script("cloude-promote")
        assert promote.parse_repo_url("git@github.com:owner/repo.git") == (
            "owner",
            "repo",
        )

    def test_unsupported_shape_raises(self, import_script):
        promote = import_script("cloude-promote")
        with pytest.raises(ValueError):
            promote.parse_repo_url("ftp://example.com/foo/bar")


# ---------------------------------------------------------------------------
# Subprocess tests
# ---------------------------------------------------------------------------


def _build_tasks_tree(tmp_path: Path, fixtures_dir: Path) -> Path:
    """Lay out tasks/staging.org + vaults/personal/tasks/active/ under tmp_path.

    Returns the top-level ``tasks/`` dir so callers can still access
    ``tasks/staging.org``. Per-vault active task files land under
    ``vaults/personal/tasks/active/`` after promote runs.
    """
    tasks = tmp_path / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    shutil.copy(fixtures_dir / "staging.org", tasks / "staging.org")
    (tmp_path / "vaults" / "personal" / "tasks" / "active").mkdir(parents=True)
    return tasks


def _install_gh_stub(tmp_path: Path, script_body: str) -> Path:
    """Drop a fake ``gh`` on a temp PATH; return that dir.

    ``script_body`` is the body of the script after the shebang. It can
    branch on ``$1 $2`` to return different JSON for ``repo view`` vs
    ``pr view``. Failure tests can ``exit 1`` here to simulate a gh
    error.
    """
    bindir = tmp_path / "ghstub"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text("#!/usr/bin/env bash\n" + script_body + "\n")
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bindir


_GH_STUB_OK = """\
case "$1 $2" in
  "repo view")
    echo '{"defaultBranchRef": {"name": "master"}}' ;;
  "pr view")
    echo '{"number":99,"state":"OPEN","headRefName":"feature/x","baseRefName":"master","isCrossRepository":false,"headRepositoryOwner":{"login":"example"},"headRepository":{"name":"example"},"url":"https://github.com/example/example/pull/99"}' ;;
  *) echo "unexpected gh: $@" >&2; exit 1 ;;
esac
"""


def _dry_run_env(tmp_path: Path, gh_dir: Path) -> dict[str, str]:
    """Env vars for a cloude-promote --select N invocation under dry-run."""
    return {
        "CLOUDE_ROOT": str(tmp_path),
        "CLOUDE_PROMOTE_DRY_RUN": "1",
        # Prepend the gh stub dir so it wins over a real ``gh``.
        "PATH": str(gh_dir) + os.pathsep + os.environ.get("PATH", ""),
    }


def _argv_to_dict(stdout: str) -> dict[str, object]:
    """Parse cloude-promote's dry-run output into a flag map.

    Layout: line 0 is the cloude-promote-setup path, then ``--flag``
    lines alternate with their values (or a bare ``--flag`` for a
    boolean switch like ``--skip-review``). Returns a dict from flag
    name (sans the ``--``) to its value (or True for a bare switch);
    the leading executable path is keyed as ``"_argv0"``.
    """
    lines = stdout.splitlines()
    out: dict[str, object] = {"_argv0": lines[0]}
    i = 1
    while i < len(lines):
        flag = lines[i]
        assert flag.startswith("--"), flag
        key = flag[2:]
        # Booleans are unfollowed by a non-flag line; peek ahead.
        if i + 1 >= len(lines) or lines[i + 1].startswith("--"):
            out[key] = True
            i += 1
        else:
            out[key] = lines[i + 1]
            i += 2
    return out


class TestPromoteSubprocess:
    def test_standard_mode_derives_slug_from_heading(
        self, run_script, tmp_path, fixtures_dir
    ):
        _build_tasks_tree(tmp_path, fixtures_dir)
        gh_dir = _install_gh_stub(tmp_path, _GH_STUB_OK)
        result = run_script(
            "cloude-promote", "--select", "1",
            env=_dry_run_env(tmp_path, gh_dir),
        )
        assert result.returncode == 0, result.stderr
        argv = _argv_to_dict(result.stdout)
        assert argv["mode"] == "standard"
        assert argv["slug"] == "first-idea"
        assert argv["repo-url"] == "https://github.com/example/example"
        assert argv["heading"] == "First idea"
        assert argv["staging-heading"] == "First idea"
        assert argv["default-branch"] == "master"
        # No --skip-review on the Example project (lacks the flag).
        assert "skip-review" not in argv
        # No --companion when COMPANION is empty.
        assert "companion" not in argv
        # Task file lives under <CLOUDE_ROOT>/vaults/<vault>/tasks/active/
        # <date>-<slug>.org. The "Example project" lives under the
        # "personal" vault in the fixture.
        assert argv["vault"] == "personal"
        assert (
            str(tmp_path / "vaults" / "personal" / "tasks" / "active")
            in str(argv["task-file"])
        )
        assert str(argv["task-file"]).endswith("first-idea.org")

    def test_slug_flag_overrides_heading_derive(
        self, run_script, tmp_path, fixtures_dir
    ):
        _build_tasks_tree(tmp_path, fixtures_dir)
        gh_dir = _install_gh_stub(tmp_path, _GH_STUB_OK)
        result = run_script(
            "cloude-promote", "--select", "1", "--slug", "custom-override",
            env=_dry_run_env(tmp_path, gh_dir),
        )
        assert result.returncode == 0, result.stderr
        argv = _argv_to_dict(result.stdout)
        assert argv["slug"] == "custom-override"

    def test_staging_slug_property_beats_heading_derive(
        self, run_script, tmp_path, fixtures_dir
    ):
        """Idea #4 in the fixture carries :SLUG: hand-picked-slug."""
        _build_tasks_tree(tmp_path, fixtures_dir)
        gh_dir = _install_gh_stub(tmp_path, _GH_STUB_OK)
        result = run_script(
            "cloude-promote", "--select", "4",
            env=_dry_run_env(tmp_path, gh_dir),
        )
        assert result.returncode == 0, result.stderr
        argv = _argv_to_dict(result.stdout)
        assert argv["slug"] == "hand-picked-slug"

    def test_slug_flag_beats_staging_slug_property(
        self, run_script, tmp_path, fixtures_dir
    ):
        _build_tasks_tree(tmp_path, fixtures_dir)
        gh_dir = _install_gh_stub(tmp_path, _GH_STUB_OK)
        result = run_script(
            "cloude-promote", "--select", "4", "--slug", "flag-wins",
            env=_dry_run_env(tmp_path, gh_dir),
        )
        assert result.returncode == 0, result.stderr
        argv = _argv_to_dict(result.stdout)
        assert argv["slug"] == "flag-wins"

    def test_skip_review_propagates_from_project(
        self, run_script, tmp_path, fixtures_dir
    ):
        """The No-review project's :SKIP_REVIEW: → --skip-review flag."""
        _build_tasks_tree(tmp_path, fixtures_dir)
        gh_dir = _install_gh_stub(tmp_path, _GH_STUB_OK)
        result = run_script(
            "cloude-promote", "--select", "3",
            env=_dry_run_env(tmp_path, gh_dir),
        )
        assert result.returncode == 0, result.stderr
        argv = _argv_to_dict(result.stdout)
        assert argv.get("skip-review") is True

    def test_adopt_mode_assembles_pr_flags(
        self, run_script, tmp_path, fixtures_dir
    ):
        _build_tasks_tree(tmp_path, fixtures_dir)
        gh_dir = _install_gh_stub(tmp_path, _GH_STUB_OK)
        result = run_script(
            "cloude-promote", "--select", "2",
            env=_dry_run_env(tmp_path, gh_dir),
        )
        assert result.returncode == 0, result.stderr
        argv = _argv_to_dict(result.stdout)
        assert argv["mode"] == "adopt"
        assert argv["head-ref"] == "feature/x"
        assert argv["base-ref"] == "master"
        assert argv["pr-url"] == "https://github.com/example/example/pull/99"
        assert argv["pr-number"] == "99"
        # Adopt-mode tasks don't take a --default-branch.
        assert "default-branch" not in argv


class TestPromoteFailureModes:
    def test_missing_select_exits_30(
        self, run_script, tmp_path, fixtures_dir
    ):
        _build_tasks_tree(tmp_path, fixtures_dir)
        gh_dir = _install_gh_stub(tmp_path, _GH_STUB_OK)
        result = run_script(
            "cloude-promote",
            env=_dry_run_env(tmp_path, gh_dir),
        )
        assert result.returncode == 30
        assert "--select" in result.stderr

    def test_out_of_range_select_exits_40(
        self, run_script, tmp_path, fixtures_dir
    ):
        _build_tasks_tree(tmp_path, fixtures_dir)
        gh_dir = _install_gh_stub(tmp_path, _GH_STUB_OK)
        result = run_script(
            "cloude-promote", "--select", "999",
            env=_dry_run_env(tmp_path, gh_dir),
        )
        assert result.returncode == 40
        assert "out of range" in result.stderr

    def test_empty_slug_exits_41(
        self, run_script, tmp_path, fixtures_dir
    ):
        """Heading with no alphanumeric chars and no :SLUG: → exit 41."""
        tasks = _build_tasks_tree(tmp_path, fixtures_dir)
        (tasks / "staging.org").write_text(
            "* Personal\n"
            "  :PROPERTIES:\n"
            "  :SLUG: personal\n"
            "  :END:\n"
            "** Project\n"
            "   :PROPERTIES:\n"
            "   :REPO: https://github.com/example/example\n"
            "   :END:\n"
            "*** !!! @@@ ###\n"
        )
        gh_dir = _install_gh_stub(tmp_path, _GH_STUB_OK)
        result = run_script(
            "cloude-promote", "--select", "1",
            env=_dry_run_env(tmp_path, gh_dir),
        )
        assert result.returncode == 41
        assert "slug is empty" in result.stderr

    def test_gh_failure_exits_42(
        self, run_script, tmp_path, fixtures_dir
    ):
        _build_tasks_tree(tmp_path, fixtures_dir)
        gh_dir = _install_gh_stub(
            tmp_path, "echo 'gh: not authenticated' >&2; exit 4"
        )
        result = run_script(
            "cloude-promote", "--select", "1",
            env=_dry_run_env(tmp_path, gh_dir),
        )
        assert result.returncode == 42

    def test_adopt_pr_not_open_exits_43(
        self, run_script, tmp_path, fixtures_dir
    ):
        _build_tasks_tree(tmp_path, fixtures_dir)
        gh_dir = _install_gh_stub(
            tmp_path,
            'echo \'{"number":99,"state":"CLOSED","headRefName":"x","baseRefName":"master",'
            '"isCrossRepository":false,'
            '"headRepositoryOwner":{"login":"example"},'
            '"headRepository":{"name":"example"},"url":"x"}\'',
        )
        result = run_script(
            "cloude-promote", "--select", "2",
            env=_dry_run_env(tmp_path, gh_dir),
        )
        assert result.returncode == 43
        assert "not OPEN" in result.stderr

    def test_adopt_pr_cross_repo_exits_43(
        self, run_script, tmp_path, fixtures_dir
    ):
        _build_tasks_tree(tmp_path, fixtures_dir)
        gh_dir = _install_gh_stub(
            tmp_path,
            'echo \'{"number":99,"state":"OPEN","headRefName":"x","baseRefName":"master",'
            '"isCrossRepository":true,'
            '"headRepositoryOwner":{"login":"forker"},'
            '"headRepository":{"name":"example"},"url":"x"}\'',
        )
        result = run_script(
            "cloude-promote", "--select", "2",
            env=_dry_run_env(tmp_path, gh_dir),
        )
        assert result.returncode == 43
        assert "cross-repository" in result.stderr

    def test_adopt_pr_repo_mismatch_exits_43(
        self, run_script, tmp_path, fixtures_dir
    ):
        _build_tasks_tree(tmp_path, fixtures_dir)
        gh_dir = _install_gh_stub(
            tmp_path,
            'echo \'{"number":99,"state":"OPEN","headRefName":"x","baseRefName":"master",'
            '"isCrossRepository":false,'
            '"headRepositoryOwner":{"login":"different"},'
            '"headRepository":{"name":"other"},"url":"x"}\'',
        )
        result = run_script(
            "cloude-promote", "--select", "2",
            env=_dry_run_env(tmp_path, gh_dir),
        )
        assert result.returncode == 43
        assert "does not" in result.stderr
