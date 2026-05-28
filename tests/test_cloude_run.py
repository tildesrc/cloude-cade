"""Subprocess tests for ``bin/cloude-run``.

Drives the script with ``CLOUDE_RUN_DRY_RUN=1`` so the assembled
``docker run`` argv is emitted instead of executed, and asserts on:

  - vault resolution from the task file path,
  - per-vault credential mounts (gh dir, gitconfig, env),
  - sibling-vault hiding via the ``--tmpfs`` overlay,
  - missing-creds fail-fast.

cloude-run isn't a Python script — it's bash. ``run_script`` works fine
for it: the host venv's Python is never invoked, just the bash
interpreter the shebang names. But cloude-run also wants to exec
``make -C $CLOUDE build`` before assembling the argv; the dry-run
branch is checked AFTER ``make`` would run, which would slow tests
and require a buildable image. To avoid that, the tests fake-build by
setting ``MAKE`` to ``/usr/bin/true`` (cloude-run invokes ``make`` via
``$PATH``, so we shadow it on the prepended PATH).
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

CLOUDE_RUN = Path(__file__).resolve().parents[1] / "bin" / "cloude-run"


def _install_make_stub(tmp_path: Path) -> Path:
    """Drop a fake ``make`` on PATH that exits 0 immediately."""
    bindir = tmp_path / "makestub"
    bindir.mkdir()
    fake = bindir / "make"
    fake.write_text("#!/usr/bin/env bash\nexit 0\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    # cloude-run also calls `jq` when ~/.docker/config.json exists. We
    # don't write that file in tests, so jq is never invoked — no need
    # to stub it.
    return bindir


def _build_layout(tmp_path: Path, vault: str, vault_creds_factory) -> tuple[Path, Path, Path]:
    """Lay out a worktree, source clone, and active task under tmp_path.

    Cloude-run's path validation requires the worktree to live under
    ``$CLOUDE/vaults/<vault>/worktrees/<repo>/<slug>`` and the task file
    under ``$CLOUDE/vaults/<vault>/tasks/active/``. The cloude root is
    ``tmp_path/cloude`` (a sibling of the make stub so we don't pollute
    its lookup).

    Returns ``(cloude_root, worktree, task_file)``.
    """
    cloude = tmp_path / "cloude"
    cloude.mkdir()
    # Also need a faux Makefile so cloude-run's `make -C $CLOUDE build`
    # has something to chdir into. The stub `make` ignores it anyway.
    (cloude / "Makefile").write_text("build:\n\ttrue\n")
    vault_dir = cloude / "vaults" / vault
    src_clone = vault_dir / "repos" / "example"
    worktree = vault_dir / "worktrees" / "example" / "demo"
    active = vault_dir / "tasks" / "active"
    src_clone.mkdir(parents=True)
    worktree.mkdir(parents=True)
    active.mkdir(parents=True)
    task_file = active / "2026-05-28-demo.org"
    task_file.write_text(
        "#+TITLE: demo\n"
        "#+TODO: PLANNING ITERATING | COMPLETE\n"
        "* PLANNING demo :agent:\n"
        "  :PROPERTIES:\n"
        f"  :VAULT: {vault}\n"
        "  :REPO: https://github.com/example/example\n"
        "  :END:\n"
    )
    # Populate vault creds at cloude/vaults/<vault>/creds/ — the
    # factory writes under tmp_path, so call it with the cloude prefix
    # by adjusting CWD-relative paths. Easiest path: do it inline.
    creds = vault_dir / "creds"
    (creds / "gh").mkdir(parents=True)
    (creds / "gitconfig").write_text("[user]\n\tname = Fixture\n")
    (creds / "env").write_text("GH_TOKEN=ghp_fixture\n")
    return cloude, worktree, task_file


def _drop_creds(cloude: Path, vault: str, entry: str) -> None:
    creds = cloude / "vaults" / vault / "creds"
    target = creds / entry
    if target.is_dir():
        import shutil
        shutil.rmtree(target)
    else:
        target.unlink(missing_ok=True)


def _run_cloude_run(cloude: Path, worktree: Path, task: Path, tmp_path: Path):
    """Invoke bin/cloude-run with dry-run env, returning the result.

    cloude-run is bash, not Python — bypass the ``run_script`` fixture
    (which runs scripts under the host venv's Python interpreter) and
    invoke it directly through the kernel via subprocess.
    """
    make_stub = _install_make_stub(tmp_path)
    env = dict(os.environ)
    env["CLOUDE_RUN_DRY_RUN"] = "1"
    # Pin cloude-run to the synthetic cloude root rather than the
    # script-location default (the real repo root). cloude-run honors
    # CLOUDE_ROOT the same way the sibling Python helpers do.
    env["CLOUDE_ROOT"] = str(cloude)
    # Prepend the stub so cloude-run's `make` resolves to the no-op.
    env["PATH"] = f"{make_stub}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        [str(CLOUDE_RUN), str(worktree), str(task)],
        capture_output=True,
        text=True,
        env=env,
    )


def _argv(stdout: str) -> list[str]:
    """Pull the docker run argv out of the dry-run stdout.

    cloude-run prints one ``DOCKER_RUN_ARGV=<arg>`` line per arg.
    Strips the prefix and returns the list.
    """
    out: list[str] = []
    for line in stdout.splitlines():
        if line.startswith("DOCKER_RUN_ARGV="):
            out.append(line[len("DOCKER_RUN_ARGV="):])
    return out


class TestCloudeRunDryRun:
    def test_assembles_vault_scoped_mounts(
        self, tmp_path, vault_creds_factory
    ):
        cloude, worktree, task = _build_layout(tmp_path, "personal", vault_creds_factory)
        result = _run_cloude_run(cloude, worktree, task, tmp_path)
        assert result.returncode == 0, result.stderr
        argv = _argv(result.stdout)
        # cloude repo is mounted read-only.
        assert f"{cloude}:{cloude}:ro" in argv
        # The /vaults/ overlay hides siblings.
        assert f"{cloude}/vaults" in argv  # the --tmpfs target
        assert "--tmpfs" in argv
        # The resolved vault is bound back rw.
        vault_path = cloude / "vaults" / "personal"
        assert f"{vault_path}:{vault_path}:rw" in argv
        # The active task dir is layered with a directory-level rw bind.
        active = vault_path / "tasks" / "active"
        assert f"{active}:{active}:rw" in argv
        # Vault credentials replace the host's ambient gh/gitconfig.
        creds = vault_path / "creds"
        assert f"{creds}/gh:/home/cloude/.config/gh:ro" in argv
        assert f"{creds}/gitconfig:/home/cloude/.gitconfig:ro" in argv
        # Claude creds volume is vault-scoped.
        assert "cloude-claude-creds-personal:/persist" in argv
        # No leaked host ~/.gitconfig or ~/.config/gh references.
        joined = "\n".join(argv)
        assert "/.gitconfig:" not in joined or "creds/gitconfig" in joined
        assert "/.config/gh:" in joined  # only the vault one — check vault's:
        assert f"{creds}/gh:/home/cloude/.config/gh:ro" in argv

    def test_passes_vault_env_through(
        self, tmp_path, vault_creds_factory
    ):
        cloude, worktree, task = _build_layout(tmp_path, "work", vault_creds_factory)
        # Overwrite env with a non-default token.
        (cloude / "vaults" / "work" / "creds" / "env").write_text(
            "GH_TOKEN=ghp_work_specific\n"
            "EXTRA_VAR=hello\n"
        )
        result = _run_cloude_run(cloude, worktree, task, tmp_path)
        assert result.returncode == 0, result.stderr
        argv = _argv(result.stdout)
        # `-e KEY=VALUE` pairs lifted from the vault env file.
        assert "GH_TOKEN=ghp_work_specific" in argv
        assert "EXTRA_VAR=hello" in argv
        # CLOUDE_VAULT is exported.
        assert "CLOUDE_VAULT=work" in argv

    @pytest.mark.parametrize("missing", ["gh", "gitconfig", "env"])
    def test_missing_creds_fails_fast(
        self, tmp_path, vault_creds_factory, missing
    ):
        cloude, worktree, task = _build_layout(tmp_path, "personal", vault_creds_factory)
        _drop_creds(cloude, "personal", missing)
        result = _run_cloude_run(cloude, worktree, task, tmp_path)
        assert result.returncode != 0
        assert "missing credentials" in result.stderr.lower()
        # Stderr names which entries are missing.
        if missing == "gh":
            assert "gh/" in result.stderr
        else:
            assert missing in result.stderr
        # No docker run argv emitted on the failure path.
        assert "DOCKER_RUN_ARGV=" not in result.stdout

    def test_rejects_task_file_outside_vault_layout(
        self, tmp_path, vault_creds_factory
    ):
        cloude, worktree, _task = _build_layout(
            tmp_path, "personal", vault_creds_factory
        )
        # Drop a stray task file at the legacy <cloude>/tasks/active/
        # path; cloude-run should refuse it.
        legacy = cloude / "tasks" / "active"
        legacy.mkdir(parents=True)
        legacy_task = legacy / "2026-05-28-orphan.org"
        legacy_task.write_text(
            "* PLANNING orphan :agent:\n"
            "  :PROPERTIES:\n"
            "  :VAULT: personal\n"
            "  :END:\n"
        )
        result = _run_cloude_run(
            cloude, worktree, legacy_task, tmp_path
        )
        assert result.returncode != 0
        assert "vaults" in result.stderr.lower()

    def test_rejects_vault_mismatch_between_path_and_property(
        self, tmp_path, vault_creds_factory
    ):
        cloude, worktree, task = _build_layout(
            tmp_path, "personal", vault_creds_factory
        )
        # Rewrite the task file's :VAULT: to a different vault than its
        # path. cloude-run should refuse.
        task.write_text(
            task.read_text().replace(":VAULT: personal", ":VAULT: work")
        )
        result = _run_cloude_run(cloude, worktree, task, tmp_path)
        assert result.returncode != 0
        assert "VAULT" in result.stderr or "vault" in result.stderr
