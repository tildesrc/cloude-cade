---
description: Scan every vault's tasks/active/ for tasks in terminal states (COMPLETE or DROPPED) and offer to /finalize each after explicit user approval
---

You are sweeping the active task pool (across every vault) for tasks that have reached a terminal TODO state (`COMPLETE` or `DROPPED`) but haven't been moved out of `vaults/<vault>/tasks/active/` yet — i.e., the in-container agent has set the keyword but the host hasn't run `/finalize`. This skill is designed to be cheap when there's nothing to do (safe to put on a `/loop`) and explicit about asking before any destructive action.

The cloude repo root (current working directory when this command was invoked) is the anchor for relative paths below.

## 1. Scan and present

Run:

```
bin/cloude-list-active --terminal
```

If the output is exactly `No tasks awaiting finalize.`, print that one line and stop. This is the idle-tick output and what makes the skill cheap on a `/loop`.

Otherwise, each numbered line is a candidate to surface to the user. The format already matches what `/finalize` would show:

```
1) [personal] [COMPLETE :user:] heading text  (vaults/personal/tasks/active/<filename>.org)
2) [work]     [DROPPED :user:] another task   (vaults/work/tasks/active/<other>.org)
```

Present those lines verbatim to the user as the candidate list.

## 2. Ask for approval, one task at a time

For each candidate, prompt the user:

> Task `<heading>` is in `<state>`. Approve `/finalize` for it? [y/N/skip]

Treat anything other than a literal `y` / `yes` as "leave it for the next sweep" — including `N`, `skip`, or no response. Conservative default — never finalize without an explicit approval.

## 3. For approved tasks, run the cleanup

For each approved task, run:

```
bin/cloude-finalize-cleanup <abs-task-file>
```

On success (exit 0), relay the script's summary block to the user.

On these specific exit codes, surface the script's stderr to the user and ask how to proceed; rerun with the matching override flag if they confirm:

- **Exit 10** — PR is not in state `MERGED`. The in-container agent set `COMPLETE` prematurely. Tell the user; do not retry from here. The fix lives in the task file (flip TODO back to `MERGING` and let the merge land).
- **Exit 12** — worktree has uncommitted/untracked work. The script printed `git status --short`. Ask: force-remove (discards the changes) or skip? On confirm, rerun with `--force-worktree`.
- **Exit 13** — DinD volume is still in use. The script printed which containers are holding it. Ask: skip the volume cleanup (leave the volume in place) or abort? On confirm, rerun with `--skip-volume`.

Other non-zero exits are hard failures: relay stderr to the user and stop work on that task; move on to the next approved one.

## 4. Summarize

When all candidates have been handled, print a short summary listing what was finalized and what was left alone. This makes the loop's per-tick output legible when you scroll back through history.
