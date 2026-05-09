---
description: Promote an idea from staging.org into an active task (file, branch, worktree, draft PR, tmux session)
---

You are promoting an idea from `staging.org` into an active task. Walk through these steps interactively with the user. Do not skip steps; do not advance past a step until it has succeeded. If any step fails, stop and tell the user exactly what succeeded and what did not so they can clean up.

The cloude repo root (current working directory when this command was invoked) is the anchor for relative paths below.

## 1. Show staging contents and pick an idea

Read `staging.org`. Parse it:

- Top-level headings (`*`) are projects. Each carries a `:REPO:` property pointing to a GitHub repo.
- Sub-headings (`**`) under a project are ideas.

Present the ideas grouped by project, numbered globally so the user can pick by number. Ask the user which one to promote.

## 2. Confirm the slug

Auto-derive a slug from the chosen idea's heading text:

- Lowercase
- Replace non-alphanumerics with hyphens
- Collapse repeated hyphens
- Trim leading/trailing hyphens

Show the proposed slug to the user and ask them to confirm or override.

## 3. Determine repo info and ensure the source clone exists

From the project's `:REPO:` URL:

- Extract the repo name (last path segment, strip any trailing `.git`).
- The source clone lives at `<cloude-root>/repos/<repo-name>`. If it doesn't exist yet, clone it:
  ```
  mkdir -p <cloude-root>/repos
  git clone <repo-url> <cloude-root>/repos/<repo-name>
  ```
- Detect the default branch:
  ```
  gh repo view <repo-url> --json defaultBranchRef -q .defaultBranchRef.name
  ```

Store as `<repo-name>`, `<source-clone>`, `<default-branch>`.

## 4. Create the worktree and branch

Compute the absolute worktree path: `<cloude-root>/worktrees/<repo-name>/<slug>`. Make sure the parent directory exists (`mkdir -p`).

From the source clone, fetch and create the worktree on a new branch named `cloude/<slug>`, based on the default branch:

```
cd <source-clone>
git fetch origin <default-branch>
git worktree add -b cloude/<slug> <abs-worktree-path> origin/<default-branch>
```

Push the new branch so a PR can be opened:

```
cd <abs-worktree-path>
git push -u origin cloude/<slug>
```

## 5. Open the draft PR

```
cd <abs-worktree-path>
gh pr create --draft --base <default-branch> --head cloude/<slug> \
  --title "<idea heading text>" \
  --body "Draft PR for task <YYYY-MM-DD>-<slug>. Plan to follow."
```

Capture the returned PR URL as `<pr-url>`.

## 6. Create the active task file

```
cp <cloude-root>/TEMPLATE.org <cloude-root>/active/<YYYY-MM-DD>-<slug>.org
```

(Use today's date in `YYYY-MM-DD` format.)

Edit the new file:

- Replace `<task title>` in the heading with the idea heading text.
- Fill in the properties drawer:
  - `:ID:` → `<YYYY-MM-DD>-<slug>`
  - `:REPO:` → the project's `:REPO:` URL
  - `:BRANCH:` → `cloude/<slug>`
  - `:WORKTREE:` → the absolute worktree path
  - `:PR:` → `<pr-url>`
  - `:AGENT:` → leave blank
- If the staging entry had notes/body content, move them into the `Notes` section of the new file. Leave `Goal`, `Context`, and `Acceptance criteria` for the user to fill in during PLANNING.

Initial TODO state stays `PLANNING` and the heading tag stays `:user:`.

## 7. Remove the entry from staging.org

Delete the chosen idea sub-heading and its body from `staging.org`. Leave the project heading in place even if no ideas remain under it.

## 8. Create the tmux session and launch the container

Create a detached tmux session that runs `bin/cloude-run` in the worktree, so the dockerized Claude is up and waiting when the user attaches:

```
tmux new-session -d -s cloude-<slug> -c <abs-worktree-path> \
  "<cloude-root>/bin/cloude-run <abs-worktree-path> <abs-task-file-path>; exec bash"
```

The trailing `exec bash` keeps the pane alive after the container exits, so the user can rerun `cloude-run` (e.g., to resume work) without recreating the session.

If a session named `cloude-<slug>` already exists, stop and ask the user how to proceed (kill the existing one, rename, or abort).

## 9. Report

Summarize what was done:

- Active task file: `active/<YYYY-MM-DD>-<slug>.org`
- Source clone: `<source-clone>`
- Branch: `cloude/<slug>` (based on `<default-branch>`)
- Worktree: `<abs-worktree-path>`
- Draft PR: `<pr-url>`
- tmux session: `cloude-<slug>` running the dockerized Claude (attach with `tmux attach -t cloude-<slug>`)
- Staging entry removed.

The task is now in `PLANNING :user:` waiting for the user's planning prompt inside the container.
