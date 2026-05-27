---
description: Advance the task's TODO keyword forward to the next workflow stage, after checking the current stage's Definition of Done
---

You are advancing the in-container task's TODO keyword forward to the next workflow stage. This skill surfaces the *current* stage's Definition of Done as a checklist and **complains** (lists unmet items, asks for explicit confirmation) before performing the transition. The skill only edits `$CLOUDE_TASK_FILE`; the cloude repo is mounted read-only inside the container, so no commit happens here — the diff will show up on the host side.

This skill is mechanical; it does not enforce the "forward transitions out of PLANNING/ITERATING/REVIEW are user-driven only" policy from `CLAUDE.md`. Invoke it only when the user has actually approved the transition (or in the agent-driven cases: `MERGING → COMPLETE`).

## 1. Read the task file

Load the task's metadata with the shared helper rather than hand-parsing the heading or properties drawer:

```
eval "$( "$CLOUDE_ROOT/bin/cloude-task-info" "$CLOUDE_TASK_FILE" )"
```

`cloude-task-info` emits shell-safe `KEY=VALUE` lines, so `eval` leaves these set:

- `$TODO` — the current TODO keyword.
- `$TAG` — the current who-has-the-ball tag (`agent` / `user` / `blocked`, or empty).
- `$HEADING` — the heading text.
- `$WORKTREE`, `$BRANCH`, `$PR` — properties-drawer fields that feed the DoD checks below (plus `$REPO`, `$ID`, and derived fields you can ignore here).
- `$SKIP_REVIEW` — `t` when the repo opts out of peer review; controls the next-state lookup in step 2 (empty otherwise).

If `cloude-task-info` exits non-zero it prints the problem on stderr (an unparseable file, or a missing required property — it names the key). Surface that to the user and stop rather than guessing.

## 2. Determine the next state

Ask the workflow model — the transition table lives in
`bin/cloude_stages.WORKFLOW`, exposed via the `cloude-stages` CLI:

```
NEXT="$(
    if [[ "$SKIP_REVIEW" == "t" ]]; then
        "$CLOUDE_ROOT/bin/cloude-stages" next "$TODO" --skip-review
    else
        "$CLOUDE_ROOT/bin/cloude-stages" next "$TODO"
    fi
)"
```

The CLI prints the next keyword on stdout, or empty when `$TODO` is
terminal (`COMPLETE` / `DROPPED`). If the result is empty, stop with
"already terminal, nothing to advance to".

For reference (what the model encodes today):

| Current     | Next                                                            |
| ----------- | --------------------------------------------------------------- |
| `PLANNING`  | `ITERATING`                                                     |
| `ITERATING` | `REVIEW` (or `MERGING` when `$SKIP_REVIEW == t` — see below)    |
| `REVIEW`    | `MERGING`                                                       |
| `MERGING`   | `COMPLETE`                                                      |
| `COMPLETE`  | terminal                                                        |
| `DROPPED`   | terminal                                                        |

**Skip-review override.** If `$SKIP_REVIEW` is truthy (`t`), the repo
opts out of peer review and the `REVIEW` stage is skipped: when the
current state is `ITERATING`, the next state is `MERGING` (not
`REVIEW`). The `--skip-review` flag to `cloude-stages next` encodes
this; every other transition is unchanged. (`:SKIP_REVIEW:` is copied
from the staging project heading by `/promote`; absent means review is
required, the default.)

## 3. Load the DoD for the current state

Ask the workflow model — the bullets it returns are the same ones the per-task checkbox skeleton was seeded with, so there's no chance of drift between what you evaluate and what's actually on disk:

```
DOD_BULLETS="$("$CLOUDE_ROOT/bin/cloude-stages" dod "$TODO")"
```

One bullet per line on stdout. For human-friendly context (the responsibilities prose, the "*Auto-ticked*" note on PLANNING's plan-approval bullet, etc.), the `#### <CURRENT_STATE>` section in `$CLOUDE_ROOT/CLAUDE.md` is the matching reference; the bullets there mirror the model but the CLI is the source of truth for the checklist this skill evaluates.

## 4. Evaluate each DoD item

Some items can be checked programmatically; others need your judgment:

- **PLANNING**
  - "The plan is written into the task's org file" — check that the task file has substantive content under `** Plan` (or comparable section), not just the template placeholder text.
  - "A draft PR has been created on GitHub" — check that `:PR:` is set in the properties drawer and the URL is reachable: `gh pr view <pr-url> --json number,state` succeeds.
  - "The user has approved the plan" — *auto-satisfied*. The act of the user invoking `/advance` while a task is in PLANNING IS the approval, and `bin/cloude-task-set-state` auto-ticks the matching DoD checkbox on the closing PLANNING entry as part of the transition. Don't pre-verify, don't ask the user, and don't flag it as unmet in step 5.
- **ITERATING**
  - "The plan is implemented in code" — judgment, with help from `git -C <worktree> log -p origin/<base>..HEAD` to see what's actually in the diff.
  - "New and relevant tests pass locally" — judgment based on what you've actually run this session.
  - "Changes are committed and pushed" — `git -C <worktree> status` should be clean (or only have untracked unrelated files), and `git -C <worktree> log @{u}..HEAD` should be empty (nothing ahead of upstream).
  - "CI tests are passing, or any failures can be attributed to irrelevant flakes" — `gh pr checks <pr-url>` for the PR. Surface the failing checks if any.
  - "The PR title and description on GitHub reflect the final change" — `gh pr view <pr-url> --json title,body`. Flag it as unmet if the title is still the bare staging-idea heading or the body still contains the `Draft PR for task … Plan to follow.` placeholder `cloude-promote-setup` opened the draft PR with. Also flag it as unmet if the body contains a "Test Plan", "Verification", or equivalent test-steps heading — those notes belong in the task's org file, not the PR description.
- **REVIEW**
  - "The PR has been reviewed" — `gh pr view <pr-url> --json reviews -q '[.reviews[] | select(.state == "APPROVED" or .state == "CHANGES_REQUESTED")] | length'` > 0, or the user has decided to skip review (judgment).
- **MERGING**
  - "The PR is merged" — `gh pr view <pr-url> --json state -q .state` must be `MERGED`.

## 5. Complain if anything is unmet

If any DoD item is unmet, print:

```
DoD for <CURRENT_STATE> is not fully satisfied:
  ✗ <unmet item 1>: <why / what's missing>
  ✗ <unmet item 2>: <why / what's missing>
  ✓ <met item>: (passed)
  ...

Advance from <CURRENT_STATE> to <NEXT_STATE> anyway? [y/N]
```

Default to **N** on any non-`y` response. If the user (or you, per the agent-driven `MERGING → COMPLETE`) says `y`, proceed. Otherwise stop without touching the file.

## 6. Perform the transition

Flip the heading with the shared helper — don't hand-edit the line:

```
"$CLOUDE_ROOT/bin/cloude-task-set-state" "$CLOUDE_TASK_FILE" --todo <NEXT_STATE> --tag <new-tag>
```

`<new-tag>` is the per-stage default for `<NEXT_STATE>`, **unless** an `--tag <name>` was passed to `/advance` (then use that name). Look it up the same way as `NEXT`:

```
NEW_TAG="$("$CLOUDE_ROOT/bin/cloude-stages" default-tag "$NEXT")"
```

For reference (what the model encodes today):

- `ITERATING → agent`
- `REVIEW → blocked`
- `MERGING → agent`
- `COMPLETE → user`

The helper rewrites only the first heading: it swaps the TODO keyword, replaces any existing trailing `:tag:` chain with the single new tag (so re-runs don't accrete tags), and preserves the heading text and everything below it.

## 7. Report and (if `:agent:`) continue working

Print one short summary:

```
Advanced: <CURRENT_STATE> :<old-tag>:  →  <NEXT_STATE> :<new-tag>:
```

When the skip-review override applied (`ITERATING → MERGING`), append a
parenthetical so it's clear `REVIEW` was intentionally bypassed:

```
Advanced: ITERATING :agent:  →  MERGING :agent:  (REVIEW skipped — repo opts out of peer review)
```

**If the new tag is `:agent:`, do not stop here — immediately begin executing the new stage's responsibilities.** The user's `/advance` invocation IS their go-ahead; don't ask "should I…?" before starting work the stage explicitly assigns to the agent (per `CLAUDE.md`'s Stage details). Examples:

- `→ ITERATING :agent:` — start implementing the plan in the task file's `** Plan` section (or whatever feedback the user has just given you).
- `→ MERGING :agent:` — invoke `/babysit-merge`. That skill owns the full MERGING lifecycle: it adds the PR to the merge queue, watches via background bash, re-queues on transient ejections, auto-advances to `COMPLETE :user:` on success, and kicks back to `ITERATING :user:` with a Notes explanation if anything blocking shows up (failing required check, requested changes, merge conflict). Don't reimplement that loop inline; just call `/babysit-merge`.

If the new tag is `:user:` or `:blocked:`, stop here. `:user:` means the next move is the user's; `:blocked:` means you're waiting on something external. Don't poke the user; don't try to make progress on a stage that isn't actively agent-driven.

If the new state is `COMPLETE`, also remind the user that the host now needs to run `/sweep` (or `/finalize` directly) to perform the file move, branch cleanup, and PR check — that runs from outside the container.
