---
description: Finalize an active task — move its org file to tasks/completed/ or tasks/dropped/, kill its tmux session, remove its worktree, and (for COMPLETE) delete the local branch
---

You are finalizing an active task — performing the file move and cleanup the in-container agent can't do because the cloude repo is mounted read-only from inside the container. Walk through these steps interactively with the user. Do not skip steps; do not advance past a step until it has succeeded. If any step fails, stop and tell the user exactly what succeeded and what did not so they can clean up.

The cloude repo root (current working directory when this command was invoked) is the anchor for relative paths below.

## 1. Show active tasks and pick one

List the files under `tasks/active/`. For each, parse the top-level heading to extract:

- the **TODO keyword** (the first whitespace-separated word after the leading `*`)
- the **heading text** (everything between the keyword and any trailing org tags)
- the **tag** (`:user:`, `:agent:`, or `:blocked:` on the heading line)

Present them numbered, one per line, in the form:

```
1. [<TODO> :<tag>:] <heading text>   (tasks/active/<filename>.org)
```

Ask the user which one to finalize.

## 2. Read the chosen task file's properties drawer

Extract these properties from the file's `:PROPERTIES: ... :END:` drawer:

- `:WORKTREE:` — absolute worktree path. Sanity check that it starts with `<cloude-root>/worktrees/`.
- `:BRANCH:` — feature branch name. Sanity check that it begins with `cloude/`.
- `:PR:` — pull request URL.

Derive:

- `<repo-name>` from the worktree path: `basename $(dirname <WORKTREE>)`.
- `<source-clone>` = `<cloude-root>/repos/<repo-name>`.
- `<slug>` from the active filename `YYYY-MM-DD-<slug>.org` (strip the leading `YYYY-MM-DD-` and the trailing `.org`).
- `<tmux-session>` = `cloude-<slug>`.

If any required property is missing, stop and ask the user to fix the task file first.

## 3. Determine the finalize action

Based on the current TODO keyword:

- `COMPLETE` → finalize as **complete**. Continue.
- `DROPPED` → finalize as **dropped**. Continue.
- Anything else (`PLANNING`, `ITERATING`, `REVIEW`, `MERGING`):
  - Tell the user the task is currently in `<state>` and `/finalize` only force-drops from a non-terminal state — it won't force-complete because COMPLETE requires the agent to verify the PR actually merged.
  - Ask the user to confirm dropping. If they decline, stop.
  - On confirmation, update the task file: replace the leading TODO keyword on the heading with `DROPPED` and proceed as a drop.

## 4. Verify (COMPLETE only)

```
gh pr view <pr-url> --json state -q .state
```

Expect `MERGED`. If anything else, stop and tell the user the PR is in `<state>`, the agent set COMPLETE prematurely, and the fix is to set the TODO back to MERGING in the task file and re-run `/finalize` after the merge actually lands.

## 5. Close the PR (DROPPED only)

```
gh pr close <pr-url> --delete-branch=false
```

Local branch deletion is handled separately below — keep them decoupled.

## 6. Kill the tmux session

```
tmux kill-session -t <tmux-session> 2>/dev/null || true
```

Silent if the session doesn't exist. Capture whether it was actually killed (the command's exit status before the `|| true`) so the report can note it.

## 7. Remove the worktree

```
git -C <source-clone> worktree remove <WORKTREE>
```

This refuses with a clear error if the worktree has uncommitted changes or is locked. **Don't pass `--force`** — surface the error to the user, tell them which path needs cleanup, and stop. They can `git -C <source-clone> worktree remove --force <WORKTREE>` themselves and re-run.

## 8. Delete the local branch (COMPLETE only)

```
git -C <source-clone> branch -D <BRANCH>
```

`-D` (capital) because the branch may not show as merged into the *local* checkout's HEAD even though it merged upstream. For DROPPED, **skip this step** — leave the local branch in place in case the user wants to revisit the work.

## 9. Move the file in the cloude repo

For COMPLETE:

```
git -C <cloude-root> mv tasks/active/<filename>.org tasks/completed/<filename>.org
```

For DROPPED:

```
git -C <cloude-root> mv tasks/active/<filename>.org tasks/dropped/<filename>.org
```

`git mv` stages the rename automatically.

## 10. Commit the finalize in the cloude repo

For COMPLETE:

```
git -C <cloude-root> commit -m "Complete: <heading text>" \
    -- tasks/active/<filename>.org tasks/completed/<filename>.org
```

For DROPPED:

```
git -C <cloude-root> commit -m "Drop: <heading text>" \
    -- tasks/active/<filename>.org tasks/dropped/<filename>.org
```

Pass the two paths as explicit arguments after `--` so the commit only includes the rename, not any other staged work.

## 11. Report

Summarize what was done:

- Final state: `COMPLETE` or `DROPPED`
- Task file: moved from `tasks/active/<filename>.org` to `tasks/<completed|dropped>/<filename>.org`
- tmux session `<tmux-session>`: killed (or "was not running")
- Worktree `<WORKTREE>`: removed
- Local branch `<BRANCH>`: deleted (COMPLETE) or preserved (DROPPED)
- PR `<pr-url>`: confirmed MERGED (COMPLETE) or closed (DROPPED)
- Cloude commit: `<short-sha> <commit-message>`
