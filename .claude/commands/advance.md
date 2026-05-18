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

If `cloude-task-info` exits non-zero it prints the problem on stderr (an unparseable file, or a missing required property — it names the key). Surface that to the user and stop rather than guessing.

## 2. Determine the next state

Look up the next state from this table:

| Current     | Next       |
| ----------- | ---------- |
| `PLANNING`  | `ITERATING` |
| `ITERATING` | `REVIEW`   |
| `REVIEW`    | `MERGING`  |
| `MERGING`   | `COMPLETE` |
| `COMPLETE`  | (terminal — stop with "already terminal, nothing to advance to") |
| `DROPPED`   | (terminal — same) |

## 3. Load the DoD for the current state

Read `Stage details` from `$CLOUDE_ROOT/CLAUDE.md` (the cloude repo, mounted at the same path inside the container). Find the `#### <CURRENT_STATE>` section and pull its **Definition of done** bullet list.

## 4. Evaluate each DoD item

Some items can be checked programmatically; others need your judgment:

- **PLANNING**
  - "The plan is written into the task's org file" — check that the task file has substantive content under `** Plan` (or comparable section), not just the template placeholder text.
  - "A draft PR has been created on GitHub" — check that `:PR:` is set in the properties drawer and the URL is reachable: `gh pr view <pr-url> --json number,state` succeeds.
  - "The user has approved the plan" — judgment; look back through your recent turns. If unclear, ask the user.
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

`<new-tag>` is the per-stage default for `<NEXT_STATE>`, **unless** an `--tag <name>` was passed to `/advance` (then use that name):

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

**If the new tag is `:agent:`, do not stop here — immediately begin executing the new stage's responsibilities.** The user's `/advance` invocation IS their go-ahead; don't ask "should I…?" before starting work the stage explicitly assigns to the agent (per `CLAUDE.md`'s Stage details). Examples:

- `→ ITERATING :agent:` — start implementing the plan in the task file's `** Plan` section (or whatever feedback the user has just given you).
- `→ MERGING :agent:` — invoke `/babysit-merge`. That skill owns the full MERGING lifecycle: it adds the PR to the merge queue, watches via background bash, re-queues on transient ejections, auto-advances to `COMPLETE :user:` on success, and kicks back to `ITERATING :user:` with a Notes explanation if anything blocking shows up (failing required check, requested changes, merge conflict). Don't reimplement that loop inline; just call `/babysit-merge`.

If the new tag is `:user:` or `:blocked:`, stop here. `:user:` means the next move is the user's; `:blocked:` means you're waiting on something external. Don't poke the user; don't try to make progress on a stage that isn't actively agent-driven.

If the new state is `COMPLETE`, also remind the user that the host now needs to run `/sweep` (or `/finalize` directly) to perform the file move, branch cleanup, and PR check — that runs from outside the container.
