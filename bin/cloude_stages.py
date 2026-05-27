"""Single source of truth for the cloude workflow stage model.

Every consumer that needs to know "what are the stages" / "what's the
next state" / "what's the Definition of Done for stage X" / "what's the
dashboard sort order" derives from `WORKFLOW` here, instead of
re-declaring its own copy of the keyword list, the in-flight subset,
the terminal subset, the dashboard ordering, or the DoD bullets.

The model:

- `Stage` — a frozen dataclass capturing one stage's identity and
  behavior: its keyword, terminal-ness, default heading tag, whether
  it auto-hands-back the ball at end of turn, its dashboard ordering,
  its DoD bullets, and the org-mode fast-key + log-style it carries
  in `#+TODO:` directives.
- `WORKFLOW: tuple[Stage, ...]` — the ordered list of stages, in the
  forward-transition order the agent walks (PLANNING → ITERATING →
  REVIEW → MERGING → COMPLETE | DROPPED).
- `BY_NAME: dict[str, Stage]` — lookup by keyword.
- Helper functions (`keyword_list`, `in_flight`, `terminal`,
  `auto_handback`, `dashboard_order_map`, `next_stage`,
  `transition_via`, `todo_directive`, `default_tag`, `dod_for`,
  `starting_stage`) — for consumers that don't want to walk the
  `WORKFLOW` tuple by hand.

Machine consumers (the skeleton appender, the stop hook, the
`/advance` skill via `bin/cloude-stages dod <STAGE>`) all read the
bullets from this module, so the on-disk DoD checkboxes and the
checklist `/advance` evaluates are guaranteed to match. `CLAUDE.md`'s
`#### <STAGE>` sections mirror the bullets as human-facing reference
prose; keep them aligned by hand. `tasks/TEMPLATE.org`'s `#+TODO:`
line is the one artifact that's machine-load-bearing — it's parsed by
org-mode when humans open task files — so the wider test suite
exercises `todo_directive()` against it indirectly via the fixture
in `tests/conftest.py` (which renders task files using the same
helper).

Importable directly: `from cloude_stages import WORKFLOW, in_flight`.
The `uv run --script` helpers (`cloude-dash`, `cloude-list-active`,
`cloude-task-info`, the new `cloude-stages` CLI) add this directory
to `sys.path` so they can `from cloude_stages import ...` without
changing their launch model.
"""

from __future__ import annotations

from dataclasses import dataclass


# The who-has-the-ball heading tags, in priority order. When multiple
# coexist on a heading (a misconfigured state), the first one in this
# tuple wins. Mirrored as `cloude_org.BALL_TAGS` for back-compat.
BALL_TAGS: tuple[str, ...] = ("agent", "user", "blocked")


@dataclass(frozen=True)
class Stage:
    """One workflow stage's identity and behavior.

    Fields:
      name             — the TODO keyword as it appears on headings.
      terminal         — true for COMPLETE / DROPPED; nothing transitions
                         out of these.
      default_tag      — the per-stage default who-has-the-ball tag.
                         Used by `/advance`, `/iterate`, `/drop` when
                         the caller doesn't pass `--tag`.
      auto_handback    — true when end-of-turn `:agent:` is flipped to
                         `:user:` automatically (PLANNING, ITERATING).
                         False for REVIEW (default `:blocked:`) and
                         MERGING (agent-driven, owned by /babysit-merge).
      dashboard_order  — sort priority for `cloude-dash` /
                         `cloude-list-active` active-tasks lists; lower
                         numbers sort first. None excludes the stage
                         from active-task ordering (COMPLETE, DROPPED).
      dod_bullets      — Definition-of-Done bullets, mirrored as the
                         human-facing copy under CLAUDE.md's
                         `#### <STAGE>` → "Definition of done" section.
      org_key          — single-character fast key for the `#+TODO:`
                         directive (the `p` in `PLANNING(p!)`).
      org_log_style    — `!` (record state change with timestamp) or
                         `@` (record state change with note) — the
                         character after `org_key` in `#+TODO:`.
    """

    name: str
    terminal: bool
    default_tag: str
    auto_handback: bool
    dashboard_order: int | None
    dod_bullets: tuple[str, ...]
    org_key: str
    org_log_style: str


# The workflow itself. Edit here, in order: that's the canonical
# transition order. CLAUDE.md's "Stage details" prose mirrors the DoD
# bullets as the human-facing copy; the drift test asserts they match.
WORKFLOW: tuple[Stage, ...] = (
    Stage(
        name="PLANNING",
        terminal=False,
        default_tag="agent",
        auto_handback=True,
        dashboard_order=3,
        dod_bullets=(
            "The plan is written into the task's org file.",
            "The user has approved the plan.",
            "A draft PR has been created on GitHub.",
        ),
        org_key="p",
        org_log_style="!",
    ),
    Stage(
        name="ITERATING",
        terminal=False,
        default_tag="agent",
        auto_handback=True,
        dashboard_order=2,
        dod_bullets=(
            "The plan is implemented in code.",
            "All user requests are implemented in code.",
            "New and relevant tests pass locally.",
            "Changes are committed and pushed.",
            "CI tests are passing, or any failures can be attributed to irrelevant flakes.",
            "The PR title and description on GitHub reflect the final change (not the draft-PR placeholder), and the description carries no Test Plan / Verification section.",
        ),
        org_key="i",
        org_log_style="!",
    ),
    Stage(
        name="REVIEW",
        terminal=False,
        default_tag="blocked",
        auto_handback=False,
        dashboard_order=1,
        dod_bullets=(
            "The PR has been reviewed.",
        ),
        org_key="r",
        org_log_style="!",
    ),
    Stage(
        name="MERGING",
        terminal=False,
        default_tag="agent",
        auto_handback=False,
        dashboard_order=0,
        dod_bullets=(
            "The PR is merged.",
        ),
        org_key="m",
        org_log_style="!",
    ),
    Stage(
        name="COMPLETE",
        terminal=True,
        default_tag="user",
        auto_handback=False,
        dashboard_order=None,
        dod_bullets=(
            "The task file has TODO state `COMPLETE` and tag `:user:`.",
        ),
        org_key="c",
        org_log_style="!",
    ),
    Stage(
        name="DROPPED",
        terminal=True,
        default_tag="user",
        auto_handback=False,
        dashboard_order=None,
        dod_bullets=(
            "The task file has TODO state `DROPPED` and tag `:user:`.",
        ),
        org_key="x",
        org_log_style="@",
    ),
)


BY_NAME: dict[str, Stage] = {s.name: s for s in WORKFLOW}


# ---------------------------------------------------------------------------
# Derived constants
# ---------------------------------------------------------------------------

# The canonical text of the PLANNING DoD bullet that records the user's
# approval of the plan. `cloude_org.mark_plan_approved` matches against
# this exact string so it can be ticked automatically when the user
# triggers any transition out of PLANNING (the trigger itself is the
# approval).
PLAN_APPROVED_BULLET: str = BY_NAME["PLANNING"].dod_bullets[1]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def keyword_list() -> tuple[str, ...]:
    """Return every stage keyword in workflow order."""
    return tuple(s.name for s in WORKFLOW)


def in_flight() -> tuple[str, ...]:
    """Return the non-terminal stage keywords, in workflow order."""
    return tuple(s.name for s in WORKFLOW if not s.terminal)


def terminal() -> tuple[str, ...]:
    """Return the terminal stage keywords (COMPLETE, DROPPED)."""
    return tuple(s.name for s in WORKFLOW if s.terminal)


def auto_handback() -> tuple[str, ...]:
    """Return the stages whose end-of-turn `:agent:` flips to `:user:`."""
    return tuple(s.name for s in WORKFLOW if s.auto_handback)


def dashboard_order_map() -> dict[str, int]:
    """Return {stage: priority} for active-task sort; terminals omitted.

    Used by `cloude-dash` and `cloude-list-active`. Lower priority sorts
    first (MERGING=0, REVIEW=1, ITERATING=2, PLANNING=3).
    """
    return {s.name: s.dashboard_order for s in WORKFLOW if s.dashboard_order is not None}


def default_tag(stage: str) -> str:
    """Return the per-stage default who-has-the-ball tag.

    Raises KeyError on an unknown stage.
    """
    return BY_NAME[stage].default_tag


def dod_for(stage: str) -> tuple[str, ...]:
    """Return the DoD bullets for `stage`. Raises KeyError on an unknown stage."""
    return BY_NAME[stage].dod_bullets


def next_stage(current: str, *, skip_review: bool = False) -> str | None:
    """Return the next stage keyword for a forward transition, or None.

    Walks `WORKFLOW` order; the special case is `skip_review`: when true
    and the current stage is ITERATING, the next stage is MERGING (the
    REVIEW stage is bypassed entirely).

    Returns None when:
      - `current` is a terminal stage (nothing transitions out of it),
      - `current` is the last in-flight stage (MERGING) — its forward
        edge is into the terminals, which is per-keyword (COMPLETE
        for normal exit, DROPPED for abandon); use that knowledge in
        the caller instead.

    Raises KeyError on an unknown stage.
    """
    if current not in BY_NAME:
        raise KeyError(current)
    if BY_NAME[current].terminal:
        return None
    if current == "ITERATING" and skip_review:
        return "MERGING"
    # Find the index of `current` in WORKFLOW and return the next
    # non-terminal stage (skipping COMPLETE / DROPPED, which are
    # alternates, not a linear successor).
    names = [s.name for s in WORKFLOW]
    idx = names.index(current)
    for s in WORKFLOW[idx + 1:]:
        if not s.terminal:
            return s.name
    # We're past the last in-flight stage (MERGING). The caller picks
    # COMPLETE explicitly for a successful merge; DROPPED is reachable
    # only via /drop.
    return "COMPLETE"


def transition_via(prev: str, new: str) -> str:
    """Return the default `:ENTERED_VIA:` text for a stage transition.

    `/drop` for any move into DROPPED; `/iterate` for a backward move
    (lower index in WORKFLOW than the previous); `/advance` for a
    forward move. Used by `cloude-task-set-state` when `--via` isn't
    passed explicitly.
    """
    if new == "DROPPED":
        return "/drop"
    names = [s.name for s in WORKFLOW]
    # Defensive: unknown stages get treated as "forward" (advance).
    prev_idx = names.index(prev) if prev in names else -1
    new_idx = names.index(new) if new in names else len(names)
    if new_idx < prev_idx:
        return "/iterate"
    return "/advance"


def todo_directive() -> str:
    """Render the canonical `#+TODO:` line for task files.

    Format mirrors org-mode's standard: in-flight keywords first, then
    a `|` separator, then the done states. Each keyword carries its
    fast-key + log-style in parens, e.g. `PLANNING(p!)`. The whole line
    is a single source for `tasks/TEMPLATE.org`; the drift test asserts
    the on-disk template matches what this returns.
    """
    todos: list[str] = []
    dones: list[str] = []
    for s in WORKFLOW:
        token = f"{s.name}({s.org_key}{s.org_log_style})"
        if s.terminal:
            dones.append(token)
        else:
            todos.append(token)
    return "#+TODO: " + " ".join(todos) + " | " + " ".join(dones)


def starting_stage(promote_mode: str) -> str:
    """Return the initial stage for a freshly-promoted task.

    `cloude-promote-setup` calls this so its mode -> stage choice isn't
    a hardcoded shell `if`. Modes:
      - `"standard"` — the agent plans first; start in PLANNING.
      - `"adopt"`    — adopting an existing PR; start in ITERATING.
    Unknown modes raise ValueError.
    """
    if promote_mode == "standard":
        return "PLANNING"
    if promote_mode == "adopt":
        return "ITERATING"
    raise ValueError(f"unknown promote mode: {promote_mode!r}")
