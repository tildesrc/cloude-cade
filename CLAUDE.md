# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

This repo holds the user's personal tools for parallelizing and managing
development with Claude Code. See `README.md` for the current description
of the repo and the task workflow.

## Keep README.md current

`README.md` is the canonical description of what this repo is and what
lives in it. Whenever you add, remove, or materially change a tool,
script, or workflow here, update `README.md` in the same change so it
stays accurate. If a change makes the README wrong, fixing the README is
part of the task, not a follow-up.

## Task tracking lives in the org files

The org files are the source of truth for in-flight work and its history:

All task tracking lives under `tasks/`:

- `tasks/staging.org` — captures not yet started, organized under
  top-level *project* headings. Each project carries a `:REPO:`
  property identifying its GitHub repo; that property travels with the
  task into the active file when it's promoted.
- `tasks/active/YYYY-MM-DD-<slug>.org` — one file per in-flight task.
- `tasks/completed/YYYY-MM-DD-<slug>.org` — one file per merged task.
- `tasks/dropped/YYYY-MM-DD-<slug>.org` — one file per abandoned task.
- `tasks/TEMPLATE.org` — starting scaffold for new active tasks; copy
  it, don't edit it in place.

Rules when working on a task:

- **Edit only your own task file.** The single-file-per-task layout is
  what makes concurrent agent updates safe; do not write into another
  task's file or into a shared index.
- **Update TODO state and tags as the situation changes** — the logbook
  drawer is the audit trail. Let org-mode populate it via state and tag
  transitions rather than writing prose history by hand.
- **Don't invent a parallel tracking scheme** (scratch files, ad-hoc
  TODO lists in code, a global index, etc.). Extend the org workflow
  instead.

### Workflow states

The TODO keywords are: `PLANNING`, `ITERATING`, `REVIEW`, `MERGING`,
`COMPLETE`, `DROPPED`. **Read the "Stage details" section of
`README.md` for the responsibilities and definition of done (DoD) of
each state — that is the canonical spec of what you must accomplish in
each stage.**

**Forward transitions out of `PLANNING`, `ITERATING`, and `REVIEW` are
user-driven only.** Do not advance these states on your own — finish
your work, set the heading's tag to `:user:`, and wait for the user to
move the task forward (or send you back with feedback). Transitioning
to `DROPPED` is allowed from any state but should also generally be a
user decision unless you have explicit authorization.

`MERGING` is different: it's an agent-driven stage where you actively
work to land the PR — handling CI failures and trivial merge conflicts.
Advance to `COMPLETE` yourself once the merge has actually landed.

### Who-has-the-ball tag

Every in-flight task heading carries a tag indicating who currently
has the ball:

- `:agent:` — you are working autonomously.
- `:user:` — the ball is in the user's court (you are waiting on user
  feedback, a decision, or a prompt to continue).
- `:blocked:` — waiting on something external to this workflow (peer
  reviewers, long-running external CI, an upstream dependency).
  `REVIEW` is `:blocked:` by default.

Flip this tag as the situation changes. This is *your* signal to the
user — keep it accurate so the user can tell at a glance which tasks
need their attention vs. which are progressing on their own vs. which
are waiting on something neither of you controls.

### Running inside the container

When an agent is launched via `bin/cloude-run`, it runs inside a Docker
container with `--dangerously-skip-permissions`. A few things to keep
in mind:

- The cloude repo, the task's worktree, and the task's active `.org`
  file are all mounted at the **same absolute paths** they have on the
  host. Cite paths verbatim — they're identical inside and out.
- The container has Docker-in-Docker, so `docker compose` works for
  spinning up the project's dev environment. The agent runs as an
  unprivileged user; only `dockerd` is privileged.
- The worktree is the cwd and writable. The task's `.org` file is
  writable. The rest of the cloude repo (other tasks, README, etc.) is
  read-only — treat the worktree as your sandbox.
- git and `gh` auth come from the host (`~/.gitconfig`, `~/.config/gh`,
  mounted read-only). Use them as you would on the host.

### Moving tasks between directories

- `tasks/staging.org` entry → `tasks/active/YYYY-MM-DD-<slug>.org`:
  when the user promotes a captured idea to active work. Carry the
  project's `:REPO:` property into the new file's properties drawer.
- `tasks/active/<file>.org` → `tasks/completed/<file>.org`: when the
  task reaches `COMPLETE` (PR merged). This file move is part of the
  COMPLETE stage's responsibility — perform it as the agent finishes
  merging.
- `tasks/active/<file>.org` → `tasks/dropped/<file>.org`: when the
  task reaches `DROPPED` (abandoned).

Keep the filename unchanged in both moves; only the directory changes.
