"""Shared fixtures and helpers for the cloude test suite.

Two layers of testing:

  - **Unit tests** import ``cloude_org`` (and, via ``import_script``,
    any of the no-extension polyglot helpers in ``bin/``) and call
    functions directly.
  - **End-to-end tests** spawn the helper as a subprocess via the
    ``run_script`` fixture, feeding stdin / args and asserting on
    stdout, stderr, exit code, and on-disk side effects.

Subprocess invocations use this repo's ``.venv-host/bin/python`` rather
than each script's shebang. Most scripts in ``bin/`` use either a
``uv run --script`` PEP-723 shebang (slow per-invocation resolve) or a
sh/Python polyglot that re-execs through ``bin/cloude-python``. Both
forms also run as plain Python under the host venv, so the tests pick
that path for speed and determinism.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import types
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# Make ``import cloude_org`` resolve for unit tests, and make ``bin/``
# importable for the no-extension scripts loaded via ``import_script``.
sys.path.insert(0, str(BIN_DIR))

from cloude_org import dod_marker_path  # noqa: E402
from cloude_stages import todo_directive  # noqa: E402

HOST_PYTHON = Path(
    os.environ.get("CLOUDE_HOST_PYTHON")
    or (REPO_ROOT / ".venv-host" / "bin" / "python")
)


# ---------------------------------------------------------------------------
# Path / interpreter fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def bin_dir() -> Path:
    return BIN_DIR


@pytest.fixture(scope="session")
def host_python() -> Path:
    """Path to the ``.venv-host`` interpreter.

    The Makefile's ``make test`` target depends on ``sync``, which
    builds this venv from ``pyproject.toml`` + ``uv.lock``. Running
    pytest directly without ``make sync`` first will fail this
    fixture — that's intentional, since the subprocess tests need
    ``orgparse`` and friends from the pinned venv.
    """
    if not HOST_PYTHON.is_file():
        pytest.skip(
            f"host venv missing at {HOST_PYTHON}; run `make sync` first"
        )
    return HOST_PYTHON


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------


@pytest.fixture
def run_script(host_python: Path, bin_dir: Path):
    """Return a callable that runs a ``bin/`` script under the host venv.

    Usage::

        result = run_script("cloude-task-set-state", str(task), "--tag", "user")
        assert result.returncode == 0

    Keyword args:

      - ``stdin``: string fed to the child's stdin.
      - ``env``: extra env vars merged onto ``os.environ``.
      - ``cwd``: working directory.
      - ``check``: if True, raise on non-zero exit (default False so
        tests can assert on the returncode).
    """

    def _run(
        script: str,
        *args: str,
        stdin: str | None = None,
        env: dict[str, str] | None = None,
        cwd: str | os.PathLike | None = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess:
        script_path = bin_dir / script
        merged_env = os.environ.copy()
        # Ensure the host venv's site-packages is what the child uses;
        # avoid leaking the test runner's own PYTHONPATH (which pins
        # ``bin/`` at index 0 so we can ``import cloude_org`` in-process)
        # into subprocesses where it would shadow the installed package.
        merged_env.pop("PYTHONPATH", None)
        if env:
            merged_env.update(env)
        return subprocess.run(
            [str(host_python), str(script_path), *args],
            input=stdin,
            capture_output=True,
            text=True,
            env=merged_env,
            cwd=cwd,
            check=check,
        )

    return _run


# ---------------------------------------------------------------------------
# import_script: load a no-extension polyglot script as a module
# ---------------------------------------------------------------------------


@pytest.fixture
def import_script(bin_dir: Path):
    """Load a ``bin/<name>`` script as an importable module.

    Useful when you want to unit-test a single helper function inside a
    no-extension polyglot script without spawning a subprocess. The
    sh/Python polyglot prologue at the top of those files parses as a
    no-op string literal under Python, so the rest of the module loads
    cleanly. The loaded module's ``__main__`` block is NOT executed
    (we use the standard ``loader.exec_module`` path).
    """

    loaded: dict[str, types.ModuleType] = {}

    def _import(name: str) -> types.ModuleType:
        if name in loaded:
            return loaded[name]
        path = bin_dir / name
        if not path.is_file():
            raise FileNotFoundError(path)
        # ``spec_from_file_location`` infers the loader from the file
        # extension; for our extensionless scripts we hand it a
        # SourceFileLoader explicitly. The module is registered in
        # ``sys.modules`` before ``exec_module`` because @dataclass
        # resolves annotations against ``sys.modules[cls.__module__]``.
        mod_name = f"_cloude_script_{name.replace('-', '_')}"
        loader = SourceFileLoader(mod_name, str(path))
        spec = importlib.util.spec_from_loader(mod_name, loader)
        assert spec is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        try:
            loader.exec_module(module)
        except BaseException:
            sys.modules.pop(mod_name, None)
            raise
        loaded[name] = module
        return module

    return _import


# ---------------------------------------------------------------------------
# Task-file fixture helpers
# ---------------------------------------------------------------------------


def render_task(
    *,
    todo: str = "PLANNING",
    title: str = "Test task",
    tag: str = "agent",
    properties: dict[str, str] | None = None,
    sections: str = "",
    log_entries: str | None = "default",
) -> str:
    """Render a task .org file body as a string.

    ``properties`` is merged on top of a small default set (ID + VAULT
    + REPO). The default ``VAULT`` is ``personal`` to match the
    ``task_file_factory`` directory layout.
    ``sections`` is dropped between the heading/properties block and the
    ``** Log`` heading verbatim — pass extra ``** Goal``, ``** Plan``
    etc. content here.

    ``log_entries`` controls the ``** Log`` body:
      - the sentinel ``"default"`` seeds a single PLANNING entry
        matching the canonical promote-time skeleton (PENDING DoD with
        three open boxes);
      - any other string is dropped in verbatim under ``** Log``;
      - ``None`` omits the ``** Log`` heading entirely (for the
        missing-log schema-error case).
    """

    props = {
        "ID": "fixture-task",
        "VAULT": "personal",
        "REPO": "https://github.com/example/example",
    }
    if properties:
        props.update(properties)
    props_block = "  :PROPERTIES:\n" + "".join(
        f"  :{k}: {v}\n" for k, v in props.items()
    ) + "  :END:\n"

    header = (
        "#+TITLE: " + title + "\n"
        + todo_directive() + "\n"
        "#+TODO: PENDING(P!) UNSATISFIABLE(U!) | PASS(D!)\n"
        "#+STARTUP: overview logdrawer\n\n"
    )
    heading = f"* {todo} {title} :{tag}:\n"

    body = header + heading + props_block + "\n" + sections
    if log_entries is None:
        return body

    if log_entries == "default":
        log_entries = (
            "*** [2026-01-01 Mon 10:00] PLANNING (via /promote)\n"
            "    :PROPERTIES:\n"
            "    :STAGE:       PLANNING\n"
            "    :ENTERED:     [2026-01-01 Mon 10:00]\n"
            "    :ENTERED_VIA: /promote\n"
            "    :END:\n"
            "**** Request\n"
            "**** Work\n"
            "**** [0/3] PENDING DoD\n"
            "     - [ ] The plan is written into the task's org file.\n"
            "     - [ ] The user has approved the plan.\n"
            "     - [ ] A draft PR has been created on GitHub.\n"
        )
    return body + "** Log\n" + log_entries


@pytest.fixture
def task_file_factory(tmp_path: Path):
    """Return a callable that writes a fixture task file under ``tmp_path``.

    The file lives at ``tmp_path/vaults/<vault>/tasks/active/<name>.org``
    so cloude-task-info's ``cloude_root = path.parents[4]`` heuristic
    resolves to ``tmp_path``. Default vault is ``personal`` to match
    ``render_task``'s default ``:VAULT:`` property. Pass ``vault=...``
    to override; the rendered file's ``:VAULT:`` is updated to match.
    """

    created: list[Path] = []

    def _make(
        name: str = "2026-01-01-fixture-task.org",
        *,
        vault: str = "personal",
        **kwargs,
    ) -> Path:
        properties = dict(kwargs.pop("properties", None) or {})
        properties.setdefault("VAULT", vault)
        content = render_task(properties=properties, **kwargs)
        active_dir = tmp_path / "vaults" / vault / "tasks" / "active"
        active_dir.mkdir(parents=True, exist_ok=True)
        path = active_dir / name
        path.write_text(content)
        created.append(path)
        return path

    yield _make

    # Clean up any /tmp DoD markers the scripts may have dropped.
    for path in created:
        try:
            dod_marker_path(path).unlink(missing_ok=True)
        except OSError:
            pass


@pytest.fixture
def vault_creds_factory(tmp_path: Path):
    """Return a callable that materializes ``vaults/<vault>/creds/`` under
    ``tmp_path``.

    Used by ``bin/cloude-run`` tests. Creates an empty ``gh/`` directory
    (the mount source needs to exist; contents are opaque to cloude-run
    itself), an empty ``gitconfig`` file, and an ``env`` file containing
    ``GH_TOKEN=ghp_fixture`` so the assembled docker argv carries a
    vault-scoped token.

    Pass ``files={"gitconfig": "...", "env": "GH_TOKEN=xyz"}`` to
    override any individual entry, or ``omit=("env",)`` to leave one
    out (for the missing-creds fail-fast tests).
    """

    def _make(
        vault: str = "personal",
        *,
        files: dict[str, str] | None = None,
        omit: tuple[str, ...] = (),
    ) -> Path:
        creds = tmp_path / "vaults" / vault / "creds"
        creds.mkdir(parents=True, exist_ok=True)
        defaults = {
            "gitconfig": "[user]\n\tname = Fixture User\n",
            "env": "GH_TOKEN=ghp_fixture\n",
        }
        merged = {**defaults, **(files or {})}
        if "gh" not in omit:
            (creds / "gh").mkdir(exist_ok=True)
        for name, content in merged.items():
            if name in omit:
                continue
            (creds / name).write_text(content)
        return creds

    return _make


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR
