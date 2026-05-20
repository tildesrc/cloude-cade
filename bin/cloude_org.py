"""Shared helpers for the cloude hook scripts and cloude-task-set-state.

`bin/cloude-on-stop`, `bin/cloude-on-user-prompt`, and
`bin/cloude-on-user-question` all need to read the first heading of a
task `.org` file — its TODO keyword and its who-has-the-ball tag — to
decide whether to act. This module is the one place that read-only
parsing lives, so those hooks cannot drift apart.

It also owns the per-stage `** Log` entry schema introduced by the
DoD-redesign work: every stage transition / `/iterate` appends a
`*** [<timestamp>] <STAGE>` sub-heading under `** Log` with
`**** Request`, `**** Work`, and `**** <verdict> DoD` sub-sub-headings.
The verdict lives as a real org TODO keyword on the DoD heading
(drawn from the second file-level `#+TODO:` sequence —
`PENDING(P!) UNSATISFIABLE(U!) | PASS(D!)`). The DoD body carries one
`- [ ] <bullet>` per stage-DoD criterion, seeded from `STAGE_DOD`
below, with a `[/]` statistics cookie on the heading.

The skeleton-append and verdict-flip operations live here so the
schema has one home; `bin/cloude-task-set-state` calls them on
`--todo` and `--dod-state` respectively.

It also owns `dod_marker_path` — the location of the per-task
"a stage transition happened this turn" marker file. Four scripts
agree on that path: `cloude-task-set-state` and `cloude-on-plan-accepted`
drop the marker on a transition, and `cloude-on-stop` consumes it to
fire its Definition-of-Done check only once per transition / `/iterate`
turn rather than on every turn.

Why hand-rolled regex here, instead of `orgparse`?

It is no longer a hard constraint. The hook scripts that import this
module (`cloude-on-stop`, `cloude-on-user-prompt`,
`cloude-on-user-question`, `cloude-on-plan-accepted`,
`cloude-task-set-state`) are re-exec'd through `bin/cloude-python`
via an sh/Python polyglot shebang, so they run under the shared
cloude venv built from the repo-root `pyproject.toml` + `uv.lock`.
`import orgparse` works here — adding it is a one-line edit to the
manifest, no per-invocation `uv run` overhead. See
`docs/internals.md` → "Why hot-path hooks don't use `uv run`" for
the full launcher / lockfile story.

We keep the regex-based implementation for now because the grammar
it touches is tiny and fixed — a single heading line,
`* <TODO> <text> :tag:chain:`, plus the log entry schema described
above — and the log-entry editor in particular needs byte/line
ranges per node that `orgparse` doesn't expose (it'd have to be
hand-written either way). Future work can swap individual helpers
(e.g. `parse_heading`) to `orgparse` without touching the rest.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

# The who-has-the-ball tags, in priority order — see CLAUDE.md's
# "Who-has-the-ball tag" section.
BALL_TAGS = ("agent", "user", "blocked")

# The two file-level TODO sequences this module knows about.
STAGE_KEYWORDS = ("PLANNING", "ITERATING", "REVIEW", "MERGING", "COMPLETE", "DROPPED")
DOD_KEYWORDS = ("PENDING", "UNSATISFIABLE", "PASS")

# Per-stage Definition-of-Done bullets. The skeleton-appender seeds
# one `- [ ]` checkbox per bullet under `**** [/] PENDING DoD`, and
# `cloude-on-stop` cross-checks the checkbox count against the verdict.
#
# CLAUDE.md (Stage details → <stage> → Definition of done) mirrors
# these bullets as the human-facing copy. If you edit a bullet here,
# edit CLAUDE.md to match.
STAGE_DOD: dict[str, tuple[str, ...]] = {
    "PLANNING": (
        "The plan is written into the task's org file.",
        "The user has approved the plan.",
        "A draft PR has been created on GitHub.",
    ),
    "ITERATING": (
        "The plan is implemented in code.",
        "All user requests are implemented in code.",
        "New and relevant tests pass locally.",
        "Changes are committed and pushed.",
        "CI tests are passing, or any failures can be attributed to irrelevant flakes.",
        "The PR title and description on GitHub reflect the final change.",
    ),
    "REVIEW": (
        "The PR has been reviewed.",
    ),
    "MERGING": (
        "The PR is merged.",
    ),
    "COMPLETE": (
        "The merge has landed and the task is finished.",
    ),
    "DROPPED": (
        "The task has been intentionally abandoned.",
    ),
}

# The canonical text of the PLANNING DoD bullet that records the user's
# approval of the plan. `mark_plan_approved` matches against this exact
# string so it can be ticked automatically when the user triggers any
# transition out of PLANNING (the trigger itself is the approval). Kept
# as a derived constant so it can't drift from STAGE_DOD.
PLAN_APPROVED_BULLET = STAGE_DOD["PLANNING"][1]

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
    DoD check once." `cloude-task-set-state` (on a `--todo`
    transition into an in-flight stage) and `cloude-on-plan-accepted`
    create it; `cloude-on-stop` reads-and-unlinks it.

    It lives in `/tmp` — container-local, writable, and discarded when
    the container exits (one container runs one task, so there is
    nothing to clean up across tasks). The path is keyed by the task
    file's name so a stray host-side invocation can't collide with an
    unrelated task's marker.
    """
    return Path("/tmp") / f"cloude-dod-pending.{Path(task_file).name}"


# ---------------------------------------------------------------------------
# Log-entry schema
# ---------------------------------------------------------------------------
#
# Each task file has a `** Log` top-level section containing one
# `*** [<timestamp>] <STAGE> (via ...)` sub-heading per stage entry /
# re-entry. Per-entry layout:
#
#   *** [2026-05-20 Wed 11:30] ITERATING (via /advance from PLANNING)
#       :PROPERTIES:
#       :STAGE:       ITERATING
#       :ENTERED:     [2026-05-20 Wed 11:30]
#       :ENTERED_VIA: /advance from PLANNING
#       :EXITED:      [...] (only on past entries)
#       :DURATION:    [...] (only on past entries)
#       :END:
#   **** Request
#        ...
#   **** Work
#        ...
#   **** [N/M] <VERDICT> DoD
#        CLOSED: [...] (only when verdict is PASS)
#        :LOGBOOK:
#        - State "..." from "..." [...]
#        :END:
#        - [ ]/[X]/[-] <bullet>
#        ... (more bullets) ...
#        optional explanation prose
#
# The level-3 heading text is prefixed with a `[<timestamp>]` so org
# doesn't mistake the stage word for a TODO state (the stage sequence
# is file-scoped and applies to any heading whose first word matches a
# keyword). The stage is read from the `:STAGE:` property, which is
# the canonical source.

ORG_TS_FMT = "%Y-%m-%d %a %H:%M"


def now_ts() -> str:
    """Return the current local time as an org inactive timestamp body.

    The body is what goes between the `[` and `]` brackets, e.g.
    `2026-05-20 Wed 16:39`. Callers wrap it in brackets themselves.
    """
    return _dt.datetime.now().strftime(ORG_TS_FMT)


def _parse_ts(body: str) -> _dt.datetime | None:
    """Parse an org inactive-timestamp body. Returns None on failure."""
    try:
        return _dt.datetime.strptime(body.strip(), ORG_TS_FMT)
    except (TypeError, ValueError):
        return None


def _format_duration(start: _dt.datetime, end: _dt.datetime) -> str:
    """Render `end - start` as `Nh Nm` (or `Nm` if under an hour)."""
    delta = end - start
    total_minutes = int(delta.total_seconds() // 60)
    if total_minutes < 0:
        total_minutes = 0
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


_LOG_SECTION_END_RE = re.compile(
    r"^(?:\*{1,2}[ \t]|# Local Variables:)", re.M
)


def find_log_section(content: str) -> tuple[int, int] | None:
    """Return (start, end) char offsets of the `** Log` section, or None.

    The section runs from the `** Log` heading line through the
    character just before:
      - the next top-level (`* `) or second-level (`** `) heading, OR
      - the file-local-variables block (`# Local Variables:`), which
        org-mode requires at the very end of the file, OR
      - end of file.
    The bounds are suitable for `content[start:end]` slicing.
    """
    log_match = re.search(r"^\*\* Log\s*$", content, re.M)
    if not log_match:
        return None
    start = log_match.start()
    after = log_match.end()
    next_boundary = _LOG_SECTION_END_RE.search(content[after:])
    end = after + next_boundary.start() if next_boundary else len(content)
    return (start, end)


_ENTRY_HEADING_RE = re.compile(r"^\*\*\*[ \t]", re.M)


def iter_log_entries(content: str) -> list[dict]:
    """Parse the `** Log` section and return one record per `***` entry.

    Each record is a dict:
      stage         (str) — from the :STAGE: property
      entered       (str) — :ENTERED: value (org timestamp body), or ''
      entered_via   (str) — :ENTERED_VIA: value, or ''
      exited        (str) — :EXITED: value, or '' if still active
      duration      (str) — :DURATION: value, or '' if still active
      request       (str) — body of `**** Request`, stripped
      work          (str) — body of `**** Work`, stripped
      dod_verdict   (str) — TODO keyword on `**** DoD`: one of
                            PENDING / UNSATISFIABLE / PASS, or 'PENDING'
                            if the keyword is missing or unrecognized
      dod_cookie    (str) — the `[/]` / `[N/M]` cookie text from the
                            DoD heading, or '' if absent
      dod_checkboxes (list[str]) — per-bullet state, in order:
                            'open' for `[ ]`, 'ticked' for `[X]`/`[x]`,
                            'na' for `[-]`
      dod_body      (str) — full body of `**** DoD` (LOGBOOK + boxes
                            + prose), stripped
      span          (tuple[int, int]) — char offsets of this entry
                            within `content`; suitable for `content[a:b]`
      dod_span      (tuple[int, int]) — char offsets of the DoD
                            sub-sub-heading (from its `****` line
                            through the character before the next
                            `****` or the entry's end)

    Returns an empty list if there is no `** Log` section or it has no
    entries.
    """
    log_span = find_log_section(content)
    if log_span is None:
        return []
    section_start, section_end = log_span
    section_text = content[section_start:section_end]

    entry_offsets = [m.start() for m in _ENTRY_HEADING_RE.finditer(section_text)]
    if not entry_offsets:
        return []

    entries: list[dict] = []
    for i, offset in enumerate(entry_offsets):
        end_offset = (
            entry_offsets[i + 1] if i + 1 < len(entry_offsets) else len(section_text)
        )
        entry_text = section_text[offset:end_offset]
        abs_span = (section_start + offset, section_start + end_offset)
        record = _parse_log_entry(entry_text, abs_span)
        entries.append(record)
    return entries


def latest_log_entry(content: str) -> dict | None:
    """Return the last log entry in document order, or None if absent."""
    entries = iter_log_entries(content)
    return entries[-1] if entries else None


_PROP_DRAWER_RE = re.compile(r":PROPERTIES:\s*\n(.*?):END:\s*\n", re.S | re.I)
_PROP_LINE_RE = re.compile(r"^\s*:([A-Za-z0-9_]+):\s*(.*)$")
_SUBSECTION_RE = re.compile(r"^\*\*\*\*[ \t](.+)$", re.M)
_DOD_HEADING_RE = re.compile(
    r"^\*\*\*\*[ \t]+(?:(\[[0-9/%]+\])\s+)?(?:(PENDING|UNSATISFIABLE|PASS)\s+)?DoD\s*$",
    re.M,
)
_CHECKBOX_RE = re.compile(r"^\s*-\s+\[([ Xx-])\]", re.M)


def _parse_log_entry(entry_text: str, abs_span: tuple[int, int]) -> dict:
    """Parse a single `*** ... ` entry. `abs_span` is its offset in the file."""
    section_offset = abs_span[0]

    # Properties drawer.
    props: dict[str, str] = {}
    pm = _PROP_DRAWER_RE.search(entry_text)
    if pm:
        for line in pm.group(1).splitlines():
            lm = _PROP_LINE_RE.match(line)
            if lm:
                props[lm.group(1).upper()] = lm.group(2).strip()

    # Sub-sub-headings: `**** Request`, `**** Work`, `**** ... DoD`.
    sub_starts = [m.start() for m in re.finditer(r"^\*\*\*\*[ \t]", entry_text, re.M)]

    request_body = ""
    work_body = ""
    dod_body = ""
    dod_heading_line = ""
    dod_span: tuple[int, int] | None = None
    for i, start in enumerate(sub_starts):
        end = sub_starts[i + 1] if i + 1 < len(sub_starts) else len(entry_text)
        sub_text = entry_text[start:end]
        first_line, _, body = sub_text.partition("\n")
        heading_text = first_line.rstrip()
        # Classify by suffix word(s).
        stripped = heading_text.lstrip("* \t").strip()
        if stripped == "Request":
            request_body = body.strip("\n")
        elif stripped == "Work":
            work_body = body.strip("\n")
        elif stripped.endswith("DoD"):
            dod_heading_line = heading_text
            dod_body = body.strip("\n")
            dod_span = (section_offset + start, section_offset + end)

    # Verdict + cookie from the DoD heading line.
    dod_verdict = "PENDING"
    dod_cookie = ""
    if dod_heading_line:
        dm = _DOD_HEADING_RE.match(dod_heading_line)
        if dm:
            dod_cookie = dm.group(1) or ""
            dod_verdict = dm.group(2) or "PENDING"

    # Per-checkbox states.
    checkboxes: list[str] = []
    if dod_body:
        for cb in _CHECKBOX_RE.finditer(dod_body):
            ch = cb.group(1)
            if ch == " ":
                checkboxes.append("open")
            elif ch in ("X", "x"):
                checkboxes.append("ticked")
            elif ch == "-":
                checkboxes.append("na")

    return {
        "stage": props.get("STAGE", ""),
        "entered": props.get("ENTERED", "").strip("[]"),
        "entered_via": props.get("ENTERED_VIA", ""),
        "exited": props.get("EXITED", "").strip("[]"),
        "duration": props.get("DURATION", ""),
        "request": request_body,
        "work": work_body,
        "dod_verdict": dod_verdict,
        "dod_cookie": dod_cookie,
        "dod_checkboxes": checkboxes,
        "dod_body": dod_body,
        "span": abs_span,
        "dod_span": dod_span,
    }


def _format_cookie(checkboxes: list[str]) -> str:
    """Return `[N/M]` where N = ticked+na, M = total. `[0/0]` if empty."""
    total = len(checkboxes)
    done = sum(1 for c in checkboxes if c in ("ticked", "na"))
    return f"[{done}/{total}]"


def mark_plan_approved(content: str) -> str:
    """Tick the `PLAN_APPROVED_BULLET` checkbox on the latest PLANNING entry.

    The user invoking `/advance`, `/iterate`, or plan-mode accept while
    a task is in PLANNING is itself the user's approval — there is no
    separate "yes I approve" gesture to record. This helper updates
    the closing PLANNING log entry's DoD body so the audit trail shows
    that approval as ticked, and refreshes the `[N/M]` cookie on the
    DoD heading to match.

    No-op (returns content unchanged) when:
      - there is no log entry,
      - the latest entry is not for stage PLANNING,
      - the entry has no `**** DoD` sub-sub-heading,
      - the canonical bullet is absent from the DoD body, or
      - the matching checkbox is already `[X]`/`[x]`/`[-]`.

    Strict match against `PLAN_APPROVED_BULLET`: a customized bullet
    is silently left alone (the customizer can tick by hand if they
    want). The verdict keyword on the DoD heading is preserved.
    """
    entry = latest_log_entry(content)
    if entry is None or entry["stage"] != "PLANNING" or entry["dod_span"] is None:
        return content

    dod_a, dod_b = entry["dod_span"]
    dod_text = content[dod_a:dod_b]

    # Tick the matching open checkbox, if any. Anchored on the exact
    # bullet text and `[ ]` so an already-ticked / N/A entry is a no-op.
    pattern = re.compile(
        r"^(\s*-\s+)\[ \](\s+" + re.escape(PLAN_APPROVED_BULLET) + r")\s*$",
        re.M,
    )
    new_dod_text, count = pattern.subn(r"\1[X]\2", dod_text, count=1)
    if count == 0:
        return content

    # Recompute the [N/M] cookie on the heading line from the updated body.
    first_line, sep, body_after = new_dod_text.partition("\n")
    boxes: list[str] = []
    for cb in _CHECKBOX_RE.finditer(body_after):
        ch = cb.group(1)
        if ch == " ":
            boxes.append("open")
        elif ch in ("X", "x"):
            boxes.append("ticked")
        elif ch == "-":
            boxes.append("na")
    new_cookie = _format_cookie(boxes)

    heading_match = _DOD_HEADING_RE.match(first_line)
    if heading_match:
        verdict = heading_match.group(2) or "PENDING"
        new_first_line = f"**** {new_cookie} {verdict} DoD"
        new_dod_text = new_first_line + sep + body_after

    return content[:dod_a] + new_dod_text + content[dod_b:]


def append_log_entry_skeleton(
    content: str,
    *,
    stage: str,
    via: str,
    prev_stage: str = "",
    when: str | None = None,
) -> str:
    """Append a fresh log entry skeleton; stamp :EXITED:/:DURATION: on prior.

    `when` is an org-timestamp body (as returned by `now_ts()`); if
    omitted, the current local time is used. `prev_stage` is included
    in the new entry's `:ENTERED_VIA:` text (e.g.
    `/advance from PLANNING`); pass empty for the very first entry.

    Behavior:
      - If there is no `** Log` section, raises ValueError. Callers
        decide whether to create one first.
      - Stamps `:EXITED:` and computes `:DURATION:` on the previously
        latest entry (if any) so the audit trail closes the prior
        stage. If `:ENTERED:` is unparseable on that entry, the
        DURATION line is omitted but EXITED still goes in.
      - Appends the new entry with `**** [/] PENDING DoD` carrying
        one `- [ ]` per `STAGE_DOD[stage]` bullet. The cookie is
        rendered as `[0/N]` for clarity.
    """
    when_body = when or now_ts()
    log_span = find_log_section(content)
    if log_span is None:
        raise ValueError("task file is missing the ** Log section")

    bullets = STAGE_DOD.get(stage, ())
    # If we don't know the stage's DoD, write a single placeholder
    # bullet so the cookie has something to count and the agent has
    # something to delete/replace by hand.
    if not bullets:
        bullets = (f"(no DoD bullets registered for stage {stage})",)

    via_text = f"{via} from {prev_stage}" if prev_stage else via
    entry_lines = [
        f"*** [{when_body}] {stage} (via {via_text})",
        "    :PROPERTIES:",
        f"    :STAGE:       {stage}",
        f"    :ENTERED:     [{when_body}]",
        f"    :ENTERED_VIA: {via_text}",
        "    :END:",
        "**** Request",
        "**** Work",
        f"**** [0/{len(bullets)}] PENDING DoD",
    ]
    for b in bullets:
        entry_lines.append(f"     - [ ] {b}")
    new_entry_text = "\n".join(entry_lines) + "\n"

    # Stamp EXITED/DURATION on the previously-latest entry (if any).
    prior = latest_log_entry(content)
    if prior is not None and prior["span"] is not None:
        a, b = prior["span"]
        prior_text = content[a:b]
        prior_text = _stamp_exited_duration(prior_text, prior, when_body)
        content = content[:a] + prior_text + content[b:]

    # Append the new entry at the end of the section.
    new_section_end = find_log_section(content)
    if new_section_end is None:
        # Shouldn't happen — we just verified it exists above — but
        # tolerate it: append at file end.
        return content.rstrip("\n") + "\n\n" + new_entry_text
    _, section_end = new_section_end
    head = content[:section_end].rstrip("\n")
    tail = content[section_end:]
    sep = "\n\n" if head else ""
    middle = "\n\n" if tail else "\n"
    return head + sep + new_entry_text.rstrip("\n") + middle + tail.lstrip("\n")


def _stamp_exited_duration(prior_text: str, prior: dict, exit_ts_body: str) -> str:
    """Return prior_text with :EXITED:/:DURATION: added to its drawer.

    If :EXITED: is already present, it's left alone (the prior
    transition already closed this entry). Otherwise, :EXITED: is
    inserted into the drawer and :DURATION: is computed from
    :ENTERED: when parseable.
    """
    if prior.get("exited"):
        return prior_text  # already closed

    entered = _parse_ts(prior.get("entered", ""))
    exited = _parse_ts(exit_ts_body)
    duration_line = ""
    if entered and exited:
        duration_line = f"    :DURATION:    {_format_duration(entered, exited)}\n"

    insertion = f"    :EXITED:      [{exit_ts_body}]\n{duration_line}"

    # Find the prior entry's properties drawer's :END: line.
    pm = _PROP_DRAWER_RE.search(prior_text)
    if not pm:
        return prior_text  # no drawer to amend
    # Insert just before the :END: line: find it within the match.
    # The match consumed `:END:\s*\n`; locate its start.
    end_match = re.search(r"^\s*:END:\s*\n", prior_text[pm.start():pm.end()], re.M)
    if not end_match:
        return prior_text
    abs_end_start = pm.start() + end_match.start()
    return prior_text[:abs_end_start] + insertion + prior_text[abs_end_start:]


class DodConsistencyError(ValueError):
    """Raised when --dod-state would create a verdict/cookie mismatch."""


def set_dod_verdict(
    content: str,
    *,
    new_verdict: str,
    when: str | None = None,
    body: str | None = None,
) -> str:
    """Flip the latest log entry's DoD verdict; append a LOGBOOK entry.

    `new_verdict` is one of PENDING / UNSATISFIABLE / PASS. `body`, if
    provided, replaces the prose block *after* the checkbox lines
    (the per-bullet `- [ ]/[X]/[-]` lines are preserved).

    Enforces the consistency rule:
      - PASS requires every box to be ticked or N/A (no `[ ]`).
      - UNSATISFIABLE requires at least one open `[ ]`.
      - PENDING has no checkbox constraint.

    On flip to PASS, also writes a `CLOSED: [<ts>]` line just below
    the heading (mirroring what `org-log-done` would do).

    Returns the new file content. Raises `DodConsistencyError` if the
    transition would violate the rule; `ValueError` for schema
    problems (no log section, no entries, no DoD sub-heading).
    """
    when_body = when or now_ts()
    new_verdict = new_verdict.upper()
    if new_verdict not in DOD_KEYWORDS:
        raise ValueError(f"unknown DoD verdict: {new_verdict!r}")

    entry = latest_log_entry(content)
    if entry is None:
        raise ValueError("no log entries to flip")
    if entry["dod_span"] is None:
        raise ValueError("latest log entry has no `**** DoD` sub-heading")

    boxes = entry["dod_checkboxes"]
    open_count = sum(1 for c in boxes if c == "open")
    total = len(boxes)
    if new_verdict == "PASS" and open_count > 0:
        raise DodConsistencyError(
            f"cannot flip to PASS: {open_count} of {total} DoD bullets "
            f"are still unchecked. Tick them (`[X]`) or mark N/A "
            f"(`[-]`) first, or flip to UNSATISFIABLE instead."
        )
    if new_verdict == "UNSATISFIABLE" and total > 0 and open_count == 0:
        raise DodConsistencyError(
            f"cannot flip to UNSATISFIABLE: every DoD bullet is ticked. "
            f"If the work is genuinely done, flip to PASS instead."
        )

    old_verdict = entry["dod_verdict"]
    dod_a, dod_b = entry["dod_span"]
    dod_text = content[dod_a:dod_b]

    # Rewrite the DoD heading line: new cookie, new keyword.
    new_cookie = _format_cookie(boxes)
    first_line, _, after_first = dod_text.partition("\n")
    new_heading = f"**** {new_cookie} {new_verdict} DoD"

    # Determine indentation of body lines (typically 5 spaces). Use
    # the indent that already exists in the body if any, else default.
    indent = "     "  # 5 spaces — matches existing skeleton layout

    # Re-assemble the DoD section piece by piece. The structure is:
    #   <heading>\n
    #   [CLOSED line]\n
    #   [LOGBOOK drawer]\n
    #   [checkbox lines]\n
    #   [prose body]\n
    # We extract the checkbox + drawer slice, then write a fresh
    # CLOSED line (PASS only), a fresh LOGBOOK drawer, the preserved
    # checkbox lines, and either the preserved or replaced body prose.

    body_text = after_first  # everything after the heading line + newline

    # 1. Extract the existing LOGBOOK drawer (if any), capturing its
    #    inner lines so we can prepend a new state-change entry.
    logbook_re = re.compile(
        r"(?P<indent>[ \t]*):LOGBOOK:\s*\n(?P<lines>.*?)(?P=indent):END:\s*\n",
        re.S | re.I,
    )
    lb_match = logbook_re.search(body_text)
    if lb_match:
        prior_lb_lines = lb_match.group("lines")
        body_text = body_text[:lb_match.start()] + body_text[lb_match.end():]
    else:
        prior_lb_lines = ""

    # 2. Extract an existing CLOSED line (we may rewrite it).
    closed_re = re.compile(r"^[ \t]*CLOSED:\s+\[[^]]+\]\s*\n", re.M)
    body_text = closed_re.sub("", body_text, count=1)

    # 3. Split the remaining body into checkbox lines + prose. The
    #    checkbox block is a contiguous run of `- [ ]` / `- [X]` /
    #    `- [-]` lines at any indent; prose is everything after.
    lines = body_text.split("\n")
    # Skip leading blank lines.
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    # Capture checkbox block.
    cb_lines: list[str] = []
    while i < len(lines) and _CHECKBOX_RE.match(lines[i]):
        cb_lines.append(lines[i])
        i += 1
    # Remainder is prose (skip a single blank separator).
    while i < len(lines) and not lines[i].strip():
        i += 1
    prose_lines = lines[i:]
    prose_text = "\n".join(prose_lines).strip("\n")

    if body is not None:
        # Caller provided a replacement prose body. Indent each line
        # to match the existing layout.
        replacement_lines = [
            (f"{indent}{ln}" if ln else ln) for ln in body.rstrip("\n").splitlines()
        ]
        prose_text = "\n".join(replacement_lines)

    # 4. Build the new DoD section.
    out_parts = [new_heading + "\n"]
    if new_verdict == "PASS":
        out_parts.append(f"{indent}CLOSED: [{when_body}]\n")

    # Logbook: prepend the new transition entry.
    new_lb_entry = (
        f'{indent}- State "{new_verdict}"'
        f' from "{old_verdict}"  [{when_body}]\n'
    )
    out_parts.append(f"{indent}:LOGBOOK:\n")
    out_parts.append(new_lb_entry)
    if prior_lb_lines:
        out_parts.append(prior_lb_lines if prior_lb_lines.endswith("\n") else prior_lb_lines + "\n")
    out_parts.append(f"{indent}:END:\n")

    # Checkbox lines.
    for cb in cb_lines:
        out_parts.append(cb + "\n")

    # Prose body.
    if prose_text:
        out_parts.append("\n")
        out_parts.append(prose_text)
        if not prose_text.endswith("\n"):
            out_parts.append("\n")

    new_dod_text = "".join(out_parts)
    return content[:dod_a] + new_dod_text + content[dod_b:]


# ---------------------------------------------------------------------------
# Smoke tests — run with `python3 bin/cloude_org.py` to exercise.
# ---------------------------------------------------------------------------

def _smoke() -> int:
    """Tiny self-test for the log-entry helpers; print results."""
    import io
    import sys
    sample = """\
#+TITLE: t
#+TODO: PLANNING ITERATING | COMPLETE
#+TODO: PENDING UNSATISFIABLE | PASS

* ITERATING title :agent:
  :PROPERTIES:
  :ID: t
  :END:

** Goal
   stuff

** Log
*** [2026-05-20 Wed 10:00] PLANNING (via /promote)
    :PROPERTIES:
    :STAGE:       PLANNING
    :ENTERED:     [2026-05-20 Wed 10:00]
    :ENTERED_VIA: /promote
    :EXITED:      [2026-05-20 Wed 11:30]
    :DURATION:    1h 30m
    :END:
**** Request
     do stuff
**** Work
     did stuff
**** [3/3] PASS DoD
     CLOSED: [2026-05-20 Wed 11:28]
     :LOGBOOK:
     - State "PASS"    from "PENDING" [2026-05-20 Wed 11:28]
     - State "PENDING" from ""        [2026-05-20 Wed 10:00]
     :END:
     - [X] One.
     - [X] Two.
     - [-] Three (N/A).

*** [2026-05-20 Wed 11:30] ITERATING (via /advance from PLANNING)
    :PROPERTIES:
    :STAGE:       ITERATING
    :ENTERED:     [2026-05-20 Wed 11:30]
    :ENTERED_VIA: /advance from PLANNING
    :END:
**** Request
     impl
**** Work
     in progress
**** [/] PENDING DoD
     - [ ] A.
     - [ ] B.
     - [ ] C.
"""
    out = io.StringIO()
    def p(*args):
        print(*args, file=out)

    entries = iter_log_entries(sample)
    p(f"entries: {len(entries)}")
    assert len(entries) == 2, entries
    p(f"  [0] stage={entries[0]['stage']!r} verdict={entries[0]['dod_verdict']!r} cookie={entries[0]['dod_cookie']!r} boxes={entries[0]['dod_checkboxes']!r}")
    p(f"  [1] stage={entries[1]['stage']!r} verdict={entries[1]['dod_verdict']!r} cookie={entries[1]['dod_cookie']!r} boxes={entries[1]['dod_checkboxes']!r}")
    assert entries[0]["stage"] == "PLANNING"
    assert entries[0]["dod_verdict"] == "PASS"
    assert entries[0]["dod_cookie"] == "[3/3]"
    assert entries[0]["dod_checkboxes"] == ["ticked", "ticked", "na"]
    assert entries[1]["stage"] == "ITERATING"
    assert entries[1]["dod_verdict"] == "PENDING"
    assert entries[1]["dod_checkboxes"] == ["open", "open", "open"]

    # set_dod_verdict: PASS on UNSATISFIABLE-shape body should fail.
    try:
        set_dod_verdict(sample, new_verdict="PASS", when="2026-05-20 Wed 12:00")
    except DodConsistencyError as exc:
        p(f"PASS-with-open rejected (expected): {exc}")
    else:
        raise AssertionError("PASS with open boxes should have raised")

    # set_dod_verdict: tick all then flip to PASS.
    ticked = sample.replace("- [ ] A.", "- [X] A.") \
                   .replace("- [ ] B.", "- [X] B.") \
                   .replace("- [ ] C.", "- [-] C.")
    flipped = set_dod_verdict(ticked, new_verdict="PASS", when="2026-05-20 Wed 12:00")
    assert "**** [3/3] PASS DoD" in flipped, flipped
    assert "CLOSED: [2026-05-20 Wed 12:00]" in flipped
    assert 'State "PASS"' in flipped
    p("PASS flip ok")

    # set_dod_verdict: UNSATISFIABLE on all-ticked body should fail.
    try:
        set_dod_verdict(flipped, new_verdict="UNSATISFIABLE", when="2026-05-20 Wed 12:10")
    except DodConsistencyError as exc:
        p(f"UNSATISFIABLE-all-ticked rejected (expected): {exc}")
    else:
        raise AssertionError("UNSATISFIABLE with all ticked should have raised")

    # append_log_entry_skeleton: append a MERGING entry.
    appended = append_log_entry_skeleton(
        flipped, stage="MERGING", via="/advance", prev_stage="ITERATING",
        when="2026-05-20 Wed 13:00",
    )
    # The prior ITERATING entry should now carry :EXITED: and :DURATION:.
    assert ":EXITED:      [2026-05-20 Wed 13:00]" in appended, appended
    assert ":DURATION:    1h 30m" in appended, appended
    # The new MERGING entry should be present with a PENDING DoD.
    assert "*** [2026-05-20 Wed 13:00] MERGING (via /advance from ITERATING)" in appended
    assert "PENDING DoD" in appended
    p("skeleton append ok")

    # mark_plan_approved: tick the canonical bullet on an open PLANNING
    # entry; recompute the cookie; preserve the verdict keyword.
    planning_sample = """\
#+TITLE: t
#+TODO: PLANNING ITERATING | COMPLETE
#+TODO: PENDING UNSATISFIABLE | PASS

* PLANNING title :user:
  :PROPERTIES:
  :ID: t
  :END:

** Log
*** [2026-05-20 Wed 10:00] PLANNING (via /promote)
    :PROPERTIES:
    :STAGE:       PLANNING
    :ENTERED:     [2026-05-20 Wed 10:00]
    :ENTERED_VIA: /promote
    :END:
**** Request
**** Work
**** [0/3] PENDING DoD
     - [ ] The plan is written into the task's org file.
     - [ ] The user has approved the plan.
     - [ ] A draft PR has been created on GitHub.
"""
    ticked_planning = mark_plan_approved(planning_sample)
    assert "- [X] The user has approved the plan." in ticked_planning, ticked_planning
    assert "**** [1/3] PENDING DoD" in ticked_planning, ticked_planning
    # Other bullets untouched.
    assert "- [ ] The plan is written into the task's org file." in ticked_planning
    assert "- [ ] A draft PR has been created on GitHub." in ticked_planning
    p("mark_plan_approved tick ok")

    # mark_plan_approved: no-op on an already-ticked entry.
    again = mark_plan_approved(ticked_planning)
    assert again == ticked_planning, "second tick should be a no-op"
    p("mark_plan_approved already-ticked no-op ok")

    # mark_plan_approved: no-op when the latest entry is not PLANNING.
    # `sample` (defined above) has PLANNING (PASS, closed) then ITERATING
    # as the latest entry — even though PLANNING is present, the latest
    # is ITERATING, so nothing should change.
    non_planning_result = mark_plan_approved(sample)
    assert non_planning_result == sample, "no-op when latest is not PLANNING"
    p("mark_plan_approved non-PLANNING latest no-op ok")

    # mark_plan_approved: no-op when the canonical bullet text is absent
    # (a user customized the bullet wording).
    customized = planning_sample.replace(
        "- [ ] The user has approved the plan.",
        "- [ ] User has signed off on the plan.",
    )
    custom_result = mark_plan_approved(customized)
    assert custom_result == customized, "no-op when bullet text differs"
    p("mark_plan_approved missing-bullet no-op ok")

    sys.stdout.write(out.getvalue())
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_smoke())
