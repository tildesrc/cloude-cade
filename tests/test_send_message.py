"""Subprocess tests for ``bin/cloude-send-message``.

The script is stdlib-only and resolves its inbox root from
``$CLOUDE_ROOT`` (with a script-location fallback), so the tests
just point that env var at a ``tmp_path`` and assert on the file
the script writes there.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


def _stamp_filename_re(from_slug: str) -> re.Pattern[str]:
    """`<iso-utc-stamp-with-ms>-<from>.msg`, anchored."""
    return re.compile(
        rf"^\d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}-\d{{2}}-\d{{2}}-\d{{3}}-{re.escape(from_slug)}\.msg$"
    )


def test_writes_message_with_explicit_body(run_script, tmp_path: Path):
    """``-m TEXT`` lands as the message body, with proper headers."""
    result = run_script(
        "cloude-send-message", "host", "-m", "hello world",
        env={"CLOUDE_ROOT": str(tmp_path), "CLOUDE_TASK_FILE": ""},
    )
    assert result.returncode == 0, result.stderr
    inbox = tmp_path / "inbox" / "host"
    files = list(inbox.glob("*.msg"))
    assert len(files) == 1
    name = files[0].name
    assert _stamp_filename_re("host").match(name), name
    text = files[0].read_text()
    assert text.startswith("to: host\n")
    assert "from: host\n" in text
    assert re.search(r"^date: \d{4}-\d{2}-\d{2}T", text, re.MULTILINE)
    assert text.rstrip("\n").endswith("hello world")


def test_body_from_stdin(run_script, tmp_path: Path):
    """When ``-m`` is absent, stdin becomes the body."""
    result = run_script(
        "cloude-send-message", "host",
        stdin="line1\nline2\n",
        env={"CLOUDE_ROOT": str(tmp_path), "CLOUDE_TASK_FILE": ""},
    )
    assert result.returncode == 0, result.stderr
    text = (tmp_path / "inbox" / "host").glob("*.msg").__next__().read_text()
    assert text.endswith("line1\nline2\n")


def test_from_slug_from_task_file_env(run_script, tmp_path: Path):
    """``$CLOUDE_TASK_FILE`` basename without ``YYYY-MM-DD-`` is the from slug."""
    result = run_script(
        "cloude-send-message", "other-task", "-m", "hi",
        env={
            "CLOUDE_ROOT": str(tmp_path),
            "CLOUDE_TASK_FILE": "/somewhere/2026-05-22-my-task.org",
        },
    )
    assert result.returncode == 0, result.stderr
    files = list((tmp_path / "inbox" / "other-task").glob("*.msg"))
    assert len(files) == 1
    assert files[0].name.endswith("-my-task.msg")
    assert "from: my-task\n" in files[0].read_text()


def test_unparseable_task_file_refuses(run_script, tmp_path: Path):
    """Garbage in ``$CLOUDE_TASK_FILE`` is a hard refuse, not a silent host fallback."""
    result = run_script(
        "cloude-send-message", "host", "-m", "hi",
        env={
            "CLOUDE_ROOT": str(tmp_path),
            "CLOUDE_TASK_FILE": "/not-a-task-file.txt",
        },
    )
    assert result.returncode == 2
    assert not (tmp_path / "inbox" / "host").exists()


def test_unknown_recipient_warns_but_writes(run_script, tmp_path: Path):
    """An unknown recipient triggers a stderr warning but still gets the message."""
    result = run_script(
        "cloude-send-message", "future-task", "-m", "pre-empt",
        env={"CLOUDE_ROOT": str(tmp_path), "CLOUDE_TASK_FILE": ""},
    )
    assert result.returncode == 0, result.stderr
    assert "warning" in result.stderr.lower()
    assert (tmp_path / "inbox" / "future-task").is_dir()


def test_known_recipient_no_warning(run_script, task_file_factory, tmp_path: Path):
    """When the recipient slug matches an active task, no warning is emitted."""
    task_file_factory(name="2026-05-22-real-task.org")
    result = run_script(
        "cloude-send-message", "real-task", "-m", "hi",
        env={"CLOUDE_ROOT": str(tmp_path), "CLOUDE_TASK_FILE": ""},
    )
    assert result.returncode == 0, result.stderr
    assert "warning" not in result.stderr.lower()


def test_atomic_no_tmp_leftover(run_script, tmp_path: Path):
    """The atomic-rename path doesn't leave a ``.tmp-*`` file behind on success."""
    run_script(
        "cloude-send-message", "host", "-m", "x",
        env={"CLOUDE_ROOT": str(tmp_path), "CLOUDE_TASK_FILE": ""},
        check=True,
    )
    leftovers = list((tmp_path / "inbox" / "host").glob(".tmp-*"))
    assert leftovers == []


def test_invalid_slug_rejected(run_script, tmp_path: Path):
    """Slugs must be lowercase letters / digits / hyphens — others are an arg error."""
    result = run_script(
        "cloude-send-message", "Bad_Slug", "-m", "x",
        env={"CLOUDE_ROOT": str(tmp_path), "CLOUDE_TASK_FILE": ""},
    )
    assert result.returncode == 1
    assert not (tmp_path / "inbox").exists()


def test_prints_relative_path(run_script, tmp_path: Path):
    """Stdout is the path of the written file, relative to ``$CLOUDE_ROOT``."""
    result = run_script(
        "cloude-send-message", "host", "-m", "x",
        env={"CLOUDE_ROOT": str(tmp_path), "CLOUDE_TASK_FILE": ""},
    )
    assert result.returncode == 0, result.stderr
    printed = result.stdout.strip()
    assert printed.startswith("inbox/host/")
    assert (tmp_path / printed).is_file()
