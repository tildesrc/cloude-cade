---
description: Scan tasks/active/ for tasks in terminal states (COMPLETE or DROPPED) and offer to /finalize each after explicit user approval
---

You are sweeping the active task pool for tasks that have reached a terminal TODO state (`COMPLETE` or `DROPPED`) but haven't been moved out of `tasks/active/` yet — i.e., the in-container agent has set the keyword but the host hasn't run `/finalize`. This skill is designed to be cheap when there's nothing to do (safe to put on a `/loop`) and explicit about asking before any destructive action.

## 1. Scan tasks/active/

List `tasks/active/*.org`. For each, parse the top-level heading line to extract the TODO keyword (the first whitespace-separated word after the leading `*`). Filter to those whose keyword is `COMPLETE` or `DROPPED`.

## 2. Quick exit if there's nothing to do

If no tasks match, print exactly one line and stop:

```
No tasks awaiting finalize.
```

This keeps loop-driven ticks terse so the per-poll cost stays low.

## 3. Present the candidates

For each candidate, print one line:

```
[<TODO>]  <heading text>   (tasks/active/<filename>.org)
```

## 4. Ask for approval, one task at a time

For each candidate, prompt the user:

> Task `<heading>` is in `<state>`. Approve `/finalize` for it? [y/N/skip]

Treat anything other than a literal `y` / `yes` as "leave it for the next sweep" — including `N`, `skip`, or no response. Conservative default — never finalize without an explicit approval.

## 5. For approved tasks, run the /finalize flow

For each approved task, follow the steps in `.claude/commands/finalize.md` **starting from step 2** — the task is already chosen by this sweep, so skip step 1's picker. Step 3 still runs normally (it reads the file's current TODO keyword to decide between COMPLETE-mode and DROPPED-mode).

All of `/finalize`'s mid-flow user prompts still apply: the dirty-worktree confirm in step 7, the volume-in-use prompt in step 8, the PR-not-MERGED abort in step 4 (for COMPLETE). Those are independent of the approval given here in step 4 of this sweep — they handle situations where finalize itself needs a judgment call.

## 6. Summarize

When all candidates have been handled, print a short summary listing what was finalized and what was left alone. This makes the loop's per-tick output legible when you scroll back through history.
