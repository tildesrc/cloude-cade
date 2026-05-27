"""End-to-end tests for ``bin/cloude-set-staging-slug``.

The script writes the chosen slug into the idea's :PROPERTIES: drawer
in ``tasks/staging.org``. Each test sets up a minimal staging.org under
``tmp_path``, spawns the helper via ``run_script`` (so the CLI argv
parsing, exit codes, and atomic-rename write path are all exercised),
and asserts on stdout, exit code, and on-disk side effects.
"""

from __future__ import annotations

from pathlib import Path


def _write_staging(tmp_path: Path, body: str) -> Path:
    tasks = tmp_path / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    staging = tasks / "staging.org"
    staging.write_text(body)
    return staging


BASE_STAGING = (
    "#+TITLE: Staging\n"
    "\n"
    "* Example project\n"
    "  :PROPERTIES:\n"
    "  :REPO: https://github.com/example/example\n"
    "  :END:\n"
    "** First idea\n"
    "** Second idea\n"
    "   :PROPERTIES:\n"
    "   :ADOPT: https://github.com/example/example/pull/99\n"
    "   :END:\n"
    "** Third idea\n"
    "   :PROPERTIES:\n"
    "   :SLUG: third-idea-slug\n"
    "   :END:\n"
)


class TestSetStagingSlug:
    def test_inserts_drawer_for_bare_heading(self, run_script, tmp_path):
        staging = _write_staging(tmp_path, BASE_STAGING)
        result = run_script(
            "cloude-set-staging-slug",
            "First idea", "first-idea",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0, result.stderr
        text = staging.read_text()
        assert (
            "** First idea\n"
            "   :PROPERTIES:\n"
            "   :SLUG: first-idea\n"
            "   :END:\n"
        ) in text
        assert "set :SLUG: first-idea" in result.stdout

    def test_inserts_into_existing_drawer(self, run_script, tmp_path):
        staging = _write_staging(tmp_path, BASE_STAGING)
        result = run_script(
            "cloude-set-staging-slug",
            "Second idea", "second-idea",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0, result.stderr
        text = staging.read_text()
        assert (
            "** Second idea\n"
            "   :PROPERTIES:\n"
            "   :ADOPT: https://github.com/example/example/pull/99\n"
            "   :SLUG: second-idea\n"
            "   :END:\n"
        ) in text

    def test_clobber_exits_3(self, run_script, tmp_path):
        staging = _write_staging(tmp_path, BASE_STAGING)
        result = run_script(
            "cloude-set-staging-slug",
            "Third idea", "different-slug",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 3
        # Original slug untouched.
        assert ":SLUG: third-idea-slug" in staging.read_text()
        assert "different-slug" in result.stderr

    def test_noop_when_slug_already_matches(self, run_script, tmp_path):
        staging = _write_staging(tmp_path, BASE_STAGING)
        before = staging.read_text()
        result = run_script(
            "cloude-set-staging-slug",
            "Third idea", "third-idea-slug",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0
        assert result.stdout == ""
        assert staging.read_text() == before

    def test_missing_heading_exits_2(self, run_script, tmp_path):
        staging = _write_staging(tmp_path, BASE_STAGING)
        result = run_script(
            "cloude-set-staging-slug",
            "Does not exist", "no-such",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 2
        assert "heading not found" in result.stderr
        # File untouched.
        assert staging.read_text() == BASE_STAGING

    def test_malformed_slug_exits_30(self, run_script, tmp_path):
        staging = _write_staging(tmp_path, BASE_STAGING)
        result = run_script(
            "cloude-set-staging-slug",
            "First idea", "BAD_SLUG",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 30
        assert "malformed slug" in result.stderr
        assert staging.read_text() == BASE_STAGING

    def test_missing_staging_file_exits_2(self, run_script, tmp_path):
        # No tasks/staging.org under tmp_path.
        (tmp_path / "tasks").mkdir()
        result = run_script(
            "cloude-set-staging-slug",
            "Anything", "any-slug",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 2
        assert "no staging file" in result.stderr

    def test_bad_argv_exits_2(self, run_script, tmp_path):
        _write_staging(tmp_path, BASE_STAGING)
        result = run_script(
            "cloude-set-staging-slug",
            "only-one-arg",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 2
        assert "usage:" in result.stderr

    def test_empty_existing_slug_is_replaced(self, run_script, tmp_path):
        body = (
            "#+TITLE: Staging\n"
            "* Example project\n"
            "  :PROPERTIES:\n"
            "  :REPO: https://github.com/example/example\n"
            "  :END:\n"
            "** Pending idea\n"
            "   :PROPERTIES:\n"
            "   :SLUG:\n"
            "   :END:\n"
        )
        staging = _write_staging(tmp_path, body)
        result = run_script(
            "cloude-set-staging-slug",
            "Pending idea", "pending-idea",
            env={"CLOUDE_ROOT": str(tmp_path)},
        )
        assert result.returncode == 0, result.stderr
        text = staging.read_text()
        assert ":SLUG: pending-idea\n" in text
        assert text.count(":SLUG:") == 1
