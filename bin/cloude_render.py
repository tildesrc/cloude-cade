"""Render the workflow-derived artifacts from a workflow definition.

Two artifacts are generated from `workflows/<active>.toml`:

  - CLAUDE.md — the "Workflow states", "Stage details", "Per-stage tag
    defaults" and "Who-has-the-ball tag" sections, spliced between a
    pair of `<!-- BEGIN/END GENERATED WORKFLOW -->` HTML-comment
    markers. The hand-written prose around the markers is untouched.
  - tasks/TEMPLATE.org — the `#+TODO:` keyword line and the starting
    TODO keyword on the scaffold heading.

`bin/cloude-render` is the thin CLI over this module; the test suite
imports the functions directly. Stdlib-only (it imports cloude_workflow,
which must stay stdlib-only for the hooks).
"""

from __future__ import annotations

import re

import cloude_workflow

BEGIN_MARKER = (
    "<!-- BEGIN GENERATED WORKFLOW "
    "(source: workflows/, regenerate: make render) -->"
)
END_MARKER = "<!-- END GENERATED WORKFLOW -->"


def render_workflow_section(wf: cloude_workflow.Workflow) -> str:
    """Render the generated CLAUDE.md block (without the marker lines)."""
    docs = wf.docs
    out: list[str] = []

    out.append("### Workflow states")
    out.append("")
    out.append(_block(docs, "workflow_states_body"))
    out.append("")

    out.append("### Stage details")
    out.append("")
    for name in wf.state_names:
        st = wf.states[name]
        suffix = " (terminal)" if st.is_terminal else ""
        out.append(f"#### {name}{suffix}")
        out.append("")
        if st.doc_prose:
            out.append(st.doc_prose.strip("\n"))
            out.append("")
        header = (
            "Responsibilities (in-container agent)"
            if st.is_terminal
            else "Responsibilities"
        )
        out.append(f"**{header}**")
        out.extend(f"- {b}" for b in st.responsibilities)
        out.append("")
        out.append("**Definition of done**")
        out.extend(f"- {b}" for b in st.definition_of_done)
        out.append("")

    out.append("#### Per-stage tag defaults")
    out.append("")
    out.append(_block(docs, "tag_defaults_body"))
    out.append("")

    out.append("### Who-has-the-ball tag")
    out.append("")
    out.append(_block(docs, "who_has_ball_intro"))
    out.append("")
    out.extend(f"- `:{t['name']}:` — {t['description']}" for t in wf.ball_tags)
    out.append("")
    out.append(_block(docs, "who_has_ball_outro"))

    return "\n".join(out)


def render_claude_md(text: str, wf: cloude_workflow.Workflow) -> str:
    """Return CLAUDE.md with the generated block spliced between the markers."""
    begin = text.find(BEGIN_MARKER)
    end = text.find(END_MARKER)
    if begin == -1 or end == -1:
        raise ValueError(
            "CLAUDE.md is missing the generated-workflow markers "
            f"({BEGIN_MARKER!r} / {END_MARKER!r})"
        )
    if end < begin:
        raise ValueError("CLAUDE.md workflow markers are out of order")

    after_begin = begin + len(BEGIN_MARKER)
    section = render_workflow_section(wf)
    return text[:after_begin] + "\n\n" + section + "\n\n" + text[end:]


def render_template_org(text: str, wf: cloude_workflow.Workflow) -> str:
    """Return TEMPLATE.org with its `#+TODO:` line and heading keyword set."""
    text = re.sub(
        r"^#\+TODO:.*$",
        f"#+TODO: {wf.todo_line}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    initial = wf.promote_initial("standard")
    text = re.sub(
        r"^(\* )\S+( <task title>)",
        rf"\g<1>{initial}\g<2>",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    return text


def _block(docs: dict, key: str) -> str:
    """A required verbatim prose block from the definition's [docs] table."""
    if key not in docs:
        raise ValueError(f"workflow definition is missing docs.{key}")
    return docs[key].strip("\n")
