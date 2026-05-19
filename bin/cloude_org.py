"""Shared helpers for the cloude hook scripts and cloude-task-set-state.

`bin/cloude-on-stop` and `bin/cloude-on-user-prompt` both need to read
the first heading of a task `.org` file — its TODO keyword and its
who-has-the-ball tag — to decide whether to act. This module is the one
place that read-only parsing lives, so the two hooks cannot drift apart.

It also owns `dod_marker_path` — the location of the per-task
"a stage transition happened this turn" marker file. Four scripts
agree on that path: `cloude-task-set-state` and `cloude-on-plan-accepted`
drop the marker on a transition, and `cloude-on-stop` consumes it to
fire its Definition-of-Done reminder only once per transition / `/iterate`
turn rather than on every turn.

Why a hand-rolled regex here, instead of `orgparse`?

The repo's org-*reading* scripts — `cloude-dash`, `cloude-list-*`,
`cloude-task-info` — do use `orgparse`. They can, because they declare
it via a PEP 723 inline-deps header and are run through `uv`, which
resolves that third-party dependency transparently.

The hook scripts are different: Claude Code's hook runner executes them
directly via their `#!/usr/bin/env python3` shebang — *not* through
`uv`. There is no dependency resolution step, so they run on plain
stdlib `python3`, and a third-party `import orgparse` would simply fail.
Any module a hook imports inherits that same constraint, so this one is
deliberately stdlib-only (`re`).

That is no real loss: the grammar this touches is tiny and fixed — a
single heading line, `* <TODO> <text> :tag:chain:` — which one regex
covers comfortably. It is the same trade-off `cloude-task-set-state`
documents for its own regex-based heading *edit*. `orgparse` would
parse the entire file (every drawer, the `** Plan` subtree, the
logbook) just to read one line.

This module only *reads* a heading. The structural *rewrite* of a
heading still lives solely in `cloude-task-set-state`.
"""

import re
from pathlib import Path

# The who-has-the-ball tags, in priority order — see CLAUDE.md's
# "Who-has-the-ball tag" section.
BALL_TAGS = ("agent", "user", "blocked")

# The first top-level heading of a task file: leading stars + space, a
# non-space TODO keyword, optional heading text, an optional trailing
# `:tag:chain:`, then the line end. The non-greedy `(.*?)` for the
# heading text ensures a colon-word embedded in the title (e.g.
# ":user:" appearing mid-title) is not mistaken for the trailing tag
# chain — only the chain anchored at `\s*$` matches.
_HEADING_RE = re.compile(
    r"^\*\s+(\S+)\s+(.*?)\s*(?::([A-Za-z0-9_@:]+):)?\s*$",
    re.M,
)


def parse_heading(content: str) -> tuple[str, list[str]] | None:
    """Find the first top-level heading; return (TODO keyword, [tag names]).

    `content` is the full text of a task `.org` file. Tag names are
    split from the trailing org-tag chain (`:foo:bar:`); the list is
    empty when the heading carries no tags. Returns None when no
    heading is found.
    """
    m = _HEADING_RE.search(content)
    if not m:
        return None
    tag_chain = m.group(3) or ""
    return m.group(1), [t for t in tag_chain.split(":") if t]


def ball_tag(tags: list[str]) -> str:
    """Return the who-has-the-ball tag from a parsed tag list, or ''.

    `tags` is the list returned by `parse_heading`. If several tags are
    present, the first of agent/user/blocked (in `BALL_TAGS` order)
    wins.
    """
    return next((t for t in BALL_TAGS if t in tags), "")


def dod_marker_path(task_file: str | Path) -> Path:
    """Return the per-task Definition-of-Done marker path.

    The marker is a sentinel file: its mere presence means "a stage
    transition happened this turn, so the next `Stop` should fire the
    DoD reminder once." `cloude-task-set-state` (on a `--todo`
    transition into an in-flight stage) and `cloude-on-plan-accepted`
    create it; `cloude-on-stop` reads-and-unlinks it.

    It lives in `/tmp` — container-local, writable, and discarded when
    the container exits (one container runs one task, so there is
    nothing to clean up across tasks). The path is keyed by the task
    file's name so a stray host-side invocation can't collide with an
    unrelated task's marker.
    """
    return Path("/tmp") / f"cloude-dod-pending.{Path(task_file).name}"
