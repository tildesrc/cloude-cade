"""Tests for bin/cloude_workflow.py — the workflow definition loader."""

from pathlib import Path

import cloude_workflow
import pytest

ROOT = Path(__file__).resolve().parent.parent


# --- the default workflow ----------------------------------------------------


def test_default_states_and_kinds():
    wf = cloude_workflow.load(name="default", root=ROOT)
    assert wf.state_names == [
        "PLANNING",
        "ITERATING",
        "REVIEW",
        "MERGING",
        "COMPLETE",
        "DROPPED",
    ]
    assert wf.in_flight == ["PLANNING", "ITERATING", "REVIEW", "MERGING"]
    assert wf.terminal == ["COMPLETE", "DROPPED"]


def test_default_todo_line():
    wf = cloude_workflow.load(name="default", root=ROOT)
    assert wf.todo_line == (
        "PLANNING(p!) ITERATING(i!) REVIEW(r!) MERGING(m!) "
        "| COMPLETE(c!) DROPPED(x@)"
    )


def test_default_stage_order_in_flight_only():
    wf = cloude_workflow.load(name="default", root=ROOT)
    assert wf.stage_order == {
        "MERGING": 0,
        "REVIEW": 1,
        "ITERATING": 2,
        "PLANNING": 3,
    }


def test_default_ball_tags():
    wf = cloude_workflow.load(name="default", root=ROOT)
    assert wf.ball_tag_names == ("agent", "user", "blocked")


def test_default_next_state_and_skip_review():
    wf = cloude_workflow.load(name="default", root=ROOT)
    assert wf.next_state("PLANNING") == "ITERATING"
    assert wf.next_state("ITERATING") == "REVIEW"
    assert wf.next_state("ITERATING", skip_review=True) == "MERGING"
    assert wf.next_state("REVIEW") == "MERGING"
    assert wf.next_state("MERGING") == "COMPLETE"
    assert wf.next_state("COMPLETE") is None
    assert wf.next_state("DROPPED") is None


def test_default_forward_drivers():
    wf = cloude_workflow.load(name="default", root=ROOT)
    assert wf.forward_driver("PLANNING") == "user"
    assert wf.forward_driver("ITERATING") == "user"
    assert wf.forward_driver("REVIEW") == "user"
    assert wf.forward_driver("MERGING") == "agent"
    assert wf.forward_driver("COMPLETE") is None


def test_default_default_tags():
    wf = cloude_workflow.load(name="default", root=ROOT)
    assert wf.default_tag("ITERATING") == "agent"
    assert wf.default_tag("REVIEW") == "blocked"
    assert wf.default_tag("MERGING") == "agent"
    assert wf.default_tag("COMPLETE") == "user"
    assert wf.default_tag("DROPPED") == "user"


def test_default_auto_advance():
    wf = cloude_workflow.load(name="default", root=ROOT)
    assert wf.auto_advance == {"from": "PLANNING", "to": "ITERATING", "tag": "agent"}


def test_default_promote_initials():
    wf = cloude_workflow.load(name="default", root=ROOT)
    assert wf.promote_initial("standard") == "PLANNING"
    assert wf.promote_initial("adopt") == "ITERATING"


def test_default_roles():
    wf = cloude_workflow.load(name="default", root=ROOT)
    assert wf.role("iterate") == "ITERATING"
    assert wf.role("drop") == "DROPPED"


def test_dod_is_flattened_for_consumers():
    wf = cloude_workflow.load(name="default", root=ROOT)
    iterating = wf.states["ITERATING"]
    # The verbatim bullet keeps CLAUDE.md's line wrapping...
    assert any("\n" in b for b in iterating.definition_of_done)
    # ...but the flattened form a hook would display is single-line.
    for bullet in iterating.dod_flat:
        assert "\n" not in bullet
    assert iterating.dod_flat[0] == "The plan is implemented in code."


def test_terminal_states_have_no_order():
    wf = cloude_workflow.load(name="default", root=ROOT)
    assert wf.states["COMPLETE"].order is None
    assert "COMPLETE" not in wf.stage_order


# --- the active-workflow pointer ---------------------------------------------


def test_active_workflow_pointer():
    assert cloude_workflow.active_workflow_name(ROOT) == "default"


def test_load_without_name_uses_active_pointer():
    wf = cloude_workflow.load(root=ROOT)
    assert wf.name == "default"


# --- the solo workflow (proves alternatives are definable) -------------------


def test_solo_has_no_review_stage():
    wf = cloude_workflow.load(name="solo", root=ROOT)
    assert "REVIEW" not in wf.state_names
    assert wf.in_flight == ["PLANNING", "ITERATING", "MERGING"]


def test_solo_iterating_advances_to_merging():
    wf = cloude_workflow.load(name="solo", root=ROOT)
    assert wf.next_state("ITERATING") == "MERGING"
    # No skip-review conditional in the solo workflow.
    assert wf.next_state("ITERATING", skip_review=True) == "MERGING"


def test_solo_todo_line_omits_review():
    wf = cloude_workflow.load(name="solo", root=ROOT)
    assert wf.todo_line == (
        "PLANNING(p!) ITERATING(i!) MERGING(m!) | COMPLETE(c!) DROPPED(x@)"
    )


# --- malformed definitions ---------------------------------------------------


def _write_workflow(tmp_path: Path, name: str, content: str) -> Path:
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir(exist_ok=True)
    (wf_dir / f"{name}.toml").write_text(content)
    return tmp_path


def test_missing_definition_file(tmp_path):
    with pytest.raises(cloude_workflow.WorkflowError, match="not found"):
        cloude_workflow.load(name="nope", root=tmp_path)


def test_malformed_toml(tmp_path):
    root = _write_workflow(tmp_path, "bad", "name = = broken")
    with pytest.raises(cloude_workflow.WorkflowError, match="malformed TOML"):
        cloude_workflow.load(name="bad", root=root)


def test_no_states_defined(tmp_path):
    root = _write_workflow(
        tmp_path,
        "bad",
        'name = "bad"\n[[ball_tags]]\nname = "agent"\ndescription = "x"\n',
    )
    with pytest.raises(cloude_workflow.WorkflowError, match=r"no \[\[states\]\]"):
        cloude_workflow.load(name="bad", root=root)


def test_no_ball_tags_defined(tmp_path):
    root = _write_workflow(
        tmp_path,
        "bad",
        'name = "bad"\n'
        '[[states]]\nname = "A"\nkind = "terminal"\n'
        'org_shortcut = "a!"\ndefault_tag = "user"\n',
    )
    with pytest.raises(cloude_workflow.WorkflowError, match="ball_tags"):
        cloude_workflow.load(name="bad", root=root)


def test_transition_to_unknown_state(tmp_path):
    root = _write_workflow(
        tmp_path,
        "bad",
        'name = "bad"\n'
        '[[ball_tags]]\nname = "agent"\ndescription = "x"\n'
        '[[states]]\nname = "A"\nkind = "in-flight"\n'
        'org_shortcut = "a!"\ndefault_tag = "agent"\n'
        '[states.forward]\nnext = "GHOST"\ndriver = "user"\n',
    )
    with pytest.raises(cloude_workflow.WorkflowError, match="unknown state 'GHOST'"):
        cloude_workflow.load(name="bad", root=root)


def test_state_missing_required_key(tmp_path):
    root = _write_workflow(
        tmp_path,
        "bad",
        'name = "bad"\n'
        '[[ball_tags]]\nname = "agent"\ndescription = "x"\n'
        '[[states]]\nname = "A"\nkind = "terminal"\n',  # no org_shortcut/default_tag
    )
    with pytest.raises(cloude_workflow.WorkflowError, match="missing required key"):
        cloude_workflow.load(name="bad", root=root)


def test_invalid_state_kind(tmp_path):
    root = _write_workflow(
        tmp_path,
        "bad",
        'name = "bad"\n'
        '[[ball_tags]]\nname = "agent"\ndescription = "x"\n'
        '[[states]]\nname = "A"\nkind = "sideways"\n'
        'org_shortcut = "a!"\ndefault_tag = "agent"\n',
    )
    with pytest.raises(cloude_workflow.WorkflowError, match="invalid kind"):
        cloude_workflow.load(name="bad", root=root)
