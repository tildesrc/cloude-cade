---
description: Finalize an active task — move its org file to tasks/completed/ or tasks/dropped/, kill its tmux session, remove its worktree, and (for COMPLETE) delete the local branch
---

You are finalizing an active task — performing the file move and cleanup the in-container agent can't do because the cloude repo is mounted read-only from inside the container. The mechanical chain lives in `bin/cloude-finalize-cleanup`; this skill is a thin wrapper that picks the task and handles the judgment-call cases the script surfaces via distinct exit codes.

The cloude repo root (current working directory when this command was invoked) is the anchor for relative paths below.

## 1. Pick a task

If a caller (e.g. `/sweep`) has already chosen the task, skip the picker and use that absolute path.

Otherwise: run `bin/cloude-list-active`. It prints a numbered list of every active task in stage-priority order, e.g.:

```
1) [COMPLETE :user:] heading text   (tasks/active/2026-05-15-foo.org)
2) [MERGING :agent:] another task   (tasks/active/2026-05-14-bar.org)
...
```

Present the list to the user and ask which one to finalize.

## 2. Run the cleanup

```
bin/cloude-finalize-cleanup <abs-task-file>
```

On success (exit 0), relay the script's summary block to the user.

The script verifies the PR is `MERGED` for COMPLETE, closes it for DROPPED, kills the tmux session, removes the worktree, removes the per-task DinD volume, deletes the local branch (COMPLETE only), and moves the task file to `tasks/completed/` or `tasks/dropped/`.

## 3. Handle judgment-call exit codes

The script bails with distinct exit codes when it needs a decision. In each case, surface the script's stderr to the user and ask how to proceed:

- **Exit 10** — task is `COMPLETE` but the PR is not in state `MERGED`. The in-container agent set the keyword prematurely. Don't retry from here. Tell the user the fix lives in the task file: flip the TODO back to `MERGING` and let the merge actually land before re-running `/finalize`.

- **Exit 11** — task is not in `COMPLETE` or `DROPPED`. `/finalize` only force-drops from a non-terminal state (it won't force-complete — COMPLETE requires the agent to verify the merge). Ask the user to confirm dropping. On confirmation, rerun with `--force-drop`; the script flips the keyword to `DROPPED` in-place and proceeds.

- **Exit 12** — worktree has uncommitted/untracked changes, or is locked. The script printed `git status --short`. Ask the user: force-remove (discards everything in the worktree) or abort? On force, rerun with `--force-worktree`.

- **Exit 13** — DinD volume is still in use. The script listed which containers are holding it. Ask the user: skip the volume cleanup (leaves the volume in place) or abort? On confirm, rerun with `--skip-volume`.

Any other non-zero exit is a hard failure: relay stderr to the user and stop. The script's "Succeeded so far" trail (when present) tells the user what was already done.

## 4. Report

The script prints its own summary block on success. Just relay it.
