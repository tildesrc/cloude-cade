"""Shared org task-heading parsing for the cloude hook scripts.

`bin/cloude-on-stop` and `bin/cloude-on-user-prompt` both need to read
the first heading of a task `.org` file — its TODO keyword and its
who-has-the-ball tag — to decide whether to act. This module is the one
place that read-only parsing lives, so the two hooks cannot drift apart.

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
import sys
from pathlib import Path

# The who-has-the-ball tag set is part of the workflow definition, so it
# is sourced from cloude_workflow rather than hardcoded here. Both
# modules are stdlib-only siblings under bin/.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cloude_workflow  # noqa: E402

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
    present, the first in the workflow's ball-tag priority order wins.
    """
    ball_tags = cloude_workflow.load().ball_tag_names
    return next((t for t in ball_tags if t in tags), "")
