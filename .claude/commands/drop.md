---
description: Flip the task's TODO keyword to DROPPED (terminal abandon transition from any non-terminal state)
---

You are abandoning the in-container task. This skill flips the TODO keyword to `DROPPED` from any non-terminal state. No DoD check (the work is being abandoned, so completion criteria don't apply). Only edits `$CLOUDE_TASK_FILE`; the cloude repo is mounted read-only inside the container, so no commit happens here — the diff will show up on the host side.

This is the agent-side half of the drop: after this skill flips the state, the host needs to run `/sweep` (or `/finalize` directly) to perform the file move, PR close, tmux/worktree cleanup.

## 1. Read the task file

Run `eval "$( "$CLOUDE_ROOT/bin/cloude-task-info" "$CLOUDE_TASK_FILE" )"`. The helper emits shell-safe `KEY=VALUE` lines; after `eval`, `$TODO` holds the current keyword (used by the guard below), `$TAG` the current tag, and `$PR` the PR URL (used in the report). Don't hand-parse the heading. If the command exits non-zero, surface its stderr and stop.

## 2. Guard against bad transitions

- If the current TODO keyword is already `DROPPED`: no-op. Report "already DROPPED" and stop.
- If the current TODO keyword is `COMPLETE`: refuse. The work has already landed; dropping a completed task doesn't make sense. Tell the user the task is COMPLETE and ask whether they want a different action (e.g., open a follow-up to revert, or hand-delete the task file). Do not edit the file.

## 3. Perform the transition

Resolve the drop state and its default tag from the workflow definition
rather than hardcoding them:

```
DROP_STATE="$( "$CLOUDE_ROOT/bin/cloude-workflow" role drop )"
DROP_TAG="$( "$CLOUDE_ROOT/bin/cloude-workflow" default-tag "$DROP_STATE" )"
```

(For the default workflow that is `DROPPED` / `user`.) Then flip the
heading with the shared helper:

```
"$CLOUDE_ROOT/bin/cloude-task-set-state" "$CLOUDE_TASK_FILE" --todo "$DROP_STATE" --tag <tag>
```

`<tag>` is `$DROP_TAG` (for the default workflow, `user` — reflects that the host now needs to run `/finalize`), **unless** an `--tag <name>` was passed to `/drop`. The helper swaps the TODO keyword, replaces any existing trailing `:tag:` chain with the single new tag, and preserves the heading text and everything below it.

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
