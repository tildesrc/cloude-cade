"""Tests for bin/cloude_render.py — CLAUDE.md / TEMPLATE.org generation.

The current CLAUDE.md and tasks/TEMPLATE.org are captured under
tests/fixtures/ as golden artifacts. These tests assert that:

  - the committed files match their captured fixtures, and
  - rendering the default workflow reproduces them byte-for-byte
    (i.e. `make render` would be a no-op — no drift), and
  - rendering the *solo* workflow produces the solo fixtures, proving
    a different workflow templates out different artifacts.
"""

from pathlib import Path

import cloude_render
import cloude_workflow

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


def _default():
    return cloude_workflow.load(name="default", root=ROOT)


def _solo():
    return cloude_workflow.load(name="solo", root=ROOT)


# --- the committed artifacts match their captured fixtures -------------------


def test_committed_claude_md_matches_fixture():
    assert (ROOT / "CLAUDE.md").read_text() == (
        FIXTURES / "CLAUDE.default.md"
    ).read_text()


def test_committed_template_matches_fixture():
    assert (ROOT / "tasks" / "TEMPLATE.org").read_text() == (
        FIXTURES / "TEMPLATE.default.org"
    ).read_text()


# --- rendering the default workflow reproduces the committed files -----------


def test_default_render_of_claude_md_is_idempotent():
    current = (ROOT / "CLAUDE.md").read_text()
    assert cloude_render.render_claude_md(current, _default()) == current


def test_default_render_of_template_is_idempotent():
    current = (ROOT / "tasks" / "TEMPLATE.org").read_text()
    assert cloude_render.render_template_org(current, _default()) == current


# --- rendering the solo workflow produces the solo fixtures ------------------


def test_solo_render_of_claude_md_matches_fixture():
    current = (ROOT / "CLAUDE.md").read_text()
    rendered = cloude_render.render_claude_md(current, _solo())
    assert rendered == (FIXTURES / "CLAUDE.solo.md").read_text()


def test_solo_render_of_template_matches_fixture():
    current = (ROOT / "tasks" / "TEMPLATE.org").read_text()
    rendered = cloude_render.render_template_org(current, _solo())
    assert rendered == (FIXTURES / "TEMPLATE.solo.org").read_text()


# --- structural properties of a render --------------------------------------


def test_solo_render_drops_the_review_stage():
    current = (ROOT / "CLAUDE.md").read_text()
    rendered = cloude_render.render_claude_md(current, _solo())
    assert "#### REVIEW" not in rendered
    assert "#### MERGING" in rendered
    # The hand-written prose outside the markers is untouched.
    assert "### Running inside the container" in rendered


def test_render_requires_markers():
    import pytest

    with pytest.raises(ValueError, match="markers"):
        cloude_render.render_claude_md("no markers here", _default())


def test_render_section_is_spliced_between_markers():
    current = (ROOT / "CLAUDE.md").read_text()
    rendered = cloude_render.render_claude_md(current, _default())
    begin = rendered.index(cloude_render.BEGIN_MARKER)
    end = rendered.index(cloude_render.END_MARKER)
    section = cloude_render.render_workflow_section(_default())
    assert section in rendered[begin:end]
