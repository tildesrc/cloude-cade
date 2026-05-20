# cloude

Go from solo mode to YOLO mode.

## What this is for

This repo is a workspace for scripts, configs, and utilities that support
agent-driven development end-to-end — from picking up a task to landing it.

Beyond the mechanical overhead of running Claude Code (worktrees, branches,
PR triage, scheduled jobs, etc.), the larger goal is to manage the
*workflow* of development tasks from beginning to end. Agents change the
shape of that workflow: they enable — and require — far more multitasking
than unassisted development, with several pieces of work in flight at once and
agents running unattended in the background.

That makes it essential to have a well-defined workflow that distinguishes:

- **Foreground work** — tasks that need active developer attention
  (decisions, reviews, ambiguous requirements, risky changes).
- **Background work** — tasks an agent can run to completion alone, with
  the developer only checking results when they land.

The tools in this repo exist to make that distinction explicit and to keep
the right things flowing through the right lane.

## Quickstart

New to cloude? This section is the fast path — prerequisites, one-time
setup, the workflow at a glance, and one task taken from idea to merged
PR. The sections below it are the full reference.

### Prerequisites

- **Docker**, with the daemon running — every task's agent runs in a
  sandboxed container.
- **[`uv`](https://docs.astral.sh/uv/)** — runs the PEP 723 scripts
  (`bin/cloude-dash` and the org-file helpers) with their dependencies
  handled transparently.
- **`gh`**, authenticated (`gh auth login`) — used to open and manage PRs.
- **`git`**.
- **Claude Code** — the `claude` CLI.

### One-time setup

```sh
make build       # build the container image (a few minutes the first time)
make login       # interactive claude login — do this once per workstation
```

After `make login` exits, your Claude credentials live in the
`cloude-claude-creds` Docker volume and persist across every task and
restart, so you won't need to log in again. Run `make help` for the
rest of the targets (rebuild, clean, etc.).

### The workflow at a glance

```mermaid
flowchart TD
    subgraph host["🖥️  Host side"]
        STAGING["tasks/staging.org<br/>captured ideas"]
        CLEANUP["/sweep → /finalize<br/>move file to completed/, tear down worktree"]
    end

    subgraph container["📦  Docker container — one per task, own tmux session"]
        direction TB
        PLANNING["PLANNING<br/>agent plans, user approves"]
        ITERATING["ITERATING<br/>agent codes, /babysit-ci watches CI"]
        REVIEW["REVIEW<br/>waiting on peer review"]
        MERGING["MERGING<br/>/babysit-merge drives merge queue"]
        COMPLETE["COMPLETE — PR merged"]
        DROPPED["DROPPED — task abandoned"]
    end

    STAGING -->|"/promote"| PLANNING
    PLANNING -->|"approved"| ITERATING
    ITERATING -->|"/advance"| REVIEW
    REVIEW -->|"/advance"| MERGING
    ITERATING -->|"/advance · :SKIP_REVIEW: repo"| MERGING
    MERGING -->|"/babysit-merge"| COMPLETE
    COMPLETE -->|"/sweep"| CLEANUP

    REVIEW -.->|"/iterate"| ITERATING
    MERGING -.->|"/iterate"| ITERATING
    ITERATING -.->|"/drop"| DROPPED
    DROPPED -.->|"/sweep"| CLEANUP
```

Solid arrows are the happy path; dashed arrows are the escape hatches
(`/iterate` back a stage, `/drop` to abandon). Note the split: you work
from the **host side** — capturing ideas, promoting, and cleaning
up — while each task's agent runs in its **own container and tmux
session**. Forward
transitions out of `PLANNING`, `ITERATING`, and `REVIEW` are user-driven;
only `MERGING → COMPLETE` advances on its own. Repos that opt out of
peer review (`:SKIP_REVIEW: t`, see [Workflow states](#workflow-states))
skip `REVIEW` — `/advance` takes the task straight from `ITERATING` to
`MERGING`.

### The host side

The *host side* is where you coordinate the per-task containers without
writing any task code yourself. It is three things you keep open:

- **An editor on `tasks/staging.org`** (Emacs — the task files are
  org-mode). This is where you capture ideas as they come up, as
  sub-headings under their project, ready to `/promote` later.
- **A host Claude session** in the cloude repo. This is where you
  *start* and *retire* tasks: `/promote` to spin one up, `/sweep` and
  `/finalize` to clean it up once it's merged.
- **The dashboard**, `bin/cloude-dash` — a TUI listing every task with
  its stage and a who-has-the-ball tag: `:agent:` (running on its own),
  `:user:` (waiting on you), or `:blocked:` (waiting on something
  external).

The work itself happens elsewhere — every task `/promote` creates runs
in its own container with its own Claude agent. The host side is
mission control: capture and start tasks, monitor the in-flight ones,
and clean them up when they land.

Here it is on a typical day — every task on one screen, ranked by
stage, each tagged with who currently has the ball — `:agent:`,
`:user:`, or `:blocked:` (the live TUI colour-codes the tag too) — and
labelled with the repo it belongs to:

```text
cloude tasks      ↑/↓ move  p open PR  t tmux  c copy slug  r reload  q quit

ACTIVE (4)
  MERGING   :agent:    Cache the dashboard customer lookup PR #312  Acme Webapp
  REVIEW    :blocked:  Add rate-limit headers to the API      PR #305  Acme API
> ITERATING :user:     Create a quickstart guide for cloude     PR #298  Cloude
  PLANNING  :user:     Migrate the billing cron job            PR #314  Billing
STAGING (2)
  —                    Retry webhook deliveries with backoff  Acme API
  —                    Drop the legacy /v1 search endpoint    Acme API
RECENT (2)
  COMPLETE  2026-05-14  fix-flaky-auth-retry-test               Cloude
  DROPPED   2026-05-12  prototype-graphql-gateway          Acme Webapp
```

The `:user:` rows are the point — the tasks that need feedback right
now (a planning prompt, a plan to approve, a decision). Highlight one
and press `t` to drop straight into that task, give the agent what it
needs, then jump back to the dashboard and move to the next `:user:`
row. You monitor from the host side and dip into a task only where
attention is wanted, so background work stays in the background.

Run `bin/cloude-dash` itself inside a tmux session to make that jumping
seamless: with the dashboard in tmux, `t` uses `tmux switch-client`
(rather than `attach`), so flipping into a task's session is instant.
To jump back, use tmux's default "switch to last session" binding —
`Ctrl-b L` — which lands you straight on the dashboard, with no
detaching or reattaching.

Press `c` on a highlighted task to copy its slug — the `<slug>` of
`YYYY-MM-DD-<slug>.org`, and the handle the branch, worktree, and tmux
session are all named after — to the system clipboard, ready to paste
into a command.

```sh
bin/cloude-dash    # /: search · p: open PR · t: switch to task · c: copy slug · r: reload · q: quit
```

See [Dashboard](#dashboard) for the full key list.

### Your first task

1. **Capture the idea.** Add a sub-heading under a project in
   `tasks/staging.org`. The project's top-level heading needs a `:REPO:`
   property pointing at its GitHub repo (see [staging.org
   structure](#stagingorg-structure)).
2. **Promote it.** Run `/promote` from your host Claude session. It
   creates the active task file, a `cloude/<slug>` branch, a worktree, a
   draft PR, and a detached `cloude-<slug>` tmux session. The task starts
   in `PLANNING :user:` — waiting for you.
3. **Plan.** Attach to the task's tmux session (`tmux attach -t
   cloude-<slug>`, or press `t` on the dashboard). The agent's input
   box comes pre-filled with the promoted staging entry as a planning
   prompt — press Enter to start planning, or edit it first. A hook
   flips the task to `:agent:` so the dashboard shows it's now
   progressing on its own. When you approve its plan, another hook
   flips the task to `ITERATING` automatically.
4. **Iterate.** The agent implements the plan and pushes; `/babysit-ci`
   watches CI after each push. When a stage's work is done the agent
   flips its tag to `:user:` — that's your cue to run `/advance` to move
   `ITERATING → REVIEW → MERGING`.
5. **Merge.** In `MERGING`, `/babysit-merge` drives the merge queue and
   auto-advances the task to `COMPLETE` once the PR lands.
6. **Clean up.** Back on the host, `/sweep` surfaces finished tasks and
   `/finalize` moves the file to `tasks/completed/` and tears down the
   worktree, tmux session, and branch.

### Where to go next

- [Workflow states](#workflow-states) — what each TODO keyword means.
- [Slash commands](#slash-commands) — full detail on `/promote`,
  `/advance`, `/babysit-ci`, `/finalize`, and the rest.
- [`docs/internals.md`](docs/internals.md) — the agent-facing wiring
  reference (helper scripts, in-container hooks, container internals).

## Task tracking

Each chunk of work — its current state and full history — is tracked in an
Emacs `org-mode` file. The layout is designed so that multiple agents can
update task state concurrently without conflicting:

```
tasks/
  staging.org            ;; lightweight captures, not yet started
  active/                ;; one file per in-flight task
    YYYY-MM-DD-<slug>.org
  completed/             ;; one file per merged task (COMPLETE)
    YYYY-MM-DD-<slug>.org
  dropped/               ;; one file per abandoned task (DROPPED)
    YYYY-MM-DD-<slug>.org
  TEMPLATE.org           ;; scaffold for new active tasks (copy, don't edit)
```

- **Top-level state** is encoded by which directory a task lives in
  (`tasks/staging.org` → `tasks/active/` → `tasks/completed/` or
  `tasks/dropped/`). The high-level overview comes from directory
  listings, not a global index file.
- **Workflow stage** is encoded by the TODO keyword inside each active
  file (see below), so org-mode's logbook captures every state transition.
- **One file per task** means each agent edits its own file. Concurrent
  agents updating their own tasks don't conflict.

Each active task file's heading carries a properties drawer with
metadata (`:REPO:`, `:BRANCH:`, `:WORKTREE:`, `:PR:`, etc.) that the
agent fills in as the task progresses. You normally don't hand-edit
those fields — see [`docs/internals.md`](docs/internals.md) for the
full schema.

### Workflow states

| State        | Meaning                                                                      | Can move to                  |
| ------------ | ---------------------------------------------------------------------------- | ---------------------------- |
| `PLANNING`   | Claude is planning the work.                                                  | `ITERATING`, `DROPPED`       |
| `ITERATING`  | Claude is writing code, running tests, updating the PR title/description, waiting on CI. | `REVIEW` (or `MERGING`, see below), `DROPPED` |
| `REVIEW`     | PR is open for peer review, waiting on comments.                              | `ITERATING`, `MERGING`, `DROPPED` |
| `MERGING`    | PR is approved and ready to merge.                                            | `COMPLETE`, `DROPPED`        |
| `COMPLETE`   | PR is merged. Terminal.                                                       | —                            |
| `DROPPED`    | Task abandoned. Terminal.                                                     | —                            |

Forward transitions out of `PLANNING`, `ITERATING`, and `REVIEW` are
**user-driven only** — the agent does not advance these states on its
own; it must wait for the user to make the call. Any state can transition
to `DROPPED` at any time.

**Skipping peer review.** A repo can opt out of peer review. When a
task's properties drawer carries `:SKIP_REVIEW: t` (copied from its
staging project — see [staging.org structure](#stagingorg-structure)),
`/advance` skips the `REVIEW` stage and moves the task straight from
`ITERATING` to `MERGING`. The `REVIEW` keyword still exists; it's simply
never entered for such tasks.

### Who-has-the-ball tag

Every in-flight task carries an org tag on its heading indicating who
currently has the ball:

- `:agent:` — the agent is working autonomously.
- `:user:` — the ball is in the user's court (the agent is waiting on
  user feedback, a decision, or a prompt to continue).
- `:blocked:` — waiting on something external to this workflow (peer
  reviewers, long-running external CI, an upstream dependency, etc.).

The agent flips its own tag as it transitions between working, waiting
on the user, and waiting on something external. It does **not** advance
the TODO state itself (except `MERGING → COMPLETE`) — that's the user's
call.

### staging.org structure

Top-level headings in `tasks/staging.org` are **projects**. A project
carries a `:REPO:` property pointing to its GitHub repo, so when a
task is promoted from staging to active the agent knows which repo to
open a branch in. Ideas live as sub-headings under their project:

```org
* cloude
  :PROPERTIES:
  :REPO: https://github.com/<org>/cloude
  :END:
** Add a task-promotion script
** Hook to auto-move COMPLETE files
```

A project may also carry an optional `:SKIP_REVIEW: t` property. It
marks a repo that doesn't require peer review: `/promote` copies it
into every task file promoted from that project (the same way `:REPO:`
travels), and `/advance` then skips the `REVIEW` stage for those tasks
(see [Workflow states](#workflow-states)). Omit it for repos that do
require review — that's the default.

```org
* cloude-cade
  :PROPERTIES:
  :REPO: https://github.com/<org>/cloude-cade
  :SKIP_REVIEW: t
  :END:
** Add a task-promotion script
```

A top-level heading **without** `:REPO:` is treated as a **TODO
project** — its sub-headings are personal TODOs the user works on
themselves, not promotable agent-driven tasks. On the dashboard each
entry appears under a section header that matches its org TODO
keyword (`DONE`, `WAITING`, …), with entries that have no keyword
falling back to a default `TODO` section. `/promote` skips them:

```org
* Non-cloude
** Get recall precision curve for recent predictions in live nation
** Reply to the design doc thread
```

You can delete TODOs when finished — there's no separate
"completed" pile for them.

## Dashboard

`bin/cloude-dash` is a curses TUI that surfaces the state of every task
in one screen. It parses each `tasks/**/*.org` file with `orgparse` and
renders the following sections:

- **ACTIVE** — one row per file in `tasks/active/`, sorted by stage
  priority (`MERGING` first, then `REVIEW`, `ITERATING`, `PLANNING`).
  Each row shows the TODO keyword, who currently has the ball
  (`:agent:` green, `:user:` yellow, `:blocked:` red), the heading,
  then a right-aligned repo label and the PR number from the `:PR:`
  property. A task that has reached a terminal state
  (`COMPLETE`/`DROPPED`) but is still awaiting host-side `/finalize`
  shows no ball tag — the tag is only meaningful while a task is in
  flight.
- **STAGING** — idea sub-headings under top-level projects that have a
  `:REPO:` property (i.e. promotable via `/promote`).
- **One section per TODO keyword** for idea sub-headings under
  top-level projects that have no `:REPO:` (personal TODOs the user
  works on without an agent). The keyword itself is the section
  header — e.g. `DONE`, `WAITING`. Entries with no keyword fall back
  to a default `TODO` header. These sections render alphabetically by
  keyword between `STAGING` and `RECENT`, and each row is prefixed
  with the project name in brackets (e.g. `[Live Nation] …`). Not
  promotable.
- **RECENT** — the 20 most-recently-touched files from
  `tasks/completed/` and `tasks/dropped/`.

ACTIVE, STAGING, and RECENT rows are labelled with the repo the task
belongs to, shown right-aligned just left of the PR number. The label
is the **`staging.org` project section header** — the human name of
the top-level project the task's `:REPO:` URL belongs to. The
dashboard inverts the staging projects' `:REPO:` properties into a
URL → header map, so an active or recent task carrying the same
`:REPO:` URL is shown under its project's name. A task whose `:REPO:`
matches no staging project falls back to an `owner/repo` label.
Personal-TODO rows (non-repo projects) carry no repo label.

Keys: `↑`/`↓` or `j`/`k` move, `g`/`G` jump to top/bottom, `p` opens
the highlighted task's PR in the default browser, `t` switches to its
`cloude-<slug>` tmux session (uses `tmux switch-client` when the
dashboard is already inside tmux, otherwise `tmux attach`), `r`
reloads, `q` quits.

Press `/` to enter search-as-you-type mode. The status line shows the
query as you type; rows are filtered fzf-style to those whose title
contains the query (case-insensitive substring), and surviving section
headers show `(matched/total)` so you can see what's been filtered out.
`↑`/`↓` still navigate the filtered list while typing. `Esc` clears
the query and exits search mode; `Enter` locks the filter, restoring
the normal keymap (`j`/`k`/`p`/`t`/`c`/`g`/`G`/`r`) over the filtered
set — `Esc` while locked clears the filter, and `/` from a locked
filter starts a fresh query.

The dashboard auto-reloads (via inotify) whenever a task file changes,
and a reload can reorder rows — a stage transition re-sorts a task
within ACTIVE, a new task can appear above it, or it can move into
RECENT. The highlight tracks the *task*, not the row index: across any
reload (auto or `r`) it stays on whatever task you had selected. If
that task disappears entirely, the highlight falls back to the first
row.

```sh
bin/cloude-dash
```

The script has a PEP 723 inline-dependency header, so the recommended
launcher is `uv` — it handles the `orgparse` install transparently.
If `uv` isn't available, `pip install --user orgparse` then run the
script with `python3`.

## Per-repo pre-launch hooks

Some projects ship config that doesn't behave inside the per-task
container — plugin entries pointing at host binaries, project skills
that depend on external services, etc. To shape the worktree before
the container starts, drop an executable script at:

```
repo-hooks/<repo-name>          (e.g. repo-hooks/acme-webapp)
```

The launcher invokes the hook (if present and executable) with cwd =
the worktree, just before launching the container. The hook gets these
env vars:

- `CLOUDE_WORKTREE` — absolute path of the task worktree.
- `CLOUDE_TASK_FILE` — absolute path of the active task `.org` file.
- `CLOUDE_REPO_NAME` — the repo name (matches the hook filename).

A failed hook (nonzero exit) aborts the launch.

Typical use: delete or edit a file the container shouldn't see, then
hide the change from `git status` via `git update-index
--skip-worktree <file>` (for tracked files) or by appending to
`.git/info/exclude` (for untracked files). Worktrees have their own
`index` and `info/exclude`, so these changes are isolated to the one
worktree.

## Slash commands

Project-scoped slash commands live in `.claude/commands/`. The ones
you invoke by hand:

**Host-side** (run from your host Claude session, in the cloude repo):

- **`/promote`** — Promote an idea from `tasks/staging.org` into an
  active task. Interactive: lists ideas grouped by project, asks
  which to promote, auto-slugs the heading. Standard mode creates a
  `cloude/<slug>` branch, a worktree under
  `worktrees/<repo-name>/<slug>`, a draft PR, and a detached
  `cloude-<slug>` tmux session — starts in `PLANNING :user:`, with
  the container's Claude Code input box pre-filled with the staging
  entry as the planning prompt. If the staging idea is `ADOPT <PR
  url>`, switches to **ADOPT mode**: no new branch or PR, checks out
  the existing PR's branch and starts in `ITERATING :user:` so you
  can direct the agent on what to do with the adopted work.
- **`/sweep`** — Scan `tasks/active/` for tasks whose TODO keyword is
  already `COMPLETE` or `DROPPED` (the in-container agent has flipped
  the state but the file is still in `active/`). For each candidate,
  prompts `Approve /finalize for <task>? [y/N/skip]` and only invokes
  `/finalize` on an explicit `y`. Quick to run (one line of output
  when nothing's pending), so safe to drive on a `/loop` poll (e.g.
  `/loop 1m /sweep`) in your main host session.
- **`/finalize`** — Finalize an active task and perform the cleanup
  the in-container agent can't do (the cloude repo is mounted ro from
  inside the container). Interactive: lists active tasks with their
  current TODO state, asks which to finalize. For `COMPLETE`,
  verifies the PR is merged, kills the tmux session, removes the
  worktree and the task's DinD volume, deletes the local branch, and
  moves the task file to `tasks/completed/`. For `DROPPED`, closes
  the PR, kills the tmux session, removes the worktree and DinD
  volume, preserves the local branch, and moves the file to
  `tasks/dropped/`. Force-drop is allowed from any non-terminal
  state; force-complete is not (COMPLETE requires the agent to have
  verified the merge).

**In-container** (run from inside the task's tmux session):

- **`/advance`** — Advance the task's TODO keyword forward to the
  next workflow stage (`PLANNING → ITERATING → REVIEW → MERGING →
  COMPLETE`, or `ITERATING → MERGING` directly when the task's
  `:SKIP_REVIEW:` property is set — see [Workflow
  states](#workflow-states)). Surfaces the current stage's Definition
  of Done and complains if anything's unmet before performing the
  transition.
- **`/iterate`** — Flip the TODO keyword back to `ITERATING` (with
  `:agent:` tag). Used when review comments come in on a `REVIEW`
  PR, or a `MERGING` task hits a merge break.
- **`/drop`** — Flip the TODO keyword to `DROPPED` (with `:user:`
  tag) from any non-terminal state. Refuses to drop from `COMPLETE`
  (work already landed); reminds you that the host now needs
  `/sweep` (or `/finalize` directly) to do the actual cleanup.
- **`/babysit-ci`** — Monitor CI on the task's PR autonomously after
  a push. Push-driven: kicks off `gh pr checks --watch` as a
  background job; the agent wakes when the watch returns. Green
  flips the heading tag to `:user:` and stops (forward TODO
  transitions are user-driven); failures get diagnosed, fixed,
  pushed, and watched again. **Merge conflicts** against the base
  branch are also part of the job: the agent merges the latest base
  in, resolves trivial conflicts (lockfiles, append-only,
  formatting), and re-pushes — bailing to `:user:` only when a
  conflict genuinely needs human judgment. Zero token cost during
  the watch — Claude is fully idle until CI ends.
- **`/babysit-merge`** — MERGING-stage equivalent of `/babysit-ci`.
  Adds the PR to the repo's merge queue, watches via background job,
  re-queues on transient ejections — "keep re-adding until it
  merges." On a successful merge, **auto-advances the heading to
  `COMPLETE :user:`** (the one forward transition the agent owns,
  since `/sweep` on the host then surfaces it for `/finalize`). On
  any blocking condition (failing required check, requested changes,
  merge conflict, branch protection refusal), **kicks the task back
  to `ITERATING :user:`** with a one-paragraph explanation appended
  to `** Notes` — conflict resolution is `/babysit-ci`'s job during
  ITERATING, not this skill's.

## Internals

For the agent-facing wiring details — the helper scripts the slash
commands shell out to, the in-container hooks that keep the task
heading in sync, the Docker container per task, the active task
properties drawer schema — see [`docs/internals.md`](docs/internals.md).
Humans normally don't need any of that.
