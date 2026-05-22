"""Regression tests for ``bin/cloude-finalize-cleanup``.

The script is bash with a top-level body that requires real task
metadata, git, gh, docker, and tmux to run end-to-end. Rather than
mock all of that, these tests extract the ``foreign_owned_count``
bash function from the script source and exercise it directly under
``bash -c 'set -euo pipefail; ...'`` — the same prologue the script
itself uses.

The bug fixed here was that ``find`` exits nonzero on permission-
denied descents (e.g. root-owned subdirs from in-container DinD test
runs), which under ``set -euo pipefail`` propagated through the pipe
and aborted the calling ``foreign="$(foreign_owned_count)"`` before
``--force-root`` could be consulted. The fix wraps ``find`` with
``|| true`` so the pipeline can't abort the script.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest


def _extract_function(source: str, name: str) -> str:
    """Pull a single bash ``name() { ... }`` block out of a script.

    Anchored at the start of a line so it doesn't match the function's
    name appearing in comments or in command substitutions elsewhere.
    Relies on the closing ``}`` also being at column 0, which is the
    convention used throughout ``bin/``.
    """
    pattern = re.compile(
        rf"^{re.escape(name)}\(\) \{{\n.*?^\}}",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(source)
    if not match:
        raise AssertionError(f"could not locate {name}() in script source")
    return match.group(0)


@pytest.fixture(scope="module")
def foreign_owned_count_fn(bin_dir: Path) -> str:
    source = (bin_dir / "cloude-finalize-cleanup").read_text()
    return _extract_function(source, "foreign_owned_count")


def _run_fn(fn_src: str, worktree: Path) -> subprocess.CompletedProcess:
    """Run the extracted function under the same shell options the script uses."""
    script = (
        "set -euo pipefail\n"
        f"{fn_src}\n"
        f'WORKTREE={subprocess.list2cmdline([str(worktree)])}\n'
        "foreign_owned_count\n"
    )
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
    )


class TestForeignOwnedCount:
    def test_survives_permission_denied_descent(
        self, foreign_owned_count_fn: str, tmp_path: Path
    ) -> None:
        """The regression: an unreadable subdir made ``find`` exit 1,
        which under ``set -euo pipefail`` killed the calling script
        before it could decide whether to fall through to ``--force-root``.

        ``chmod 000`` on a subdir reproduces ``find``'s nonzero exit
        without needing a foreign owner or docker.
        """
        work = tmp_path / "work"
        work.mkdir()
        locked = work / "locked"
        locked.mkdir()
        # Also drop a regular file so 'find' has at least one entry to
        # print before the descent fails — this is closer to a real
        # worktree shape.
        (work / "regular.txt").write_text("hello")
        locked.chmod(0o000)
        try:
            result = _run_fn(foreign_owned_count_fn, work)
        finally:
            locked.chmod(stat.S_IRWXU)

        assert result.returncode == 0, (
            f"foreign_owned_count exited {result.returncode}; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        # Output must still parse as an integer even though find
        # partially failed.
        count = int(result.stdout.strip())
        assert count >= 0

    def test_clean_worktree_returns_zero(
        self, foreign_owned_count_fn: str, tmp_path: Path
    ) -> None:
        """Control case: a worktree we fully own returns 0 (no foreign
        files) and exits 0. Pins the happy-path output so a future
        regression in either direction (e.g. someone silencing exit by
        always returning 0) is caught.
        """
        work = tmp_path / "work"
        work.mkdir()
        (work / "a.txt").write_text("a")
        (work / "sub").mkdir()
        (work / "sub" / "b.txt").write_text("b")

        result = _run_fn(foreign_owned_count_fn, work)
        assert result.returncode == 0
        assert result.stdout.strip() == "0"

    def test_missing_worktree_returns_zero(
        self, foreign_owned_count_fn: str, tmp_path: Path
    ) -> None:
        """The function has an early ``[[ -d "$WORKTREE" ]] || echo 0``
        guard. Make sure that still fires (the fix is one line below).
        """
        result = _run_fn(foreign_owned_count_fn, tmp_path / "does-not-exist")
        assert result.returncode == 0
        assert result.stdout.strip() == "0"
