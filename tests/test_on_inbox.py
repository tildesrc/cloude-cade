"""Subprocess tests for ``bin/cloude-on-inbox``.

The hook is wired to ``UserPromptSubmit``. It reads
``inbox/<slug>/*.msg``, prints each file's content into the prompt
context, moves each into ``.seen/``, and ends with a one-line
reminder to use ``AskUserQuestion``. Silent on empty inboxes; never
blocks.
"""

from __future__ import annotations

import json
from pathlib import Path


MSG_TEMPLATE = "to: {to}\nfrom: {frm}\ndate: 2026-05-22T12:00:00.000+00:00\n\n{body}\n"


def _seed(inbox: Path, name: str, body: str, frm: str = "sender") -> Path:
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / name
    path.write_text(MSG_TEMPLATE.format(to="host", frm=frm, body=body))
    return path


def _hook_stdin() -> str:
    """The harness passes a JSON envelope; the hook only drains it."""
    return json.dumps({"prompt": "irrelevant"})


def test_empty_inbox_is_silent(run_script, tmp_path: Path):
    """No messages = no stdout, exit 0 — must not nag the agent."""
    result = run_script(
        "cloude-on-inbox", stdin=_hook_stdin(),
        env={"CLOUDE_ROOT": str(tmp_path), "CLOUDE_TASK_FILE": ""},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_missing_inbox_dir_is_silent(run_script, tmp_path: Path):
    """An inbox dir that doesn't exist yet is treated like an empty inbox."""
    result = run_script(
        "cloude-on-inbox", stdin=_hook_stdin(),
        env={"CLOUDE_ROOT": str(tmp_path), "CLOUDE_TASK_FILE": ""},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_surfaces_and_archives(run_script, tmp_path: Path):
    """Messages land in stdout (= prompt context) and move into ``.seen/``."""
    inbox = tmp_path / "inbox" / "host"
    a = _seed(inbox, "2026-05-22T12-00-00-001-alice.msg", "first body", frm="alice")
    b = _seed(inbox, "2026-05-22T12-00-00-002-bob.msg", "second body", frm="bob")

    result = run_script(
        "cloude-on-inbox", stdin=_hook_stdin(),
        env={"CLOUDE_ROOT": str(tmp_path), "CLOUDE_TASK_FILE": ""},
    )
    assert result.returncode == 0, result.stderr
    # Both messages surfaced in chronological order.
    pos_first = result.stdout.find("first body")
    pos_second = result.stdout.find("second body")
    assert 0 <= pos_first < pos_second
    # Headline + per-file banner + closing reminder are present.
    assert "2 new message(s)" in result.stdout
    assert "AskUserQuestion" in result.stdout
    # Both files moved into .seen/.
    assert not a.exists()
    assert not b.exists()
    seen = inbox / ".seen"
    assert (seen / a.name).is_file()
    assert (seen / b.name).is_file()


def test_second_invocation_silent_after_archive(run_script, tmp_path: Path):
    """After surfacing once, the next turn must not re-surface the same mail."""
    inbox = tmp_path / "inbox" / "host"
    _seed(inbox, "2026-05-22T12-00-00-001-alice.msg", "one")
    first = run_script(
        "cloude-on-inbox", stdin=_hook_stdin(),
        env={"CLOUDE_ROOT": str(tmp_path), "CLOUDE_TASK_FILE": ""},
    )
    assert first.returncode == 0
    second = run_script(
        "cloude-on-inbox", stdin=_hook_stdin(),
        env={"CLOUDE_ROOT": str(tmp_path), "CLOUDE_TASK_FILE": ""},
    )
    assert second.returncode == 0
    assert second.stdout == ""


def test_uses_task_file_slug(run_script, tmp_path: Path):
    """`$CLOUDE_TASK_FILE`'s slug determines which inbox to read."""
    inbox = tmp_path / "inbox" / "my-task"
    _seed(inbox, "2026-05-22T12-00-00-001-host.msg", "for my-task")

    result = run_script(
        "cloude-on-inbox", stdin=_hook_stdin(),
        env={
            "CLOUDE_ROOT": str(tmp_path),
            "CLOUDE_TASK_FILE": "/some/path/2026-05-22-my-task.org",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "for my-task" in result.stdout
    assert "inbox/my-task/" in result.stdout
