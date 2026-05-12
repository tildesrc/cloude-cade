---
description: Flip the task's TODO keyword to DROPPED (terminal abandon transition from any non-terminal state)
---

You are abandoning the in-container task. This skill flips the TODO keyword to `DROPPED` from any non-terminal state. No DoD check (the work is being abandoned, so completion criteria don't apply). Only edits `$CLOUDE_TASK_FILE`; the cloude repo is mounted read-only inside the container, so no commit happens here — the diff will show up on the host side.

This is the agent-side half of the drop: after this skill flips the state, the host needs to run `/sweep` (or `/finalize` directly) to perform the file move, PR close, tmux/worktree cleanup.

## 1. Read the task file

Read `$CLOUDE_TASK_FILE`. Parse the top-level heading's current TODO keyword, heading text, and existing tag(s).

## 2. Guard against bad transitions

- If the current TODO keyword is already `DROPPED`: no-op. Report "already DROPPED" and stop.
- If the current TODO keyword is `COMPLETE`: refuse. The work has already landed; dropping a completed task doesn't make sense. Tell the user the task is COMPLETE and ask whether they want a different action (e.g., open a follow-up to revert, or hand-delete the task file). Do not edit the file.

## 3. Perform the transition

Edit the heading line:

- TODO keyword → `DROPPED`
- Heading tag → `:user:` (the per-stage default for DROPPED — reflects that the host now needs to run `/finalize`), **unless** an `--tag <name>` was passed.

Strip any existing trailing `:tag:` markers before appending the new one. Preserve the heading text and leading indentation exactly. Don't touch anything below the heading.

## 4. Report

Print one short summary plus a host-action reminder:

```
Dropped: <CURRENT_STATE> :<old-tag>:  →  DROPPED :<new-tag>:

The host needs to run /sweep (or /finalize directly) to:
  - close the PR (<:PR: value>)
  - kill the tmux session
  - remove the worktree
  - git mv the file from tasks/active/ to tasks/dropped/
```
