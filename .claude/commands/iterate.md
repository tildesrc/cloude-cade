---
description: Flip the task's TODO keyword to ITERATING (backward escape hatch from REVIEW or MERGING when more work is needed)
---

You are re-entering the `ITERATING` stage. This is the workflow's backward escape hatch — used when:

- a peer reviewer has left comments on a `REVIEW` PR that need code changes, or
- a `MERGING` task hit a merge conflict / failing required check / other surprise that calls for more code work.

Mechanical, no DoD check, no preconditions. Only edits `$CLOUDE_TASK_FILE` (the cloude repo is mounted read-only inside the container, so no commit happens here — the diff will show up on the host side).

## 1. Read the task file

Read `$CLOUDE_TASK_FILE`. Parse the top-level heading's current TODO keyword, heading text, and existing tag(s).

## 2. Perform the transition

Edit the heading line:

- TODO keyword → `ITERATING`
- Heading tag → `:agent:` (the per-stage default for ITERATING), **unless** an `--tag <name>` was passed.

Strip any existing trailing `:tag:` markers before appending the new one. Preserve the heading text and leading indentation exactly. Don't touch anything below the heading.

If the current state is already `ITERATING`, this is effectively a tag-reset (useful if the tag had drifted to `:user:` or `:blocked:` and you want to mark yourself back into active work).

## 3. Report

Print one short summary:

```
Re-entered ITERATING: <CURRENT_STATE> :<old-tag>:  →  ITERATING :<new-tag>:
```
