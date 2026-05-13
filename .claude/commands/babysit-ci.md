---
description: Watch CI on the in-container task's PR via a background `gh pr checks --watch`. The harness fires a new turn when the watch completes; on that turn, react (fix and re-watch, or stop on green). After the user kicks off, the loop runs autonomously without polling.
---

You are running CI babysitting on the in-container task's PR. The pattern is *push-driven*: each invocation either kicks off a long-running background watch (and ends the turn) or reacts to a just-completed watch and decides what to do next. The harness wakes you up automatically when the background watch returns — no polling, no `ScheduleWakeup`. You only consume tokens on real CI state changes, not on idle waits.

This skill only edits the worktree (the cloude repo is mounted read-only inside the container). It does **not** touch the heading's TODO keyword — `/advance`, `/iterate`, `/drop` own that. On bail, it does flip the heading's tag to `:user:` so you stop being autonomous.

## State conventions

- State file: `<worktree>/.cloude-babysit-state.json`. Created on first invocation, deleted on clean exit or bail. Add it to `<worktree>/.git/info/exclude` on creation so `git status` stays quiet.
- Schema:
  ```json
  {
    "started_at": "<ISO8601>",
    "watch_bash_id": "<bash-id-of-background-gh-watch | null>",
    "last_head_sha": "<sha-or-null>",
    "failed_check_retries": {"<check name>": <int>, ...}
  }
  ```
- Budgets (defaults):
  - **Wall-clock**: 2 hours from `started_at`.
  - **Per-check post-fix retries**: 3 on the same check. A "post-fix retry" is a failing check whose count increments only when the worktree HEAD SHA changed between the previous failure and this one.

## 1. Read inputs

From `$CLOUDE_TASK_FILE` properties drawer: `:WORKTREE:`, `:PR:`. If `:PR:` is missing or unset, **bail immediately** (see Bail-out hygiene below) with note "no :PR: in task file".

Load `<worktree>/.cloude-babysit-state.json` if it exists. If not, this is a fresh start — initialize:

```json
{ "started_at": "<now ISO>", "watch_bash_id": null, "last_head_sha": null, "failed_check_retries": {} }
```

And append `.cloude-babysit-state.json` to `<worktree>/.git/info/exclude` if not already present.

## 2. Wall-clock budget check

If `now - started_at > 2 hours`: bail with note "babysit-ci wall-clock budget exhausted (2h)".

## 3. Decide mode

Two cases:

- **Post-completion mode** — `watch_bash_id` is set AND that background task has finished. Detected by either the task-notification in this turn's input naming that bash id, or by `BashOutput(bash_id=...)` reporting completion. Proceed to step 4.
- **Fresh-start mode** — `watch_bash_id` is null (no watch active yet). Skip to step 5.

(If `watch_bash_id` is set but the bash task is still running — e.g., a user manually re-invoked while a watch was in flight — print "watch already running, exiting" and end the turn without starting another. No state changes.)

## 4. Post-completion: read the watch's output and react

Use `BashOutput(bash_id=<watch_bash_id>)` to read the captured stdout/stderr from the completed `gh pr checks --watch` call, and read its exit code from the task-notification or the bash status.

Parse the output to know the final state of each check. `gh pr checks --watch` prints a check-by-check status table; the last block of output is the final state.

Two branches:

### 4a. All checks passing → flip to :user: and exit

If no failing checks (and at least one passing), the agent's autonomous work is done. The next move — actually advancing the stage — is the user's call.

- Edit `$CLOUDE_TASK_FILE`'s top-level heading: replace any trailing `:tag:` markers (`:agent:` typically; could be a chain) with `:user:`. Preserve the TODO keyword (still `ITERATING`, or whatever stage you were running under) and the heading text exactly. This signals that nothing more is happening autonomously and the user should look at the result and decide whether to `/advance`.
- Delete `<worktree>/.cloude-babysit-state.json`.
- Print:
  ```
  babysit-ci: CI is green on <pr-url>. Heading tag flipped to :user:. Run /advance when ready.
  ```
- End the turn. Loop terminates here. **Do not auto-advance the TODO state.** Advancing forward is user-driven by design; the `:user:` flip is the explicit hand-off.

### 4b. At least one failing → fix and re-watch

Capture current HEAD SHA: `git -C <worktree> rev-parse HEAD`.

For each failing check:

- If `last_head_sha` is set and current HEAD == `last_head_sha`: this is the same revision as last failure — don't increment retries (it's just CI reporting the same result we already processed). Move on.
- If HEAD changed since `last_head_sha`: this is a post-fix retry. Increment `failed_check_retries[<check name>]`. If it now exceeds 3: bail with note "babysit-ci: <check> has failed 3 times after fix attempts; needs human review".
- Pull the failure logs:
  ```
  gh run view <run-id> --log-failed
  ```
  Run id comes from the `link` field in `gh pr checks --json`. If you didn't capture it in step 3's output, re-query: `gh pr checks <pr-url> --json name,state,conclusion,link`.
- Decide: real failure or flake?
  - **Flake** (network blip, transient infra, etc.): `gh run rerun <run-id> --failed`. Don't increment retries (no fix was attempted).
  - **Real**: diagnose, implement the fix in the worktree, commit + push:
    ```
    git -C <worktree> add <paths>
    git -C <worktree> commit -m "<concise, project-convention message>"
    git -C <worktree> push
    ```

After handling all failures:
- Update state: `last_head_sha = current HEAD`, `watch_bash_id = null`, updated `failed_check_retries`.
- Save state file.
- Fall through to step 5 (start a new watch on the new push).

## 5. Fresh-start: kick off the background watch and exit

Start the watch as a background bash:

```
gh pr checks <pr-url> --watch --interval 10
```

with `run_in_background: true`. The Bash tool returns immediately with a `bash_id`.

Update state file:
- `watch_bash_id` = the returned bash id
- (other fields unchanged)
Save state.

Print:
```
babysit-ci: watch armed (bash <id>) on <pr-url>. Ending turn; will react when CI completes.
```

End the turn. **Do not call `ScheduleWakeup`. Do not call any other tools.** The push-on-completion model means the harness will fire your next turn when the watch returns. On that turn, you'll be in post-completion mode (step 4).

## Bail-out hygiene

Whenever bailing for any reason (no `:PR:`, wall-clock exhausted, per-check retries exceeded, unrecoverable error):

1. Edit `$CLOUDE_TASK_FILE`'s top-level heading line: flip the tag to `:user:` (preserve TODO keyword and heading text). Append a short note to the `** Notes` section explaining what bailed and why.
2. If `watch_bash_id` is set and the bash is still running: kill it via the appropriate tool (or `kill <pid>` if you have it). Don't leave orphans.
3. Delete `<worktree>/.cloude-babysit-state.json`.
4. Print a one-paragraph summary so a glance at the conversation makes it clear what happened.
5. **Do not** call `ScheduleWakeup`. **Do not** start a new watch. The loop ends here.

## Output convention

Every invocation prints at most a few short lines:

```
[babysit-ci]
  Mode:    <fresh-start | post-completion | bailed>
  PR:      <pr-url>
  Action:  <"watch armed" | "rerunning <check> (flake)" | "pushed fix for <check>" | "exited clean (green)" | "bailed: <reason>">
```

Don't dump the full `gh pr checks` table on every tick — it'll be in the bash output already. Just the action line.
