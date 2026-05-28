"""Tests for ``bin/cloude-render-task-file``.

Subprocess tests against a tiny fixture template. The renderer is a
thin CLI wrapper around `cloude_org.render_task_from_template` (which
has its own deep coverage in ``test_cloude_org.py``); these tests only
verify the CLI surface — flag plumbing, file-vs-stdout output, exit
codes — not the rendering rules themselves.
"""

from __future__ import annotations

from pathlib import Path


def _write_template(tmp_path: Path) -> Path:
    """Drop a minimal TEMPLATE.org fixture into ``tmp_path``.

    Mirrors the live ``tasks/TEMPLATE.org`` placeholders the helper
    fills in (heading, title, properties, log section).
    """
    tmpl = tmp_path / "TEMPLATE.org"
    tmpl.write_text(
        "#+TITLE: <task title>\n"
        "#+TODO: PLANNING(p!) ITERATING(i!) REVIEW(r!) MERGING(m!) | "
        "COMPLETE(c!) DROPPED(x@)\n"
        "#+TODO: PENDING(P!) UNSATISFIABLE(U!) | PASS(D!)\n"
        "#+STARTUP: overview logdrawer\n"
        "\n"
        "* PLANNING <task title>                                               :user:\n"
        "  :PROPERTIES:\n"
        "  :ID:       <YYYY-MM-DD-slug>\n"
        "  :REPO:     https://github.com/<org>/<repo>\n"
        "  :BRANCH:\n"
        "  :WORKTREE:\n"
        "  :PR:\n"
        "  :AGENT:\n"
        "  :END:\n"
        "\n"
        "** Notes\n"
        "\n"
        "** Log\n"
    )
    return tmpl


class TestRenderTaskFile:
    def test_writes_to_out_path(self, run_script, tmp_path):
        tmpl = _write_template(tmp_path)
        out = tmp_path / "task.org"
        result = run_script(
            "cloude-render-task-file",
            "--template", str(tmpl),
            "--todo", "PLANNING",
            "--heading", "Sample idea",
            "--task-id", "2026-05-28-sample",
            "--repo-url", "https://github.com/example/repo",
            "--branch", "cloude/sample",
            "--worktree", "/tmp/wt",
            "--out", str(out),
        )
        assert result.returncode == 0, result.stderr
        body = out.read_text()
        assert "#+TITLE: Sample idea" in body
        assert "* PLANNING Sample idea" in body
        assert ":ID:       2026-05-28-sample" in body
        assert ":REPO:     https://github.com/example/repo" in body
        assert ":BRANCH:cloude/sample" in body
        assert ":WORKTREE:/tmp/wt" in body

    def test_writes_to_stdout_with_dash(self, run_script, tmp_path):
        tmpl = _write_template(tmp_path)
        result = run_script(
            "cloude-render-task-file",
            "--template", str(tmpl),
            "--todo", "PLANNING",
            "--heading", "Sample idea",
            "--task-id", "2026-05-28-sample",
            "--repo-url", "https://github.com/example/repo",
            "--branch", "cloude/sample",
            "--worktree", "/tmp/wt",
            "--out", "-",
        )
        assert result.returncode == 0, result.stderr
        assert "#+TITLE: Sample idea" in result.stdout

    def test_skip_review_inserts_drawer_property(self, run_script, tmp_path):
        tmpl = _write_template(tmp_path)
        out = tmp_path / "task.org"
        result = run_script(
            "cloude-render-task-file",
            "--template", str(tmpl),
            "--todo", "PLANNING",
            "--heading", "Sample",
            "--task-id", "2026-05-28-sample",
            "--repo-url", "https://github.com/example/repo",
            "--branch", "cloude/sample",
            "--worktree", "/tmp/wt",
            "--skip-review",
            "--out", str(out),
        )
        assert result.returncode == 0, result.stderr
        assert ":SKIP_REVIEW:  t" in out.read_text()

    def test_companion_and_adopted_propagate(self, run_script, tmp_path):
        tmpl = _write_template(tmp_path)
        out = tmp_path / "task.org"
        result = run_script(
            "cloude-render-task-file",
            "--template", str(tmpl),
            "--todo", "ITERATING",
            "--heading", "Sample",
            "--task-id", "2026-05-28-sample",
            "--repo-url", "https://github.com/example/repo",
            "--branch", "feat/x",
            "--worktree", "/tmp/wt",
            "--adopted",
            "--companion", "2026-05-28-sibling",
            "--out", str(out),
        )
        assert result.returncode == 0, result.stderr
        body = out.read_text()
        assert ":ADOPTED:  t" in body
        assert ":COMPANION: 2026-05-28-sibling" in body

    def test_template_missing_exits_2(self, run_script, tmp_path):
        out = tmp_path / "task.org"
        result = run_script(
            "cloude-render-task-file",
            "--template", str(tmp_path / "does-not-exist.org"),
            "--todo", "PLANNING",
            "--heading", "x",
            "--task-id", "x",
            "--repo-url", "https://github.com/a/b",
            "--branch", "x",
            "--worktree", "/tmp/wt",
            "--out", str(out),
        )
        assert result.returncode == 2
        assert "template not found" in result.stderr

    def test_missing_required_flag_exits_30(self, run_script, tmp_path):
        result = run_script(
            "cloude-render-task-file",
            "--template", str(tmp_path / "T.org"),
            "--todo", "PLANNING",
            # missing --heading, etc.
            "--out", "-",
        )
        assert result.returncode == 30
