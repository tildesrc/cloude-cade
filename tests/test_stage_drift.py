"""Drift tests: hand-authored artifacts agree with cloude_stages.

Two artifacts that humans edit by hand mirror data the model also
owns:

  - ``tasks/TEMPLATE.org``'s ``#+TODO:`` directive — duplicated for
    every promoted task and unsynced after promote, so the model is
    the only place a new keyword can land.
  - ``CLAUDE.md``'s ``#### <STAGE>`` "Definition of done" bullet
    lists — agent-facing copy of ``cloude_stages.WORKFLOW`` DoD text.

Both are guarded here rather than by an "Edit both when a bullet
changes" comment. If you change a stage in the model and forget to
mirror it, these tests fail and tell you exactly which artifact and
which line is stale.

Lint-only on purpose (the PLANNING-time architecture decision): no
generator regenerates the on-disk files; you edit each by hand and
the test catches drift.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cloude_stages import WORKFLOW, dod_for, keyword_list, todo_directive


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ORG = REPO_ROOT / "tasks" / "TEMPLATE.org"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
README_MD = REPO_ROOT / "README.md"


# ---------------------------------------------------------------------------
# tasks/TEMPLATE.org
# ---------------------------------------------------------------------------


def _first_stage_todo_line(content: str) -> str:
    """Return the first `#+TODO:` line that names the stage keywords.

    The template carries two `#+TODO:` lines: the workflow stages and
    the DoD verdict sequence. We want the first (workflow) one. Match
    on the presence of "PLANNING" to disambiguate.
    """
    for line in content.splitlines():
        if line.startswith("#+TODO:") and "PLANNING" in line:
            return line
    raise AssertionError(
        "no workflow #+TODO: line found in tasks/TEMPLATE.org"
    )


class TestTemplateOrgTodoDirective:
    def test_matches_model(self):
        content = TEMPLATE_ORG.read_text()
        on_disk = _first_stage_todo_line(content)
        # If this fails, either regenerate the line via
        # `bin/cloude-stages todo-directive > /tmp/td && grep -v ... `
        # or hand-edit TEMPLATE.org to match `cloude_stages.todo_directive()`.
        assert on_disk == todo_directive()


# ---------------------------------------------------------------------------
# CLAUDE.md Stage details / Definition of done
# ---------------------------------------------------------------------------


# `#### PLANNING` or `#### COMPLETE (terminal)` — capture the bare stage name.
_STAGE_HEADING_RE = re.compile(
    r"^####\s+(?P<name>[A-Z]+)\b.*$", re.M
)


def _parse_claude_md_dod() -> dict[str, list[str]]:
    """Parse CLAUDE.md → {stage: [DoD bullet first-line, ...]}.

    For each `#### <STAGE>` heading, walks to the next `#### ` (or `### `,
    or `## `) and extracts the bullet list under the `**Definition of
    done**` sub-heading. Only the first line of each bullet is kept —
    follow-on prose (e.g. PLANNING's italic "*Auto-ticked*..." paragraph
    or ITERATING's parenthetical) is dropped so the bullet text can be
    matched against the model's terse strings.
    """
    content = CLAUDE_MD.read_text()
    section_starts = [
        (m.start(), m.group("name")) for m in _STAGE_HEADING_RE.finditer(content)
    ]
    # End each section at the next `#### ` or any higher-level heading.
    boundary_re = re.compile(r"^(?:####\s|###\s|##\s)", re.M)
    bullets: dict[str, list[str]] = {}
    for i, (start, name) in enumerate(section_starts):
        # Find this section's end.
        after = start + len(content[start:].splitlines()[0]) + 1
        m = boundary_re.search(content, after)
        end = m.start() if m else len(content)
        section_text = content[start:end]

        # Find `**Definition of done**` and grab the bullet list that
        # follows up to a blank line that's followed by another `**...**`
        # block or a heading.
        dod_match = re.search(
            r"\*\*Definition of done\*\*\s*\n(?P<body>(?:.|\n)*?)"
            r"(?=\n\*\*|\n####\s|\Z)",
            section_text,
        )
        if not dod_match:
            bullets[name] = []
            continue
        dod_body = dod_match.group("body")

        # Each bullet is a line starting with `- ` followed by
        # continuation lines indented two spaces. Take only the first
        # logical line per bullet (everything up to the first `\n` not
        # followed by indent).
        lines = dod_body.splitlines()
        items: list[str] = []
        current: list[str] | None = None
        for line in lines:
            if line.startswith("- "):
                if current is not None:
                    items.append(" ".join(current).strip())
                current = [line[2:].strip()]
            elif current is not None and line.startswith("  "):
                current.append(line.strip())
            elif current is not None and not line.strip():
                # Blank line terminates the list.
                items.append(" ".join(current).strip())
                current = None
                break
        if current is not None:
            items.append(" ".join(current).strip())
        # Keep only the first sentence (up to the first ". ") so trailing
        # *Auto-ticked* notes and (parentheticals) are stripped.
        bullets[name] = [_first_sentence(b) for b in items]
    return bullets


def _first_sentence(text: str) -> str:
    """Return the leading sentence of `text` ending in a period.

    The model's bullets are terse single sentences ending in a period.
    CLAUDE.md's bullets sometimes carry follow-on prose ("*Auto-ticked*
    when..." for PLANNING; "(not the draft-PR placeholder)..." for
    ITERATING). Take everything through the first `.` followed by a
    space or end-of-string so the comparison stays robust.
    """
    text = text.strip()
    # Match up to and including the first period that's followed by a
    # space, a `*` (italics begin), or end of string.
    m = re.match(r"(.*?\.)(?=\s|\*|$)", text)
    return m.group(1).strip() if m else text


@pytest.mark.parametrize("stage", list(keyword_list()))
def test_claude_md_dod_bullets_match_model(stage):
    """Each model DoD bullet must appear as the leading sentence of the
    corresponding CLAUDE.md bullet, in order, with the same count.

    Why first-sentence rather than full-string equality: CLAUDE.md
    embellishes some bullets with follow-on prose (PLANNING's
    *Auto-ticked* note, ITERATING's "(not the draft-PR placeholder)"
    parenthetical). The terse model bullet is what the per-task
    checkbox skeleton uses and what `mark_plan_approved` matches
    against; the richer CLAUDE.md prose stays for human readers.
    """
    on_disk = _parse_claude_md_dod().get(stage, [])
    expected = list(dod_for(stage))
    assert len(on_disk) == len(expected), (
        f"CLAUDE.md `#### {stage}` has {len(on_disk)} DoD bullet(s); "
        f"model has {len(expected)}. Bullets on disk: {on_disk!r}"
    )
    for idx, (got, want) in enumerate(zip(on_disk, expected)):
        assert got == want, (
            f"CLAUDE.md `#### {stage}` DoD bullet {idx} drift:\n"
            f"  on disk : {got!r}\n"
            f"  model   : {want!r}\n"
            f"Update CLAUDE.md or `cloude_stages.WORKFLOW[{stage!r}]`."
        )


# ---------------------------------------------------------------------------
# README.md workflow keyword coverage
# ---------------------------------------------------------------------------


class TestReadmeMentionsEveryStage:
    def test_workflow_states_table_covers_model(self):
        """The README's `## Workflow states` table must include every
        stage the model declares.

        This catches "added a new stage to the model, forgot to update
        the README intro table" — the table's not parsed for
        bullet-by-bullet equality (different layout from CLAUDE.md),
        just for keyword presence.
        """
        # Strip out the mermaid graph block — it lists state names too
        # but in arrow form, which would mask a missing table row.
        content = README_MD.read_text()
        content_no_mermaid = re.sub(
            r"```mermaid.*?```", "", content, flags=re.S
        )
        # Heuristic: each keyword must appear at least once after the
        # `## Workflow states` heading in a table cell (` `<KEYWORD>` `).
        ws_idx = content_no_mermaid.find("## Workflow states")
        assert ws_idx != -1, "README missing `## Workflow states` heading"
        ws_text = content_no_mermaid[ws_idx:]
        for stage in keyword_list():
            assert f"`{stage}`" in ws_text, (
                f"README `## Workflow states` section never mentions "
                f"`{stage}` — the model declares it but the README's "
                f"workflow-states table / prose doesn't cover it."
            )
