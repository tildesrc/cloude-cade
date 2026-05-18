"""Shared loader for the cloude workflow definition.

The workflow "state machine" — its stages, transitions, definitions of
done, responsibilities, and who-has-the-ball tags — lives in a single
machine-parseable TOML file under `workflows/`. This module is the one
place that file is parsed; every hook, helper, and generator that needs
to know the workflow imports `load()` from here so they cannot drift
apart.

Why a stdlib-only module?

Claude Code's hook runner executes `bin/cloude-on-*` directly via their
`#!/usr/bin/env python3` shebang — not through `uv` — so they run on
plain stdlib `python3` with no dependency resolution. Any module a hook
imports inherits that constraint. TOML is parsed with `tomllib`, in the
standard library since Python 3.11 (the version shipped in the cloude
container); no third-party dependency is needed.

Repo-wide single active workflow: `workflows/active` is a one-line
pointer naming the active workflow (e.g. `default`). `load()` resolves
it; pass `name=` to load a specific workflow regardless, or `root=` to
point at a different cloude checkout (used by the test suite).
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# This module always lives at <cloude-root>/bin/cloude_workflow.py, so
# the repo root is two parents up — no env var or cwd assumption needed.
_DEFAULT_ROOT = Path(__file__).resolve().parent.parent


class WorkflowError(Exception):
    """Raised when a workflow definition is missing or malformed."""


def flatten(text: str) -> str:
    """Collapse internal whitespace runs (incl. newlines) to single spaces.

    Responsibilities and DoD bullets are stored in the definition with
    the line wrapping CLAUDE.md uses, so generation reproduces the doc
    verbatim. Consumers that want a single-line bullet (the hooks, the
    `cloude-workflow` CLI) call this to un-wrap.
    """
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class State:
    """One workflow stage."""

    name: str
    kind: str  # "in-flight" | "terminal"
    org_shortcut: str
    default_tag: str
    responsibilities: tuple[str, ...]
    definition_of_done: tuple[str, ...]
    order: int | None = None
    doc_prose: str = ""
    skipped_when: str = ""
    forward: dict | None = None  # {"next": str, "driver": str, "conditional": [...]}
    auto_advance: dict | None = None  # {"trigger", "to", "tag"}

    @property
    def is_terminal(self) -> bool:
        return self.kind == "terminal"

    @property
    def dod_flat(self) -> tuple[str, ...]:
        """Definition-of-done bullets un-wrapped to single lines."""
        return tuple(flatten(b) for b in self.definition_of_done)

    @property
    def responsibilities_flat(self) -> tuple[str, ...]:
        return tuple(flatten(b) for b in self.responsibilities)


@dataclass
class Workflow:
    """A parsed workflow definition."""

    name: str
    description: str
    states: dict[str, State]
    ball_tags: tuple[dict, ...]
    docs: dict
    roles: dict
    promote: dict
    _order: list[str] = field(default_factory=list)

    # --- state collections ------------------------------------------------

    @property
    def state_names(self) -> list[str]:
        """State names in definition order."""
        return list(self._order)

    @property
    def in_flight(self) -> list[str]:
        """In-flight (non-terminal) state names, in definition order."""
        return [n for n in self._order if not self.states[n].is_terminal]

    @property
    def terminal(self) -> list[str]:
        """Terminal state names, in definition order."""
        return [n for n in self._order if self.states[n].is_terminal]

    @property
    def ball_tag_names(self) -> tuple[str, ...]:
        return tuple(t["name"] for t in self.ball_tags)

    @property
    def stage_order(self) -> dict[str, int]:
        """Dashboard sort priority, in-flight states only."""
        return {
            n: self.states[n].order
            for n in self._order
            if self.states[n].order is not None
        }

    @property
    def todo_line(self) -> str:
        """The org `#+TODO:` keyword line (without the `#+TODO: ` prefix)."""
        active = " ".join(
            f"{n}({self.states[n].org_shortcut})" for n in self.in_flight
        )
        done = " ".join(
            f"{n}({self.states[n].org_shortcut})" for n in self.terminal
        )
        return f"{active} | {done}"

    # --- transitions ------------------------------------------------------

    def next_state(self, current: str, skip_review: bool = False) -> str | None:
        """The forward state from `current`, honoring conditional overrides.

        Returns None for a terminal state (nothing to advance to). Raises
        WorkflowError for an unknown state name.
        """
        st = self._require(current)
        if st.forward is None:
            return None
        if skip_review:
            for cond in st.forward.get("conditional", []):
                if cond.get("when") == "skip_review":
                    return cond["next"]
        return st.forward["next"]

    def forward_driver(self, state: str) -> str | None:
        """'user' or 'agent' — who drives the forward transition, or None."""
        st = self._require(state)
        return None if st.forward is None else st.forward.get("driver")

    def default_tag(self, state: str) -> str:
        return self._require(state).default_tag

    def dod(self, state: str) -> tuple[str, ...]:
        """Verbatim definition-of-done bullets (CLAUDE.md wrapping kept)."""
        return self._require(state).definition_of_done

    def responsibilities(self, state: str) -> tuple[str, ...]:
        return self._require(state).responsibilities

    @property
    def auto_advance(self) -> dict | None:
        """The plan-accepted auto-advance, as {"from", "to", "tag"}, or None."""
        for name in self._order:
            st = self.states[name]
            if st.auto_advance and st.auto_advance.get("trigger") == "plan_accepted":
                return {
                    "from": name,
                    "to": st.auto_advance["to"],
                    "tag": st.auto_advance["tag"],
                }
        return None

    def promote_initial(self, mode: str) -> str:
        """The starting state /promote uses for the given mode."""
        try:
            return self.promote[mode]
        except KeyError:
            raise WorkflowError(
                f"workflow {self.name!r}: no promote initial state for "
                f"mode {mode!r} (known: {', '.join(sorted(self.promote))})"
            ) from None

    def role(self, name: str) -> str:
        """The state playing a named role (e.g. 'iterate', 'drop')."""
        try:
            return self.roles[name]
        except KeyError:
            raise WorkflowError(
                f"workflow {self.name!r}: no state for role {name!r} "
                f"(known: {', '.join(sorted(self.roles))})"
            ) from None

    def _require(self, state: str) -> State:
        try:
            return self.states[state]
        except KeyError:
            raise WorkflowError(
                f"workflow {self.name!r}: unknown state {state!r} "
                f"(known: {', '.join(self._order)})"
            ) from None


# --- loading -----------------------------------------------------------------


def active_workflow_name(root: Path | None = None) -> str:
    """Read the repo-wide active-workflow pointer (`workflows/active`)."""
    root = root or _DEFAULT_ROOT
    pointer = root / "workflows" / "active"
    if pointer.is_file():
        name = pointer.read_text().strip()
        if name:
            return name
    return "default"


def load(name: str | None = None, root: Path | None = None) -> Workflow:
    """Load a workflow definition.

    `name` defaults to the repo-wide active workflow. `root` defaults to
    the cloude checkout this module lives in (override for tests).
    """
    root = root or _DEFAULT_ROOT
    if name is None:
        name = active_workflow_name(root)

    path = root / "workflows" / f"{name}.toml"
    if not path.is_file():
        raise WorkflowError(f"workflow definition not found: {path}")

    try:
        raw = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise WorkflowError(f"workflow {name!r}: malformed TOML: {exc}") from exc

    return _build(name, raw)


def _build(name: str, raw: dict) -> Workflow:
    if "states" not in raw or not raw["states"]:
        raise WorkflowError(f"workflow {name!r}: no [[states]] defined")

    states: dict[str, State] = {}
    order: list[str] = []
    for entry in raw["states"]:
        st = _build_state(name, entry)
        if st.name in states:
            raise WorkflowError(f"workflow {name!r}: duplicate state {st.name!r}")
        states[st.name] = st
        order.append(st.name)

    # Every forward/auto-advance target must name a real state.
    for st in states.values():
        if st.forward is not None:
            _check_target(name, st.name, st.forward["next"], states)
            for cond in st.forward.get("conditional", []):
                _check_target(name, st.name, cond["next"], states)
        if st.auto_advance is not None:
            _check_target(name, st.name, st.auto_advance["to"], states)

    ball_tags = tuple(raw.get("ball_tags", ()))
    if not ball_tags:
        raise WorkflowError(f"workflow {name!r}: no [[ball_tags]] defined")

    return Workflow(
        name=raw.get("name", name),
        description=raw.get("description", ""),
        states=states,
        ball_tags=ball_tags,
        docs=raw.get("docs", {}),
        roles=raw.get("roles", {}),
        promote=raw.get("promote", {}),
        _order=order,
    )


def _build_state(wf_name: str, entry: dict) -> State:
    for required in ("name", "kind", "org_shortcut", "default_tag"):
        if required not in entry:
            raise WorkflowError(
                f"workflow {wf_name!r}: a [[states]] entry is missing "
                f"required key {required!r}"
            )
    kind = entry["kind"]
    if kind not in ("in-flight", "terminal"):
        raise WorkflowError(
            f"workflow {wf_name!r}: state {entry['name']!r} has invalid "
            f"kind {kind!r} (expected 'in-flight' or 'terminal')"
        )
    return State(
        name=entry["name"],
        kind=kind,
        org_shortcut=entry["org_shortcut"],
        default_tag=entry["default_tag"],
        responsibilities=tuple(entry.get("responsibilities", ())),
        definition_of_done=tuple(entry.get("definition_of_done", ())),
        order=entry.get("order"),
        doc_prose=entry.get("doc_prose", ""),
        skipped_when=entry.get("skipped_when", ""),
        forward=entry.get("forward"),
        auto_advance=entry.get("auto_advance"),
    )


def _check_target(wf_name: str, src: str, target: str, states: dict) -> None:
    if target not in states:
        raise WorkflowError(
            f"workflow {wf_name!r}: state {src!r} transitions to unknown "
            f"state {target!r}"
        )
