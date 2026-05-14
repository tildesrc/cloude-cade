---
description: Promote an idea from tasks/staging.org into an active task (file, branch, worktree, draft PR, tmux session)
---

You are promoting an idea from `tasks/staging.org` into an active task. Walk through these steps interactively with the user. Do not skip steps; do not advance past a step until it has succeeded. If any step fails, stop and tell the user exactly what succeeded and what did not so they can clean up.

The cloude repo root (current working directory when this command was invoked) is the anchor for relative paths below.

## Two modes: standard vs ADOPT

There are two flavors of promotion:

- **Standard**: the typical case. The idea is a new piece of work, so the skill creates a fresh `cloude/<slug>` branch off the default branch and opens a draft PR. Initial state is `PLANNING :user:`.
- **ADOPT**: the idea heading is exactly `ADOPT <PR url>` (e.g., `ADOPT https://github.com/acme-co/acme-webapp/pull/123`). The skill **doesn't** create a new branch or PR — it adopts the existing PR's branch into a worktree and starts the task in `ITERATING :user:` (so the user can give the agent further direction without going through PLANNING).

Each numbered step below calls out when ADOPT behaves differently.

## 1. Show staging contents and pick an idea

Read `tasks/staging.org`. Parse it:

- Top-level headings (`*`) are projects. **Filter to projects that have a `:REPO:` property** — those are the promotable ones. A top-level heading without `:REPO:` is a "TODO project" whose sub-headings are personal TODOs the user works on without an agent (see `bin/cloude-dash`'s TODO section). `/promote` skips those entirely.
- Sub-headings (`**`) under each promotable project are ideas.

Present the ideas grouped by project, numbered globally so the user can pick by number. If you found any TODO projects (no `:REPO:`), mention that as one short line above the listing — e.g. `(TODO-project ideas under "Non-cloude" omitted — those aren't promotable; see them in bin/cloude-dash.)` Ask the user which one to promote.

If the user names a TODO-project idea by some out-of-band shortcut, refuse with: "that project has no `:REPO:` — its ideas are personal TODOs, not promotable. Add a `:REPO:` to the project heading first if you want to promote them."

## 2. Detect mode and (if ADOPT) gather PR details

If the chosen idea's heading text starts with `ADOPT ` followed by a URL, you're in **ADOPT mode**. Otherwise you're in **standard mode**.

For ADOPT mode:

- Extract the PR URL from the heading (everything after `ADOPT `).
- Query the PR:
  ```
  gh pr view <pr-url> --json number,title,state,headRefName,baseRefName,isCrossRepository,headRepositoryOwner,headRepository
  ```
- **Refuse to proceed** if any of these fail:
  - `state != "OPEN"` — abort and tell the user what state the PR is in. `/finalize` handles closed/merged PRs; this skill only adopts open ones.
  - `isCrossRepository == true` — abort. We can't push to a fork's branch without configuring an extra remote, and the workflow assumes you can push back to where the PR lives.
  - The PR's repo doesn't match the project's `:REPO:` URL — abort with a clear "PR repo doesn't match the staging project's :REPO:" message.
- Store as `<pr-url>`, `<pr-number>`, `<pr-title>`, `<head-ref-name>` (the PR's branch), `<base-ref-name>` (its base branch). These replace the values that the standard flow would normally derive from staging text + default branch.

## 3. Confirm the slug

**Standard mode** — auto-derive a slug from the chosen idea's heading text:

- Lowercase
- Replace non-alphanumerics with hyphens
- Collapse repeated hyphens
- Trim leading/trailing hyphens

**ADOPT mode** — auto-derive the slug from `<head-ref-name>` (the PR's branch) using the same rules. E.g., `feature/wire-config-volume` becomes `feature-wire-config-volume`. The slug only needs to be a safe filesystem/tmux name; the worktree's local branch will use the verbatim `<head-ref-name>` so pushes go to the right place.

Show the proposed slug to the user and ask them to confirm or override.

## 4. Determine repo info and ensure the source clone exists

From the project's `:REPO:` URL (same logic in both modes):

- Extract the **owner** and **repo name** (handle both forms — `git@github.com:OWNER/REPO[.git]` and `https://github.com/OWNER/REPO[.git]`).
- Compute the **HTTPS clone URL**: `https://github.com/<owner>/<repo>.git`. We want the remote in HTTPS form so the in-container `git push` (which has no SSH keys, only a forwarded `GH_TOKEN`) works.
- The source clone lives at `<cloude-root>/repos/<repo-name>`. If it doesn't exist yet, clone it via `gh repo clone` (which uses gh's auth, so private repos work even when the host has no git credential helper configured globally), normalize the remote to HTTPS, and configure the gh credential helper for this repo:
  ```
  mkdir -p <cloude-root>/repos
  gh repo clone <owner>/<repo> <cloude-root>/repos/<repo-name>
  git -C <cloude-root>/repos/<repo-name> remote set-url origin <https-clone-url>
  git -C <cloude-root>/repos/<repo-name> \
      config credential."https://github.com".helper '!gh auth git-credential'
  ```
  Why each step:
  - `gh repo clone` instead of `git clone` — `gh` always carries the user's PAT, so private repos clone without the host needing a global git credential helper. Plain `git clone` of a private repo fails with "could not read Username".
  - `remote set-url origin <https-clone-url>` — `gh repo clone` honors gh's configured `git_protocol` (which can be ssh). We want HTTPS regardless, so the in-container container can push using the forwarded `GH_TOKEN` rather than SSH keys it doesn't have.
  - The per-repo credential helper makes all subsequent `git fetch`/`push` against this clone auth through `gh` on the host (and the container's `/etc/gitconfig` configures the same helper for inside the container).
- **Standard mode only**: detect the default branch:
  ```
  gh repo view <owner>/<repo> --json defaultBranchRef -q .defaultBranchRef.name
  ```
  Store as `<default-branch>`. (ADOPT mode uses `<base-ref-name>` from step 2 instead.)

Store as `<repo-name>`, `<source-clone>`.

## 5. Create the worktree and branch

Compute the absolute worktree path: `<cloude-root>/worktrees/<repo-name>/<slug>`. Make sure the parent directory exists (`mkdir -p`).

**Standard mode** — fetch the default branch and create a new local branch `cloude/<slug>` off it:

```
git -C <source-clone> fetch origin <default-branch>
git -C <source-clone> worktree add -b cloude/<slug> <abs-worktree-path> origin/<default-branch>
```

Push the new branch so a PR can be opened:

```
git -C <abs-worktree-path> push -u origin cloude/<slug>
```

**ADOPT mode** — fetch the PR's existing branch and create a worktree tracking it. **Don't** push (the branch already exists upstream).

```
git -C <source-clone> fetch origin <head-ref-name>:refs/remotes/origin/<head-ref-name>
git -C <source-clone> worktree add -b <head-ref-name> <abs-worktree-path> origin/<head-ref-name>
```

If a local branch named `<head-ref-name>` already exists in the source clone (rare — only if the user manually checked it out before), use `-B` instead of `-b` (or stop and ask). The new local branch tracks `origin/<head-ref-name>`, so `git push` from inside the worktree pushes back to the right upstream branch.

## 6. Open the draft PR (standard mode only)

**Standard mode**:

```
git -C <abs-worktree-path> ...
gh pr create --draft --base <default-branch> --head cloude/<slug> \
  --title "<idea heading text>" \
  --body "Draft PR for task <YYYY-MM-DD>-<slug>. Plan to follow."
```

Capture the returned PR URL as `<pr-url>`.

**ADOPT mode** — skip this step entirely. We already have `<pr-url>` from step 2.

## 7. Create the active task file

```
cp <cloude-root>/tasks/TEMPLATE.org <cloude-root>/tasks/active/<YYYY-MM-DD>-<slug>.org
```

(Use today's date in `YYYY-MM-DD` format.)

Edit the new file. The properties drawer is the same in both modes; the heading line and starting state differ:

| Field            | Standard mode                              | ADOPT mode                                   |
| ---------------- | ------------------------------------------ | -------------------------------------------- |
| Heading TODO     | `PLANNING`                                 | `ITERATING`                                  |
| Heading tag      | `:user:`                                   | `:user:`                                     |
| Heading text     | `<idea heading text>`                      | `<pr-title>` (the PR's title from step 2)    |
| `:ID:`           | `<YYYY-MM-DD>-<slug>`                      | same                                         |
| `:REPO:`         | the project's `:REPO:` URL                 | same                                         |
| `:BRANCH:`       | `cloude/<slug>`                            | `<head-ref-name>` (the PR's actual branch)   |
| `:WORKTREE:`     | the absolute worktree path                 | same                                         |
| `:PR:`           | `<pr-url>` from step 6                     | `<pr-url>` from step 2                       |
| `:AGENT:`        | blank                                      | blank                                        |

In ADOPT mode, also add a `:ADOPTED:` property set to `t` (or any truthy value) so it's easy to grep for adopted tasks later, and add a brief Notes line: `Adopted from PR <pr-url> — original heading: ADOPT <pr-url>`.

**Companion-task detection (both modes)** — if the staging heading text references another PR (e.g., `acme-webapp changes for https://github.com/.../pull/124` or `Frontend for PR #123`), add a `:COMPANION_PR:` property to the drawer with the referenced PR's full URL. Don't try to parse fancy patterns; if the heading clearly names a sibling PR that this task is paired with, capture it. Note the companion link in the `Notes` section too. See `README.md` for the property's documented meaning.

If the staging entry had body content, move it into the `Notes` section. Leave `Goal`, `Context`, and `Acceptance criteria` for the user to fill in.

## 8. Remove the entry from tasks/staging.org

Delete the chosen idea sub-heading and its body from `tasks/staging.org`. Leave the project heading in place even if no ideas remain under it.

## 9. Commit the promotion in the cloude repo

Stage the new active task file and the staging.org edit, then commit. Don't use `git add -A` — stage these two paths by name to avoid sweeping in any unrelated work:

```
git -C <cloude-root> add tasks/staging.org tasks/active/<YYYY-MM-DD>-<slug>.org
git -C <cloude-root> commit -m "Promote: <heading text>"      # standard
git -C <cloude-root> commit -m "Adopt: <pr-title> (#<pr-number>)"   # ADOPT
```

If `git status` shows nothing to commit, skip this step.

## 10. Create the tmux session and launch the container

Create a detached tmux session that runs `bin/cloude-run` in the worktree:

```
tmux new-session -d -s cloude-<slug> -c <abs-worktree-path> \
  "<cloude-root>/bin/cloude-run <abs-worktree-path> <abs-task-file-path>; exec bash"
```

The trailing `exec bash` keeps the pane alive after the container exits.

If a session named `cloude-<slug>` already exists, stop and ask the user how to proceed (kill the existing one, rename, or abort).

## 11. Report

Summarize what was done. Standard mode:

- Mode: standard
- Active task file: `tasks/active/<YYYY-MM-DD>-<slug>.org`
- Source clone: `<source-clone>`
- Branch: `cloude/<slug>` (based on `<default-branch>`)
- Worktree: `<abs-worktree-path>`
- Draft PR: `<pr-url>`
- tmux session: `cloude-<slug>` (attach with `tmux attach -t cloude-<slug>`)
- Staging entry removed.
- Starting state: `PLANNING :user:` — waiting for the user's planning prompt.

ADOPT mode:

- Mode: ADOPT (PR #`<pr-number>`)
- Active task file: `tasks/active/<YYYY-MM-DD>-<slug>.org`
- Source clone: `<source-clone>`
- Branch: `<head-ref-name>` (tracking `origin/<head-ref-name>`)
- Worktree: `<abs-worktree-path>`
- Existing PR: `<pr-url>`
- tmux session: `cloude-<slug>` (attach with `tmux attach -t cloude-<slug>`)
- Staging entry removed.
- Starting state: `ITERATING :user:` — waiting for the user's direction on what to do with the adopted PR.
