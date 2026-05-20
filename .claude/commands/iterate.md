---
description: Flip the task's TODO keyword to ITERATING (backward escape hatch from REVIEW or MERGING when more work is needed)
---

You are re-entering the `ITERATING` stage. This is the workflow's backward escape hatch — used when:

- a peer reviewer has left comments on a `REVIEW` PR that need code changes, or
- a `MERGING` task hit a merge conflict / failing required check / other surprise that calls for more code work.

Mechanical, no DoD check, no preconditions. Only edits `$CLOUDE_TASK_FILE` (the cloude repo is mounted read-only inside the container, so no commit happens here — the diff will show up on the host side).

## 1. Read the task file

Run `eval "$( "$CLOUDE_ROOT/bin/cloude-task-info" "$CLOUDE_TASK_FILE" )"`. The helper emits shell-safe `KEY=VALUE` lines; after `eval`, `$TODO` and `$TAG` hold the current state for the report below. Don't hand-parse the heading. If the command exits non-zero, surface its stderr and stop.

## 2. Perform the transition

Flip the heading with the shared helper:

```
"$CLOUDE_ROOT/bin/cloude-task-set-state" "$CLOUDE_TASK_FILE" --todo ITERATING --tag <tag>
```

`<tag>` is `agent` (the per-stage default for ITERATING), **unless** an `--tag <name>` was passed to `/iterate` — then use that name. The helper swaps the TODO keyword, replaces any existing trailing `:tag:` chain with the single new tag, and preserves the heading text and everything below it.

If the current state is already `ITERATING`, this is effectively a tag-reset (useful if the tag had drifted to `:user:` or `:blocked:` and you want to mark yourself back into active work).

## 3. Report

Print one short summary:

```
Re-entered ITERATING: <CURRENT_STATE> :<old-tag>:  →  ITERATING :<new-tag>:
```

## Note: auto-tick from PLANNING

When `/iterate` is invoked while the current state is `PLANNING`, `bin/cloude-task-set-state` additionally auto-ticks the "user has approved the plan" DoD checkbox on the closing PLANNING entry — the user's invocation of `/iterate` from PLANNING is itself the approval, the same way `/advance` is. No action needed from this skill.
