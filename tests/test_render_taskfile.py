"""Tests for bin/cloude-render-taskfile — active task .org generation.

This is the task-file generation step `/promote` runs. The /promote
skill (an LLM) chooses the heading, slug and repo and invokes the
script; these tests mock that by passing the arguments directly and
asserting the rendered file. The starting TODO keyword comes from the
active workflow definition, not the test.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RENDER = ROOT / "bin" / "cloude-render-taskfile"
TEMPLATE = ROOT / "tasks" / "TEMPLATE.org"


def render(tmp_path: Path, *args: str) -> str:
    dest = tmp_path / "task.org"
    result = subprocess.run(
        [
            sys.executable,
            str(RENDER),
            "--template",
            str(TEMPLATE),
            "--dest",
            str(dest),
            *args,
        ],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert result.returncode == 0, result.stderr
    return dest.read_text()


STANDARD = (
    "--mode",
    "standard",
    "--heading",
    "Add a widget",
    "--task-id",
    "2026-05-18-add-a-widget",
    "--repo-url",
    "https://github.com/org/repo",
    "--branch",
    "cloude/add-a-widget",
    "--worktree",
    "/wt/add-a-widget",
    "--pr-url",
    "https://github.com/org/repo/pull/5",
)


def test_standard_task_file(tmp_path):
    text = render(tmp_path, *STANDARD)
    assert text.startswith("#+TITLE: Add a widget\n")
    # The #+TODO: line is sourced from the active workflow.
    assert "#+TODO: PLANNING(p!) ITERATING(i!)" in text
    # Standard mode starts in the workflow's standard promote state.
    assert "* PLANNING Add a widget" in text
    assert ":REPO:     https://github.com/org/repo" in text
    assert ":BRANCH:cloude/add-a-widget" in text
    assert ":PR:https://github.com/org/repo/pull/5" in text
    assert ":ID:       2026-05-18-add-a-widget" in text
    # Standard mode adds neither :ADOPTED: nor :SKIP_REVIEW:.
    assert ":ADOPTED:" not in text
    assert ":SKIP_REVIEW:" not in text


def test_standard_heading_keeps_the_user_tag(tmp_path):
    text = render(tmp_path, *STANDARD)
    heading = next(ln for ln in text.splitlines() if ln.startswith("* "))
    assert heading.startswith("* PLANNING Add a widget")
    assert heading.endswith(":user:")


def test_skip_review_task_file(tmp_path):
    text = render(tmp_path, *STANDARD, "--skip-review")
    assert ":SKIP_REVIEW:  t" in text


def test_adopt_task_file(tmp_path):
    text = render(
        tmp_path,
        "--mode",
        "adopt",
        "--heading",
        "Existing PR title",
        "--task-id",
        "2026-05-18-existing-pr",
        "--repo-url",
        "https://github.com/org/repo",
        "--branch",
        "feature/x",
        "--worktree",
        "/wt/existing-pr",
        "--pr-url",
        "https://github.com/org/repo/pull/9",
        "--adopted",
        "--notes-prelude",
        "Adopted from PR https://github.com/org/repo/pull/9",
    )
    # Adopt mode starts in the workflow's adopt promote state.
    assert "* ITERATING Existing PR title" in text
    assert ":ADOPTED:  t" in text
    assert "Adopted from PR https://github.com/org/repo/pull/9" in text


def test_missing_template_is_an_error(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(RENDER),
            "--template",
            str(tmp_path / "nope.org"),
            "--dest",
            str(tmp_path / "out.org"),
            "--mode",
            "standard",
            "--heading",
            "X",
            "--task-id",
            "id",
            "--repo-url",
            "url",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "template not found" in result.stderr
