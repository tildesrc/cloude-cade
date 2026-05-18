---
description: Promote an idea from tasks/staging.org into an active task (file, branch, worktree, draft PR, tmux session)
---

You are promoting an idea from `tasks/staging.org` into an active task. The mechanical chain (clone, worktree, branch, PR, task file, staging removal, tmux session) lives in `bin/cloude-promote-setup`. This skill is a thin interactive wrapper: it picks the idea, detects standard vs ADOPT mode, derives the slug, then hands off to the script. If anything fails, stop and tell the user what the script reported succeeded vs. failed.

The cloude repo root (current working directory when this command was invoked) is the anchor for relative paths below.

## Two modes: standard vs ADOPT

- **Standard**: the typical case — fresh `cloude/<slug>` branch off the default branch, new draft PR, initial state `PLANNING :user:`.
- **ADOPT**: the chosen idea's heading is `ADOPT <PR url>`. No new branch or PR — the script checks out the existing PR's branch as a worktree. Initial state `ITERATING :user:`.

The mode determines which flags are passed to `cloude-promote-setup`.

## 1. Show staging contents and pick an idea

Run:

```
bin/cloude-list-staging
```

Output looks like:

```
PROMOTABLE
1) [project-name] idea heading text  [ADOPT]
2) [project-name] another idea
...
TODO_PROJECTS  <count>
```

Present the numbered `PROMOTABLE` lines to the user. If `TODO_PROJECTS` is non-zero, print one short note above the listing: `(<count> TODO-project ideas omitted — those aren't promotable; see them in bin/cloude-dash.)` Ask which one to promote.

Once the user picks a number `N`, recover that idea's full record — don't re-read `tasks/staging.org` by hand:

```
bin/cloude-list-staging --select <N>
```

`eval` its stdout — it emits shell-safe `KEY=VALUE` lines for the chosen index:

- `REPO` — the project's `:REPO:` URL (→ `--repo-url`).
- `HEADING` — the exact idea heading text (→ `--staging-heading`, and `--heading` in standard mode).
- `MODE` — `standard` or `adopt` (see step 2).
- `PR_URL` — the adopted PR URL in ADOPT mode, empty otherwise.

If the user names a TODO-project idea by some out-of-band shortcut, refuse: "that project has no `:REPO:` — its ideas are personal TODOs, not promotable. Add a `:REPO:` to the project heading first if you want to promote them."

## 2. Detect mode and (if ADOPT) gather PR details

`MODE` from step 1's `--select` output is the mode marker — `standard` or `adopt`. (The `[ADOPT]` suffix in the plain listing is the same signal, derived from the idea heading starting with `ADOPT `.)

For ADOPT mode, the PR URL is `PR_URL` from step 1. Query the PR:

```
gh pr view <pr-url> --json number,title,state,headRefName,baseRefName,isCrossRepository,headRepositoryOwner,headRepository
```

Refuse to proceed if any of these fail:

- `state != "OPEN"` — `/finalize` handles closed/merged PRs; this skill only adopts open ones.
- `isCrossRepository == true` — we can't push to a fork's branch without an extra remote.
- The PR's repo doesn't match the project's `:REPO:` URL.

Record `<pr-url>`, `<pr-number>`, `<pr-title>`, `<head-ref-name>`, `<base-ref-name>`.

For standard mode, look up the default branch:

```
gh repo view <owner>/<repo> --json defaultBranchRef -q .defaultBranchRef.name
```

(`<owner>/<repo>` is parsed from the project's `:REPO:` URL — both `git@github.com:OWNER/REPO[.git]` and `https://github.com/OWNER/REPO[.git]` forms are supported by the orchestrator.)

## 3. Confirm the slug

- **Standard mode** — derive from the idea heading: lowercase, replace non-alphanumerics with `-`, collapse repeats, trim. E.g. `"Hook to auto-move COMPLETE files"` → `hook-to-auto-move-complete-files`.
- **ADOPT mode** — derive from `<head-ref-name>` using the same rules (slashes in branch names become hyphens). The worktree's local branch uses the verbatim `<head-ref-name>` so pushes go to the right upstream.

Show the proposed slug to the user and ask them to confirm or override. Compute the task file path: `<cloude-root>/tasks/active/$(date +%F)-<slug>.org`.

## 4. Run the setup

```
bin/cloude-promote-setup \
  --mode <standard|adopt> \
  --slug <slug> \
  --repo-url <repo-url> \
  --task-file <abs-task-file> \
  --staging-heading <exact-idea-heading-text>
```

Plus mode-specific flags:

- **Standard**: `--heading <idea-heading-text>` `--default-branch <default-branch>`
- **ADOPT**: `--head-ref <head-ref-name>` `--base-ref <base-ref-name>` `--pr-url <pr-url>` `--pr-title <pr-title>` `--pr-number <pr-number>`

The script ensures the source clone exists, creates the worktree + branch, opens the draft PR (standard only), renders the task file from `tasks/TEMPLATE.org`, removes the idea from `tasks/staging.org`, and starts the detached tmux session.

On success (exit 0), relay the script's summary block.

On failure, the script's stderr includes a "Succeeded so far" list so the user can clean up the partial state. Exit codes:

- `10` — source clone setup failed.
- `11` — worktree creation failed.
- `12` — `gh pr create` failed (standard only).
- `13` — task-file render failed.
- `14` — staging entry not found / removal failed (the heading text didn't match what's in `tasks/staging.org`).
- `20` — tmux session name `cloude-<slug>` already exists. Ask the user how to proceed (kill the existing session, pick a different slug, or abort) — don't retry without explicit user direction.
- `30` — argument validation failed (a required flag was missing or malformed).

## 5. Companion-PR detection (optional, post-render)

If the chosen idea's heading text clearly names a sibling PR this task is paired with — patterns like `"acme-webapp changes for https://github.com/.../pull/124"` or `"Frontend for PR #123"` — add a `:COMPANION_PR:` property to the new task file's properties drawer with the referenced PR's full URL, and add a one-line note in the Notes section. This is judgment-call pattern matching; don't try to be clever. See `README.md` for the property's documented meaning.

## 6. Report

Relay the script's summary block plus any companion-PR addition from step 5.
