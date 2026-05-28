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

Read side uses `orgparse`; writers use regex.

The hook scripts that import this module (`cloude-on-stop`,
`cloude-on-user-prompt`, `cloude-on-user-question`,
`cloude-on-plan-accepted`, `cloude-task-set-state`) are re-exec'd
through `bin/cloude-python` via an sh/Python polyglot shebang, so
they run under the shared cloude venv built from the repo-root
`pyproject.toml` + `uv.lock`. `import orgparse` is free here, and
the read-only parsers (`parse_heading`, the staging-entry locator
in `remove_staging_entry`, the `** Plan`-section probe used by
`cloude-on-plan-accepted`) use it.

The log-entry editor (`find_log_section`, `iter_log_entries`,
`mark_plan_approved`, `append_log_entry_skeleton`, `set_dod_verdict`,
`_stamp_exited_duration`) and the heading rewriter in
`cloude-task-set-state` stay on regex: they all need byte/line
ranges per node so they can splice replacements back into the file,
and `orgparse` doesn't expose those ranges. Template rendering in
`render_task_from_template` is also regex — it substitutes
placeholders in a known string template, not parsing org grammar.
"""

from __future__ import annotations

import datetime as _dt
import re
import textwrap
from pathlib import Path

import orgparse

# The workflow stage model — keyword list, per-stage DoD bullets,
# who-has-the-ball tag defaults, transition map — lives in the
# sibling `cloude_stages` module so every consumer (this module, the
# hook scripts, the dashboard, the slash commands via the
# `cloude-stages` CLI) derives from one place. STAGE_KEYWORDS /
# STAGE_DOD / BALL_TAGS / PLAN_APPROVED_BULLET are re-exported here
# for back-compat with existing importers; new code should import
# directly from `cloude_stages`.
from types import MappingProxyType  # noqa: E402

from cloude_stages import (  # noqa: E402
    BALL_TAGS,
    PLAN_APPROVED_BULLET,
    WORKFLOW,
    in_flight as _stages_in_flight,
    keyword_list as _stages_keyword_list,
    terminal as _stages_terminal,
)

# The cloude stage-keyword sequence, in workflow order. Re-exported
# from `cloude_stages.keyword_list()`.
STAGE_KEYWORDS: tuple[str, ...] = _stages_keyword_list()

# DoD-verdict keywords for the secondary `#+TODO:` sequence inside
# the per-stage `** Log` entries. Kept here (not in `cloude_stages`)
# because it's tied to the log-entry schema this module owns, not to
# the workflow itself.
DOD_KEYWORDS = ("PENDING", "UNSATISFIABLE", "PASS")

# Per-stage Definition-of-Done bullets. Read-only view onto the
# `cloude_stages.WORKFLOW` registry so callers indexing
# `STAGE_DOD["ITERATING"]` keep working. The bullets are owned by
# `cloude_stages`; CLAUDE.md's "Stage details" sections mirror them
# as human-facing reference prose. Machine consumers — this map and
# `/advance` via `bin/cloude-stages dod <STAGE>` — all read from the
# model directly, so CLAUDE.md drift is a documentation lag rather
# than a correctness bug.
STAGE_DOD: MappingProxyType[str, tuple[str, ...]] = MappingProxyType(
    {s.name: s.dod_bullets for s in WORKFLOW}
)


def _org_env(filename: str = "<cloude-task>") -> orgparse.OrgEnv:
    """Return an `OrgEnv` preloaded with the cloude TODO keywords.

    `orgparse` only recognizes TODO keywords it's been told about. A
    well-formed task file has the `#+TODO:` directive at the top so
    the parser self-bootstraps, but the unit tests feed bare-heading
    fixtures (no directive) and the hook scripts get called against
    files of varying completeness. Seeding the env with the keyword
    list keeps `node.todo` reliable across both.
    """
    return orgparse.OrgEnv(
        todos=list(_stages_in_flight()),  # PLANNING / ITERATING / REVIEW / MERGING
        dones=list(_stages_terminal()),   # COMPLETE / DROPPED
        filename=filename,
    )


def _load_org(content: str) -> orgparse.node.OrgRootNode:
    """`orgparse.loads(content)` with the cloude TODO sequence preloaded.

    `filename` matters only because `OrgEnv.__init__` requires it to
    match `loads(filename=...)`; we use a sentinel.
    """
    return orgparse.loads(content, env=_org_env(), filename="<cloude-task>")


def parse_heading(content: str) -> tuple[str, list[str]] | None:
    """Find the first top-level heading; return (TODO keyword, [tag names]).

    `content` is the full text of a task `.org` file. The tag list is
    sorted alphabetically (`orgparse` exposes tags as an unordered
    set; consumers — `ball_tag` and the hook scripts — only need
    membership, so a stable order is enough). Returns None when no
    top-level heading is found, or when the heading is missing a TODO
    keyword (which a well-formed task file should never be).
    """
    root = _load_org(content)
    for node in root[1:]:
        if node.level == 1:
            todo = (node.todo or "").strip()
            if not todo:
                return None
            return todo, sorted(node.tags)
    return None


def ball_tag(tags: list[str]) -> str:
    """Return the who-has-the-ball tag from a parsed tag list, or ''.

    `tags` is the list returned by `parse_heading`. If several tags are
    present, the first of agent/user/blocked (in `BALL_TAGS` order)
    wins.
    """
    return next((t for t in BALL_TAGS if t in tags), "")


def has_level2_section(content: str, name: str) -> bool:
    """True when `content` has a level-2 heading whose text starts with `name`.

    Used by `cloude-on-plan-accepted` to decide between inserting and
    replacing a `** Plan` section without resorting to a regex probe.
    """
    root = _load_org(content)
    for node in root[1:]:
        if node.level == 2 and str(node.heading).strip().startswith(name):
            return True
    return False


def remove_staging_entry(content: str, heading_text: str) -> tuple[str, str]:
    """Remove a level-2 sub-heading + body from `staging.org` content.

    `heading_text` is matched against the heading text *without* tags
    (`orgparse`'s `node.heading` strips the trailing `:tag:chain:`
    for us). The returned tuple is `(new_content, body_text)`:

    - `new_content`: `content` with the matching entry's heading line
      and every line after it through the line just before the next
      level-≤2 heading (or end of file) removed.
    - `body_text`: the entry's body with its `:PROPERTIES:` drawer
      stripped (`get_body()` does this for us), dedented, and
      surrounding blank lines trimmed. Empty when the entry has only
      a heading. Suitable for stuffing into a prefill prompt.

    Raises `ValueError` when no level-2 heading matches `heading_text`.
    """
    root = _load_org(content)
    nodes = list(root[1:])
    target_idx: int | None = None
    for i, node in enumerate(nodes):
        if node.level == 2 and str(node.heading).strip() == heading_text.strip():
            target_idx = i
            break
    if target_idx is None:
        raise ValueError(f"heading not found: {heading_text!r}")

    target = nodes[target_idx]
    start_lineno = target.linenumber  # 1-based, points at the `** ...` line

    end_lineno: int | None = None
    for node in nodes[target_idx + 1:]:
        if node.level <= 2:
            end_lineno = node.linenumber  # 1-based, points at the next heading
            break

    lines = content.splitlines(keepends=True)
    if end_lineno is None:
        end_lineno = len(lines) + 1

    new_lines = lines[: start_lineno - 1] + lines[end_lineno - 1:]
    new_content = "".join(new_lines)

    raw_body = target.get_body() or ""
    body_text = textwrap.dedent(raw_body).strip("\n")

    return new_content, body_text


# Validation for slug values written into staging-idea drawers via
# `set_idea_slug` / `bin/cloude-set-staging-slug`. Same shape `/promote`
# expects: starts and ends with [a-z0-9], hyphens allowed in the middle.
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
SLUG_MAX_LEN = 80


def derive_slug(heading: str) -> str:
    """Reduce a heading to a filesystem-safe slug.

    Lowercase, replace any non-alphanumeric run with `-`, trim
    leading/trailing dashes. Shared by `cloude-promote` (idea slugs)
    and `cloude-list-staging` (vault slugs when no `:SLUG:` is set on
    the level-1 heading), so both apply the same rule.
    """
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")


class SlugClobberError(ValueError):
    """Raised by `set_idea_slug` when an existing `:SLUG:` would be overwritten.

    The watcher / `/suggest-slugs` flow never overwrites a slug the user
    has hand-edited: an idea with `:SLUG:` set to something other than
    the empty string (which means "please suggest one") wins over the
    LLM-generated suggestion. An empty existing `:SLUG:` is *replaced*,
    not clobbered.
    """


def set_idea_slug(content: str, heading_text: str, slug: str) -> str:
    """Set the `:SLUG:` property on a level-2 idea heading.

    `heading_text` matches the same way as `remove_staging_entry`:
    against the heading text without its tag chain, exact match after
    `strip()`. Returns new file content, or `content` unchanged when
    the idea already carries the same slug.

    Behavior matrix:
    - No drawer under the heading → insert one with `:SLUG: <slug>`
      using a 3-space indent (the README convention for level-2
      idea drawers).
    - Drawer present, no `:SLUG:` line → insert one just before
      `:END:`, matching the drawer's existing indent.
    - Drawer present, empty `:SLUG:` (the "please suggest" sentinel) →
      replace with `<slug>`.
    - Drawer present, `:SLUG: <slug>` already → no-op.
    - Drawer present, `:SLUG: <other>` → raise `SlugClobberError`.

    Raises `ValueError` when no level-2 heading matches `heading_text`.
    """
    root = _load_org(content)
    nodes = list(root[1:])
    target_idx: int | None = None
    for i, node in enumerate(nodes):
        if node.level == 2 and str(node.heading).strip() == heading_text.strip():
            target_idx = i
            break
    if target_idx is None:
        raise ValueError(f"heading not found: {heading_text!r}")

    target = nodes[target_idx]
    start_lineno = target.linenumber  # 1-based, points at `** …`

    end_lineno: int | None = None
    for node in nodes[target_idx + 1:]:
        if node.level <= 2:
            end_lineno = node.linenumber
            break

    lines = content.splitlines(keepends=True)
    if end_lineno is None:
        end_lineno = len(lines) + 1

    heading_idx = start_lineno - 1  # 0-based index of the `** …` line
    body_slice = slice(heading_idx + 1, end_lineno - 1)
    body_lines = lines[body_slice]

    # Drawer must be the first non-blank thing under the heading.
    j = 0
    while j < len(body_lines) and body_lines[j].strip() == "":
        j += 1
    drawer_open_local: int | None = None
    drawer_end_local: int | None = None
    if j < len(body_lines) and body_lines[j].strip().upper() == ":PROPERTIES:":
        drawer_open_local = j
        for k in range(j + 1, len(body_lines)):
            if body_lines[k].strip().upper() == ":END:":
                drawer_end_local = k
                break

    if drawer_open_local is not None and drawer_end_local is not None:
        # Drawer found. Look for an existing :SLUG: line.
        for li in range(drawer_open_local + 1, drawer_end_local):
            m = re.match(r"^(\s*):SLUG:\s*(.*?)\s*$", body_lines[li])
            if m is None:
                continue
            existing = m.group(2).strip()
            if existing == slug:
                return content
            if existing == "":
                indent = m.group(1)
                rewritten = f"{indent}:SLUG: {slug}\n"
                abs_idx = heading_idx + 1 + li
                new_lines = lines[:abs_idx] + [rewritten] + lines[abs_idx + 1:]
                return "".join(new_lines)
            raise SlugClobberError(
                f"idea {heading_text!r} already has :SLUG: {existing!r}; "
                f"refusing to overwrite with {slug!r}"
            )
        # No :SLUG: in drawer — insert before :END: with the drawer's indent.
        indent_match = re.match(r"^(\s*)", body_lines[drawer_open_local])
        indent = indent_match.group(1) if indent_match else "   "
        new_line = f"{indent}:SLUG: {slug}\n"
        abs_end = heading_idx + 1 + drawer_end_local
        new_lines = lines[:abs_end] + [new_line] + lines[abs_end:]
        return "".join(new_lines)

    # No drawer — synthesise one immediately under the heading.
    indent = "   "
    new_drawer = (
        f"{indent}:PROPERTIES:\n"
        f"{indent}:SLUG: {slug}\n"
        f"{indent}:END:\n"
    )
    new_lines = lines[: heading_idx + 1] + [new_drawer] + lines[heading_idx + 1:]
    return "".join(new_lines)


def render_task_from_template(
    template_text: str,
    *,
    todo: str,
    heading: str,
    task_id: str,
    vault: str,
    repo_url: str,
    branch: str,
    worktree: str,
    pr_url: str = "",
    adopted: bool = False,
    skip_review: bool = False,
    companion: str = "",
    notes_prelude: str = "",
) -> str:
    """Return `template_text` with TEMPLATE.org placeholders filled in.

    Regex substitution (not org parsing): the template is a known
    string layout, and the placeholders are anchored to it.
    `:ADOPTED:`, `:SKIP_REVIEW:`, and `:COMPANION:` are inserted just
    before the properties drawer's `:END:` line when the corresponding
    flag/value is set, matching the order the old inline heredoc in
    `cloude-promote-setup` produced. `notes_prelude`, when set, is
    inserted as the first body line under `** Notes`.
    """
    text = template_text

    # 48 spaces of padding between heading and `:user:`; matches what
    # the previous inline heredoc produced. Long headings push the tag
    # past column 80; that's the existing behavior, preserved here.
    text = re.sub(
        r"^\* PLANNING <task title>\s+:user:\s*$",
        f"* {todo} {heading}" + " " * 48 + ":user:",
        text,
        count=1,
        flags=re.M,
    )

    text = text.replace("#+TITLE: <task title>", f"#+TITLE: {heading}", 1)

    text = re.sub(
        r"^(\s*:ID:\s+).*$", rf"\g<1>{task_id}", text, count=1, flags=re.M
    )
    text = re.sub(
        r"^(\s*:VAULT:\s+).*$", rf"\g<1>{vault}", text, count=1, flags=re.M
    )
    text = re.sub(
        r"^(\s*:REPO:\s+).*$", rf"\g<1>{repo_url}", text, count=1, flags=re.M
    )
    text = re.sub(
        r"^(\s*:BRANCH:\s*)$", rf"\g<1>{branch}", text, count=1, flags=re.M
    )
    text = re.sub(
        r"^(\s*:WORKTREE:\s*)$", rf"\g<1>{worktree}", text, count=1, flags=re.M
    )
    text = re.sub(
        r"^(\s*:PR:\s*)$", rf"\g<1>{pr_url}", text, count=1, flags=re.M
    )

    # Optional drawer entries — inserted just before `:END:`, in the
    # same order the previous heredoc produced.
    inserts: list[str] = []
    if adopted:
        inserts.append("  :ADOPTED:  t")
    if skip_review:
        inserts.append("  :SKIP_REVIEW:  t")
    if companion:
        inserts.append(f"  :COMPANION: {companion}")
    for line in inserts:
        text = re.sub(
            r"^(\s*:END:\s*)$",
            line + "\n" + r"\g<1>",
            text,
            count=1,
            flags=re.M,
        )

    if notes_prelude:
        text = re.sub(
            r"^(\*\* Notes\s*)$",
            r"\g<1>\n   " + notes_prelude.replace("\\", "\\\\"),
            text,
            count=1,
            flags=re.M,
        )

    return text


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
