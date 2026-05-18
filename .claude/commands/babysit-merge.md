---
description: Drive a PR through the merge queue autonomously. Adds the PR to the queue, watches via background bash, re-queues on transient ejections. On successful merge, auto-advances MERGING → COMPLETE :user:. On any blocking condition (failed required check, requested changes, merge conflict, etc.), kicks the task back to ITERATING :user: with an explanation. Push-driven — zero tokens during the wait.
---

You are driving the in-container task's PR through the merge queue. This is the MERGING stage's autonomous workhorse: the agent's job per CLAUDE.md is "actively manage the merge — re-add to the queue on flaky failures … and flip the TODO keyword to COMPLETE once the merge has landed."

Push-driven loop (same shape as `/babysit-ci`): kicks off `gh pr checks --watch` as a background bash, ends the turn, harness fires a new turn when the watch returns, the agent reacts. Zero tokens during the wait.

Only edits the worktree (cloude repo is read-only inside the container). On success it advances the heading TODO; on bail / kick-back it edits the heading tag and notes. `/finalize` on the host handles the final file move + cleanup.

## State conventions

- State file: `<worktree>/.cloude-babysit-merge-state.json`. Created on first invocation, deleted on clean exit or bail. Add to `<worktree>/.git/info/exclude` on creation so `git status` stays quiet.
- Schema:
  ```json
  {
    "started_at": "<ISO8601>",
    "watch_bash_id": "<bash-id-of-background-gh-watch | null>",
    "requeue_count": <int>
  }
  ```
- Budget: **2 hours wall-clock** from `started_at`. There's no fixed cap on re-queue attempts — "keep re-adding to the queue until it merges" — but the wall-clock acts as the long-stop. Genuinely-blocked PRs trip step 5c (kick back to ITERATING) before wall-clock matters.

## 1. Read inputs

Run `eval "$( "$CLOUDE_ROOT/bin/cloude-task-info" "$CLOUDE_TASK_FILE" )"` to load `$WORKTREE` and `$PR` (the helper emits shell-safe `KEY=VALUE` lines — don't hand-parse the drawer). If `cloude-task-info` exits non-zero — it returns 3 and names the missing key on stderr when `:PR:` / `:WORKTREE:` / `:BRANCH:` is absent — **bail immediately** (see Bail-out hygiene) with that stderr message as the note.

Load `<worktree>/.cloude-babysit-merge-state.json` if it exists. If not, this is fresh — initialize:

```json
{ "started_at": "<now ISO>", "watch_bash_id": null, "requeue_count": 0 }
```

And append `.cloude-babysit-merge-state.json` to `<worktree>/.git/info/exclude` if not already present.

## 2. Wall-clock budget check

If `now - started_at > 2 hours`: bail with note "babysit-merge wall-clock budget exhausted (2h); merge isn't landing — needs human attention".

## 3. Query PR state

```
gh pr view <pr-url> --json state,mergeStateStatus,reviewDecision,autoMergeRequest,mergedAt,baseRefName
```

Capture the relevant fields. We branch on these in step 5.

## 4. Decide mode

- **Post-completion mode** — `watch_bash_id` is set AND the background watch has completed (detected via the task-notification or `BashOutput`). Proceed to step 5.
- **Fresh-start mode** — `watch_bash_id` is null. Proceed to step 5 anyway; the state query was non-blocking so we can evaluate immediately.

(If `watch_bash_id` is set and still running — e.g., a user manually re-invoked while a watch is in flight — print "watch already running, exiting" and end the turn without disturbing it.)

## 5. Branch on PR state

### 5a. `state == "MERGED"` → success: advance to COMPLETE :user:

The merge landed. Per CLAUDE.md, MERGING → COMPLETE is the one forward transition the agent is explicitly allowed to perform.

- Flip the heading to `COMPLETE :user:` with the shared helper:
  ```
  "$CLOUDE_ROOT/bin/cloude-task-set-state" "$CLOUDE_TASK_FILE" --todo COMPLETE --tag user
  ```
  It swaps the keyword, replaces any existing trailing `:tag:` chain with the single new tag, and preserves the heading text.
- Append a short line under `** Notes` recording the merge (e.g. `Merged at <mergedAt> as <mergeCommit short SHA>`).
- Delete `<worktree>/.cloude-babysit-merge-state.json`.
- Print:
  ```
  babysit-merge: PR <pr-url> merged. Task auto-advanced MERGING → COMPLETE :user:.
  Run /sweep (or /finalize directly) on the host to move the file and clean up.
  ```
- End the turn. Loop terminates here.

### 5b. `state == "CLOSED"` (and not merged) → unusual; kick to :user:

The PR was closed without merging. Unexpected during MERGING. Don't try to re-open or guess; surface it.

- Flip the heading tag to `:user:` with `"$CLOUDE_ROOT/bin/cloude-task-set-state" "$CLOUDE_TASK_FILE" --tag user` (passing only `--tag` keeps TODO as MERGING; the user decides whether to /iterate or /drop).
- Append to `** Notes`: `babysit-merge: PR was CLOSED unexpectedly without merging. Investigate before next action.`
- Delete the state file.
- Print a summary line and end the turn.

### 5c. PR open with a blocking condition → kick back to ITERATING :user:

Detect a "blocking" condition from the step-3 query. Any of these qualifies:

- `mergeStateStatus` is `CONFLICTING` or `DIRTY` — merge conflict against the base. (Resolution belongs in ITERATING via `/babysit-ci`, which already handles conflict resolution.)
- `mergeStateStatus` is `BLOCKED` — a required check is failing, a required reviewer hasn't approved, branch protection isn't satisfied, etc.
- `reviewDecision` is `CHANGES_REQUESTED` — a reviewer asked for changes.

When any of those is true:

- Flip the heading to `ITERATING :user:` with the shared helper:
  ```
  "$CLOUDE_ROOT/bin/cloude-task-set-state" "$CLOUDE_TASK_FILE" --todo ITERATING --tag user
  ```
  It swaps the keyword, replaces any existing trailing `:tag:` chain, and preserves the heading text.
- Diagnose the specific blocker and append a short paragraph to `** Notes`. Examples:
  - *Merge blocked: required check `Build / unit-tests` is failing. See `<run-url>`. Address the failure and re-enter MERGING.*
  - *Merge blocked: reviewer @<login> requested changes. See review thread at `<review-url>`. Resolve the feedback and re-enter MERGING.*
  - *Merge blocked: branch is `CONFLICTING` against `<baseRefName>`. Run `/babysit-ci` (which handles trivial conflicts) or resolve manually, then re-enter MERGING.*
- Delete the state file.
- Print the same explanation to stdout so it's also visible at the conversation level.
- End the turn. Loop terminates.

### 5d. PR open, not blocking, **not in merge queue** → add and watch

`state == OPEN`, no blocking condition, and `autoMergeRequest` is null (PR isn't currently queued).

- Add to the queue:
  ```
  gh pr merge <pr-url> --auto --squash
  ```
  (Default `--squash`. If the repo uses a different merge strategy, the agent should adjust based on project convention — check the project's `CLAUDE.md` for a stated preference. If `gh` errors because the PR isn't yet eligible (e.g., draft, missing approval that wasn't blocking-reported), treat it like step 5c and kick back to ITERATING with the gh error in `** Notes`.)
- Increment `requeue_count` in state.
- Arm the background watch:
  ```
  gh pr checks <pr-url> --watch --interval 10
  ```
  with `run_in_background: true`. Capture the returned bash id into `watch_bash_id`. Save state.
- Print:
  ```
  babysit-merge: queued <pr-url> (attempt <requeue_count>). Watch armed (bash <id>). Ending turn; will react when CI completes.
  ```
- End the turn. **Do not call `ScheduleWakeup`. Do not call any other tools.** The harness fires the next turn when the watch returns.

### 5e. PR open, not blocking, **already in merge queue** → just watch

`autoMergeRequest` is non-null. The PR is queued or about to be queued.

- Arm the background watch (same `gh pr checks <pr-url> --watch --interval 10`, `run_in_background: true`). Capture bash id.
- Save state (don't bump `requeue_count` — we didn't add this time).
- Print and end the turn.

## Bail-out hygiene

Whenever bailing for any reason (no `:PR:`, wall-clock exhausted, unrecoverable error not covered by 5b/5c/5d):

1. Flip the heading tag to `:user:` with `"$CLOUDE_ROOT/bin/cloude-task-set-state" "$CLOUDE_TASK_FILE" --tag user`. Passing only `--tag` leaves the TODO keyword alone — don't touch it unless the specific bail-out explicitly says to (5a moves to COMPLETE; 5c moves to ITERATING; everything else keeps TODO as-is).
2. Append a short note under `** Notes` explaining what bailed and why.
3. If `watch_bash_id` is set and the bash is still running, kill it (don't leave orphans).
4. Delete `<worktree>/.cloude-babysit-merge-state.json`.
5. Print a one-paragraph summary so the next `/sweep` or human glance makes the situation clear.
6. **Do not** call `ScheduleWakeup`. **Do not** start another watch.

## Output convention

Every invocation prints at most a few short lines:

```
[babysit-merge]
  Mode:    <fresh-start | post-completion | bailed>
  PR:      <pr-url>
  State:   <state> / mergeable=<mergeStateStatus> / review=<reviewDecision>
  Action:  <"queued + watch armed" | "in-queue, watching" | "merged → COMPLETE :user:"
            | "kicked back to ITERATING: <reason>" | "bailed: <reason>">
  Next:    <"react when watch returns" | "—">
```

Don't dump full PR JSON or watch output every tick; the bash output is in the captured stream already.
