---
description: Promote an idea from tasks/staging.org into an active task (file, branch, worktree, draft PR, tmux session)
---

You are promoting an idea from `tasks/staging.org` into an active task. The mechanical chain — listing the ideas, performing the gh discovery for each mode (default branch lookup for standard mode, PR validation for ADOPT mode), deriving the slug, opening the draft PR, creating the worktree and tmux session, removing the staging entry — lives in `bin/cloude-promote`, a deterministic Python orchestrator that itself exec's `bin/cloude-promote-setup`. This skill is a thin interactive wrapper: it shows the list, asks the user which idea to promote, then hands off entirely to `bin/cloude-promote --select N`.

The cloude repo root (current working directory when this command was invoked) is the anchor for relative paths below.

## 1. Show staging contents and pick an idea

Run:

```
bin/cloude-list-staging
```

Output looks like:

```
PROMOTABLE
1) [<vault-slug>/<project-name>] idea heading text  [ADOPT]
2) [<vault-slug>/<project-name>] another idea
...
TODO_PROJECTS  <count>
```

The `[<vault-slug>/<project-name>]` prefix shows which vault and project each idea belongs to. Present the numbered `PROMOTABLE` lines to the user verbatim. If `TODO_PROJECTS` is non-zero, print one short note above the listing: `(<count> TODO-project ideas omitted — those aren't promotable; see them in bin/cloude-dash.)` Ask which one to promote.

If the user names a TODO-project idea by some out-of-band shortcut, refuse: "that project has no `:REPO:` — its ideas are personal TODOs, not promotable. Add a `:REPO:` to the project heading first if you want to promote them."

## 2. Hand off to the orchestrator

Once the user picks a number `N`, run:

```
bin/cloude-promote --select N
```

That's it. `cloude-promote` does the gh discovery, slug derivation, mode detection, flag wiring, and exec's `cloude-promote-setup` to perform the worktree / PR / tmux setup. Relay its stdout/stderr to the user and report.

### Slug derivation

`cloude-promote` derives the slug deterministically with this precedence:

1. `--slug SLUG` flag (if you pass one),
2. the staging idea's `:SLUG:` property (if set on the idea's drawer),
3. otherwise auto-derived from the heading text (lowercase, non-alphanumerics replaced with `-`, trimmed).

If the user wants a slug different from the heading-derived default and there's no `:SLUG:` on the idea, pass `--slug <slug>` when invoking the orchestrator. Otherwise call it without that flag.

### Exit codes worth flagging

`cloude-promote`'s own failure modes (above `cloude-promote-setup`'s 10..30 range):

- `30` — argument validation (a flag is missing or malformed).
- `40` — `cloude-list-staging --select N` failed (typically the index is out of range, but also any parse failure on `staging.org`).
- `41` — resolved slug is empty (the heading has no alphanumeric characters and no `:SLUG:` was set; retry with `--slug`).
- `42` — `gh repo view` or `gh pr view` failed (often an auth problem or rate limit — relay the gh error to the user).
- `43` — ADOPT-mode PR is not OPEN, is cross-repository (head is in a fork), or lives in a different repo than the project's `:REPO:`. None of these are retried automatically; relay the message and ask the user how to proceed.

For `cloude-promote-setup`'s own 10..30 range, see its `--help`. The orchestrator passes those through unchanged.

## 3. Report

Relay the orchestrator's summary block as-is. It tells the user the new task file, branch, worktree, PR URL, tmux session, and starting state — everything they need to attach and start working.
