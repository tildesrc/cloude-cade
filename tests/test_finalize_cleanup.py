"""Regression tests for ``bin/cloude-finalize-cleanup``.

The script is bash with a top-level body that requires real task
metadata, git, gh, docker, and tmux to run end-to-end. Rather than
mock all of that, these tests extract individual bash functions from
the script source and exercise them directly under
``bash -c 'set -euo pipefail; ...'`` — the same prologue the script
itself uses.
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


# ---------------------------------------------------------------------------
# worktree_registered: short-circuit detection for already-cleaned-up
# worktrees. Returns success iff $SOURCE_CLONE has a 'git worktree list'
# entry for $WORKTREE. Used by step 4's Tier 0 absent-check.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def worktree_registered_fn(bin_dir: Path) -> str:
    source = (bin_dir / "cloude-finalize-cleanup").read_text()
    return _extract_function(source, "worktree_registered")


def _run_worktree_registered(
    fn_src: str, source_clone: Path, worktree: Path
) -> subprocess.CompletedProcess:
    """Run ``worktree_registered`` against the given paths.

    Prints ``REGISTERED`` or ``ABSENT`` so tests can assert on stdout
    rather than worry about ``set -e`` propagation from a function that
    intentionally returns 1.
    """
    script = (
        "set -uo pipefail\n"
        f"{fn_src}\n"
        f'SOURCE_CLONE={subprocess.list2cmdline([str(source_clone)])}\n'
        f'WORKTREE={subprocess.list2cmdline([str(worktree)])}\n'
        "if worktree_registered; then echo REGISTERED; else echo ABSENT; fi\n"
    )
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
    )


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def source_clone(tmp_path: Path) -> Path:
    """A real git repo with one initial commit on the default branch.

    Configures a local identity *before* the first commit — CI runners
    typically have no global ``user.email`` / ``user.name`` set, so a
    bare ``git commit`` there would fail with exit 128.
    """
    clone = tmp_path / "source-clone"
    clone.mkdir()
    _git(clone, "init", "-q", "-b", "main")
    _git(clone, "config", "user.email", "test@example.invalid")
    _git(clone, "config", "user.name", "Test")
    _git(clone, "commit", "-q", "--allow-empty", "-m", "initial")
    return clone


class TestWorktreeRegistered:
    def test_registered_returns_success(
        self,
        worktree_registered_fn: str,
        source_clone: Path,
        tmp_path: Path,
    ) -> None:
        """Happy path: a worktree added via ``git worktree add`` is
        registered, so the helper returns success and the test driver
        prints ``REGISTERED``.
        """
        wt = tmp_path / "wt"
        _git(source_clone, "worktree", "add", "-q", str(wt), "-b", "feature")

        result = _run_worktree_registered(
            worktree_registered_fn, source_clone, wt
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "REGISTERED"

    def test_unregistered_returns_failure(
        self,
        worktree_registered_fn: str,
        source_clone: Path,
        tmp_path: Path,
    ) -> None:
        """A path that ``git worktree list`` doesn't know about — the
        fully-absent case the Tier-0 short-circuit needs to detect.
        """
        result = _run_worktree_registered(
            worktree_registered_fn,
            source_clone,
            tmp_path / "never-added",
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "ABSENT"

    def test_missing_source_clone_returns_failure(
        self,
        worktree_registered_fn: str,
        tmp_path: Path,
    ) -> None:
        """``[[ -d "$SOURCE_CLONE" ]] || return 1`` guard: if the source
        clone itself is gone we can't query worktrees, so the helper
        returns failure cleanly (no noisy git error on stderr).
        """
        result = _run_worktree_registered(
            worktree_registered_fn,
            tmp_path / "no-such-clone",
            tmp_path / "no-such-worktree",
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "ABSENT"

    def test_dir_gone_but_still_registered(
        self,
        worktree_registered_fn: str,
        source_clone: Path,
        tmp_path: Path,
    ) -> None:
        """Mid-state: worktree directory removed externally, but
        ``.git/worktrees/<slug>`` bookkeeping still present. The
        function should still report REGISTERED — the script's Tier-0
        short-circuit only fires when *both* the dir AND the
        bookkeeping are gone, since ``git worktree remove`` already
        prunes the bookkeeping in this case.
        """
        wt = tmp_path / "wt-stale"
        _git(source_clone, "worktree", "add", "-q", str(wt), "-b", "feat2")
        # Wipe the directory but leave the bookkeeping behind.
        subprocess.run(["rm", "-rf", str(wt)], check=True)

        result = _run_worktree_registered(
            worktree_registered_fn, source_clone, wt
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "REGISTERED"


# ---------------------------------------------------------------------------
# probe_pr_state: splits "PR accessible, state=X" from "gh exit nonzero".
# Tested against fake gh binaries on $PATH so we don't depend on a real
# repo / network / auth.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def probe_pr_state_fn(bin_dir: Path) -> str:
    source = (bin_dir / "cloude-finalize-cleanup").read_text()
    return _extract_function(source, "probe_pr_state")


def _fake_gh(dir_: Path, *, stdout: str, exit_code: int) -> Path:
    """Write a fake ``gh`` script to ``dir_/gh`` and return its dir.

    The returned path is meant to be prepended to ``$PATH`` so calls to
    ``gh`` in the test resolve here instead of the system binary.
    """
    gh = dir_ / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        f"printf %s {subprocess.list2cmdline([stdout])}\n"
        f"exit {exit_code}\n"
    )
    gh.chmod(0o755)
    return dir_


def _run_probe_pr_state(
    fn_src: str, fake_path_dir: Path
) -> subprocess.CompletedProcess:
    """Run ``probe_pr_state`` with the given fake-gh dir at the front of
    ``$PATH``, then echo the resulting pr_accessible / pr_state globals.
    """
    script = (
        "set -uo pipefail\n"
        f"{fn_src}\n"
        'PR=https://example.invalid/pr/1\n'
        "pr_accessible=unset\n"
        'pr_state=unset\n'
        "probe_pr_state\n"
        'echo "accessible=$pr_accessible state=$pr_state"\n'
    )
    env = os.environ.copy()
    env["PATH"] = f"{fake_path_dir}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
    )


class TestProbePrState:
    def test_accessible_with_state(
        self, probe_pr_state_fn: str, tmp_path: Path
    ) -> None:
        """gh succeeds and prints the state: pr_accessible=true,
        pr_state captures the value (MERGED in this case)."""
        fake = _fake_gh(tmp_path, stdout="MERGED", exit_code=0)
        result = _run_probe_pr_state(probe_pr_state_fn, fake)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "accessible=true state=MERGED"

    def test_accessible_open(
        self, probe_pr_state_fn: str, tmp_path: Path
    ) -> None:
        fake = _fake_gh(tmp_path, stdout="OPEN", exit_code=0)
        result = _run_probe_pr_state(probe_pr_state_fn, fake)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "accessible=true state=OPEN"

    def test_not_accessible(
        self, probe_pr_state_fn: str, tmp_path: Path
    ) -> None:
        """gh exits nonzero (repo deleted / auth lost / network):
        pr_accessible=false, pr_state cleared. The 'if assign; then'
        shape inside the function must keep set -e from tripping —
        if this regresses the script won't even reach the echo.
        """
        fake = _fake_gh(
            tmp_path, stdout="some error on stdout\n", exit_code=1
        )
        result = _run_probe_pr_state(probe_pr_state_fn, fake)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "accessible=false state="
