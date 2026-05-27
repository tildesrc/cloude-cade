"""Subprocess tests for ``bin/cloude-read-inbox``.

The script reads messages from ``$CLOUDE_ROOT/inbox/<slug>/``, prints
them in chronological filename order, and (by default) archives them
into ``.seen/``. The tests seed messages directly on disk under a
``tmp_path`` inbox and assert on stdout + on-disk state.
"""

from __future__ import annotations

from pathlib import Path


MSG_TEMPLATE = "to: {to}\nfrom: {frm}\ndate: 2026-05-22T12:00:00.000+00:00\n\n{body}\n"


def _seed(inbox: Path, name: str, body: str) -> Path:
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / name
    path.write_text(MSG_TEMPLATE.format(to="host", frm="sender", body=body))
    return path


def test_empty_inbox_prints_friendly(run_script, tmp_path: Path):
    """No inbox dir at all is still a clean exit with the standard message."""
    result = run_script(
        "cloude-read-inbox",
        env={"CLOUDE_ROOT": str(tmp_path), "CLOUDE_TASK_FILE": ""},
    )
    assert result.returncode == 0, result.stderr
    assert "No new messages." in result.stdout


def test_default_archives_after_reading(run_script, tmp_path: Path):
    """Default mode prints each message and moves it into ``.seen/``."""
    inbox = tmp_path / "inbox" / "host"
    a = _seed(inbox, "2026-05-22T12-00-00-001-alice.msg", "first")
    b = _seed(inbox, "2026-05-22T12-00-00-002-bob.msg", "second")

    result = run_script(
        "cloude-read-inbox",
        env={"CLOUDE_ROOT": str(tmp_path), "CLOUDE_TASK_FILE": ""},
    )
    assert result.returncode == 0, result.stderr
    # Chronological by filename.
    pos_first = result.stdout.find("first")
    pos_second = result.stdout.find("second")
    assert 0 <= pos_first < pos_second
    # Both files moved into .seen/.
    assert not a.exists()
    assert not b.exists()
    seen = inbox / ".seen"
    assert (seen / a.name).is_file()
    assert (seen / b.name).is_file()


def test_no_archive_peeks_without_moving(run_script, tmp_path: Path):
    """``--no-archive`` leaves messages where they are."""
    inbox = tmp_path / "inbox" / "host"
    a = _seed(inbox, "2026-05-22T12-00-00-001-alice.msg", "peek me")
    result = run_script(
        "cloude-read-inbox", "--no-archive",
        env={"CLOUDE_ROOT": str(tmp_path), "CLOUDE_TASK_FILE": ""},
    )
    assert result.returncode == 0, result.stderr
    assert "peek me" in result.stdout
    assert a.exists()
    assert not (inbox / ".seen").exists()


def test_all_includes_seen(run_script, tmp_path: Path):
    """``--all`` surfaces already-seen messages without moving them back."""
    inbox = tmp_path / "inbox" / "host"
    seen = inbox / ".seen"
    seen.mkdir(parents=True)
    old = seen / "2026-05-22T11-00-00-000-alice.msg"
    old.write_text(MSG_TEMPLATE.format(to="host", frm="alice", body="historical"))
    _seed(inbox, "2026-05-22T12-00-00-000-alice.msg", "fresh")

    result = run_script(
        "cloude-read-inbox", "--all",
        env={"CLOUDE_ROOT": str(tmp_path), "CLOUDE_TASK_FILE": ""},
    )
    assert result.returncode == 0, result.stderr
    assert "historical" in result.stdout
    assert "fresh" in result.stdout
    # The old one stays in .seen/.
    assert old.exists()


def test_positional_slug_overrides_env(run_script, tmp_path: Path):
    """A positional ``<slug>`` reads that inbox, ignoring ``$CLOUDE_TASK_FILE``."""
    inbox = tmp_path / "inbox" / "other-agent"
    _seed(inbox, "2026-05-22T12-00-00-000-x.msg", "into other-agent inbox")

    result = run_script(
        "cloude-read-inbox", "other-agent",
        env={
            "CLOUDE_ROOT": str(tmp_path),
            "CLOUDE_TASK_FILE": "/somewhere/2026-05-22-something-else.org",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "into other-agent inbox" in result.stdout


def test_slug_derived_from_task_file(run_script, tmp_path: Path):
    """Without an explicit slug, ``$CLOUDE_TASK_FILE`` selects the inbox."""
    inbox = tmp_path / "inbox" / "my-task"
    _seed(inbox, "2026-05-22T12-00-00-000-host.msg", "to my-task")
    result = run_script(
        "cloude-read-inbox",
        env={
            "CLOUDE_ROOT": str(tmp_path),
            "CLOUDE_TASK_FILE": "/some/path/2026-05-22-my-task.org",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "to my-task" in result.stdout
