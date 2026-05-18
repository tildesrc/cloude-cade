"""Tests for bin/cloude-workflow — the query CLI the skills call."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "bin" / "cloude-workflow"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


def test_next_state():
    result = run("next-state", "ITERATING")
    assert result.returncode == 0
    assert result.stdout.strip() == "REVIEW"


def test_next_state_with_skip_review():
    result = run("next-state", "ITERATING", "--skip-review")
    assert result.returncode == 0
    assert result.stdout.strip() == "MERGING"


def test_next_state_of_terminal_exits_3():
    result = run("next-state", "COMPLETE")
    assert result.returncode == 3
    assert result.stdout.strip() == ""


def test_default_tag():
    assert run("default-tag", "MERGING").stdout.strip() == "agent"
    assert run("default-tag", "REVIEW").stdout.strip() == "blocked"


def test_forward_driver():
    assert run("forward-driver", "MERGING").stdout.strip() == "agent"
    assert run("forward-driver", "ITERATING").stdout.strip() == "user"


def test_role():
    assert run("role", "iterate").stdout.strip() == "ITERATING"
    assert run("role", "drop").stdout.strip() == "DROPPED"


def test_dod_lists_flattened_bullets():
    result = run("dod", "ITERATING")
    assert result.returncode == 0
    lines = result.stdout.splitlines()
    assert "The plan is implemented in code." in lines
    # Every bullet is a single line (un-wrapped).
    assert all(line.strip() for line in lines)


def test_info_emits_shell_safe_pairs():
    result = run("info")
    assert result.returncode == 0
    pairs = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert pairs["WORKFLOW"] == "default"
    assert pairs["AUTO_ADVANCE_FROM"] == "PLANNING"


def test_unknown_state_is_an_error():
    result = run("next-state", "GHOST")
    assert result.returncode == 2
    assert "unknown state" in result.stderr


def test_unknown_command_is_an_error():
    result = run("frobnicate")
    assert result.returncode == 2
