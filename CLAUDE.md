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

- `staging.org` — captures not yet started.
- `active/YYYY-MM-DD-<slug>.org` — one file per in-flight task.
- `completed/YYYY-MM-DD-<slug>.org` — one file per finished/dropped task.
- `TEMPLATE.org` — starting scaffold for new active tasks; copy it,
  don't edit it in place.

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
`COMPLETE`, `DROPPED`. See `README.md` for the meaning of each and the
allowed transitions.

**Forward transitions out of `PLANNING`, `ITERATING`, and `REVIEW` are
user-driven only.** Do not advance these states on your own — finish
your work, set the heading's tag to `:user:`, and wait for the user to
move the task forward (or send you back with feedback). Transitioning
to `DROPPED` is allowed from any state but should also generally be a
user decision unless you have explicit authorization.

`MERGING` is different: it's an agent-driven stage where you actively
work to land the PR — handling CI failures and trivial merge conflicts.
Advance to `COMPLETE` yourself once the merge has actually landed.

### Agent vs. user tag

Within `PLANNING`, `ITERATING`, and `MERGING`, the heading carries a
tag indicating who currently has the ball:

- `:agent:` — you are working autonomously.
- `:user:` — the ball is in the user's court (you are waiting on user
  feedback, a decision, or a prompt to continue).

Flip this tag as you transition between working and waiting. This is
*your* signal to the user — keep it accurate so the user can tell at a
glance which tasks need their attention.

### Moving tasks between directories

- `staging.org` entry → `active/YYYY-MM-DD-<slug>.org`: when the user
  promotes a captured idea to active work.
- `active/<file>.org` → `completed/<file>.org`: when the task reaches
  `COMPLETE` or `DROPPED`. Keep the filename; only the directory
  changes. The file move is the signal that the task has left active
  flight.
