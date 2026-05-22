---
description: Promote an idea from tasks/staging.org into an active task (file, branch, worktree, draft PR, tmux session)
---

You are promoting an idea from `tasks/staging.org` into an active task. The mechanical chain (clone, worktree, branch, PR, task file, staging removal, tmux session) lives in `bin/cloude-promote-setup`. This skill is a thin interactive wrapper: it picks the idea, detects standard vs ADOPT mode, derives the slug, then hands off to the script. If anything fails, stop and tell the user what the script reported succeeded vs. failed.

The cloude repo root (current working directory when this command was invoked) is the anchor for relative paths below.

## Two modes: standard vs ADOPT

- **Standard**: the typical case — fresh `cloude/<slug>` branch off the default branch, new draft PR, initial state `PLANNING :user:`.
- **ADOPT**: the chosen staging idea carries an `:ADOPT:` property in its properties drawer (value = PR URL of an existing open PR). No new branch or PR — the script checks out the existing PR's branch as a worktree. Initial state `ITERATING :user:`. The staging idea's heading text and body are free-form, just like a standard idea, and feed the same prefill prompt; ADOPT-mode is determined entirely by property presence.

The mode determines which flags are passed to `cloude-promote-setup`.

## Staging-idea properties recognized by `/promote`

`/promote` reads two optional properties from each staging idea sub-heading's properties drawer (in addition to the project-level `:REPO:` and `:SKIP_REVIEW:`):

- `:ADOPT: <pr-url>` — triggers ADOPT mode. The value is the URL of an existing open PR in the project's repo. Without this property, the idea promotes as a standard task.
- `:COMPANION: <task-id>` — sibling cloude task ID (slug-dated form, e.g. `2026-05-20-acme-webapp-side`). Copied verbatim into the new active task file's properties drawer. See `docs/internals.md` for the property's meaning on the active task.

Both are optional; absent properties take the defaults (standard mode, no companion).

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
- `HEADING` — the idea's heading text — verbatim, free-form, used in both modes (→ `--staging-heading` and `--heading`).
- `MODE` — `standard` or `adopt`, derived from the idea's `:ADOPT:` property (see step 2).
- `PR_URL` — the value of the idea's `:ADOPT:` property in ADOPT mode, empty otherwise.
- `COMPANION` — the value of the idea's optional `:COMPANION:` property (sibling cloude task ID), empty if absent. See step 4.
- `SKIP_REVIEW` — the project's optional `:SKIP_REVIEW:` property (`t` when the repo opts out of peer review, empty otherwise; see step 4).
- `SLUG` — the idea's optional `:SLUG:` property (pre-computed by the host-side staging-slug watcher — see [`/suggest-slugs-watch`](suggest-slugs-watch.md) / [`/suggest-slugs`](suggest-slugs.md)). Empty when no suggestion exists; step 3 falls back to the mechanical derivation in that case.

If the user names a TODO-project idea by some out-of-band shortcut, refuse: "that project has no `:REPO:` — its ideas are personal TODOs, not promotable. Add a `:REPO:` to the project heading first if you want to promote them."

## 2. Detect mode and (if ADOPT) gather PR details

`MODE` from step 1's `--select` output is the mode marker — `standard` or `adopt`. It's set from the staging idea's `:ADOPT:` property: present (and non-empty) → `adopt`, absent → `standard`. The `[ADOPT]` suffix in the plain listing is the same signal.

For ADOPT mode, the PR URL is `PR_URL` from step 1. Query the PR:

```
gh pr view <pr-url> --json number,state,headRefName,baseRefName,isCrossRepository,headRepositoryOwner,headRepository
```

Refuse to proceed if any of these fail:

- `state != "OPEN"` — `/finalize` handles closed/merged PRs; this skill only adopts open ones.
- `isCrossRepository == true` — we can't push to a fork's branch without an extra remote.
- The PR's repo doesn't match the project's `:REPO:` URL.

Record `<pr-url>`, `<pr-number>`, `<head-ref-name>`, `<base-ref-name>`. (The PR title isn't needed — the task title comes from the staging idea heading.)

For standard mode, look up the default branch:

```
gh repo view <owner>/<repo> --json defaultBranchRef -q .defaultBranchRef.name
```

(`<owner>/<repo>` is parsed from the project's `:REPO:` URL — both `git@github.com:OWNER/REPO[.git]` and `https://github.com/OWNER/REPO[.git]` forms are supported by the orchestrator.)

## 3. Confirm the slug

If `SLUG` from step 1's `--select` output is non-empty, use it verbatim as the proposed slug — that's the host claude's pre-computed suggestion (see `/suggest-slugs`), and it's likely shorter and clearer than the mechanical fallback below.

Otherwise, derive from the idea heading in both modes: lowercase, replace non-alphanumerics with `-`, collapse repeats, trim. E.g. `"Hook to auto-move COMPLETE files"` → `hook-to-auto-move-complete-files`. (In ADOPT mode, the worktree's local branch still uses the verbatim `<head-ref-name>` so pushes go to the right upstream — only the task slug / filename / tmux session / DinD volume names follow the heading.)

Show the proposed slug to the user and ask them to confirm or override (regardless of which source it came from). Compute the task file path: `<cloude-root>/tasks/active/$(date +%F)-<slug>.org`.

## 4. Run the setup

```
bin/cloude-promote-setup \
  --mode <standard|adopt> \
  --slug <slug> \
  --repo-url <repo-url> \
  --task-file <abs-task-file> \
  --staging-heading <exact-idea-heading-text> \
  --heading <idea-heading-text>
```

`--staging-heading` is the verbatim text used to locate and delete the idea from `tasks/staging.org`; `--heading` is the same text used as the task title and prefill prompt (they happen to be equal — the script keeps them as two flags so the search target is decoupled from any future title transformation).

Plus mode-specific flags:

- **Standard**: `--default-branch <default-branch>`
- **ADOPT**: `--head-ref <head-ref-name>` `--base-ref <base-ref-name>` `--pr-url <pr-url>` `--pr-number <pr-number>`

Plus, in either mode:

- If `SKIP_REVIEW` from step 1 is `t`, add `--skip-review`. That renders `:SKIP_REVIEW: t` into the new task file's properties drawer, so the repo's peer-review opt-out travels with the task the same way `:REPO:` does — and `/advance` will later skip the `REVIEW` stage (`ITERATING → MERGING`).
- If `COMPANION` from step 1 is non-empty, add `--companion <id>`. That renders `:COMPANION: <id>` into the new task file's properties drawer, so the sibling-task pointer travels with the task. See `docs/internals.md` for the property's documented meaning.

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

## 5. Report

Relay the script's summary block.
