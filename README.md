# cloude

Personal tools for parallelizing and managing development with Claude Code.

## What this is for

This repo is a workspace for scripts, configs, and utilities that support
agent-driven development end-to-end — from picking up a task to landing it.

Beyond the mechanical overhead of running Claude Code (worktrees, branches,
PR triage, scheduled jobs, etc.), the larger goal is to manage the
*workflow* of development tasks from beginning to end. Agents change the
shape of that workflow: they enable — and require — far more multitasking
than solo development, with several pieces of work in flight at once and
agents running unattended in the background.

That makes it essential to have a well-defined workflow that distinguishes:

- **Foreground work** — tasks that need active developer attention
  (decisions, reviews, ambiguous requirements, risky changes).
- **Background work** — tasks an agent can run to completion alone, with
  the developer only checking results when they land.

The tools in this repo exist to make that distinction explicit and to keep
the right things flowing through the right lane.

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

### Workflow states

| State        | Meaning                                                                      | Can move to                  |
| ------------ | ---------------------------------------------------------------------------- | ---------------------------- |
| `PLANNING`   | Claude is planning the work.                                                  | `ITERATING`, `DROPPED`       |
| `ITERATING`  | Claude is writing code, running tests, updating the PR, waiting on CI.        | `REVIEW`, `DROPPED`          |
| `REVIEW`     | PR is open for peer review, waiting on comments.                              | `ITERATING`, `MERGING`, `DROPPED` |
| `MERGING`    | PR is approved and ready to merge.                                            | `COMPLETE`, `DROPPED`        |
| `COMPLETE`   | PR is merged. Terminal.                                                       | —                            |
| `DROPPED`    | Task abandoned. Terminal.                                                     | —                            |

Forward transitions out of `PLANNING`, `ITERATING`, and `REVIEW` are
**user-driven only** — the agent does not advance these states on its
own; it must wait for the user to make the call. Any state can transition
to `DROPPED` at any time.

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

### Stage details and tag defaults

Per-stage responsibilities, definition of done, and `:agent:` /
`:user:` / `:blocked:` defaults are the agent's canonical spec — they
live in `CLAUDE.md` so they get loaded automatically into every Claude
session.

### staging.org structure

Top-level headings in `tasks/staging.org` are **projects**. Each project
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

### Active task properties

Each active task file's top-level heading carries a properties drawer
with the metadata needed to act on the task without hunting:

| Property    | Meaning                                                        |
| ----------- | -------------------------------------------------------------- |
| `:ID:`      | Stable task identifier, matches the filename (`YYYY-MM-DD-<slug>`). |
| `:REPO:`    | GitHub repo the task lives in. Carried from the staging project. |
| `:BRANCH:`  | Feature branch name in the repo.                                |
| `:WORKTREE:`| Local git worktree path where the agent works.                  |
| `:PR:`      | Pull request URL once the draft PR exists.                      |
| `:AGENT:`   | Link to the agent session driving the task.                     |

`:ID:` and `:REPO:` are set when the task is promoted from staging.
The rest are filled in as the task progresses (branch + worktree at
the start of `PLANNING`, `:PR:` at the end of `PLANNING`, `:AGENT:`
whenever an agent is attached).

### Lifecycle

1. Capture the idea in `tasks/staging.org` as a sub-heading under the right
   project (create the project heading if it doesn't exist yet).
2. When ready to start, run `/promote` (see "Slash commands" below).
   The skill walks through staging interactively, then sets up the
   active task file, a feature branch, a worktree under `worktrees/`, a draft
   PR, and a detached tmux session. Initial state is `PLANNING` with
   the `:user:` tag — the task is waiting for the user's planning
   prompt.
3. Update the TODO keyword as the task moves through stages, and flip
   the `:agent:`/`:user:` tag as the agent moves between working and
   waiting.
4. When the task reaches `COMPLETE`, move the file into
   `tasks/completed/`; when it reaches `DROPPED`, move the file into
   `tasks/dropped/`. Filename unchanged in either case.

## Dashboard

`bin/cloude-dash` is a curses TUI that surfaces the state of every task
in one screen. It parses each `tasks/**/*.org` file with `orgparse` and
renders three sections:

- **ACTIVE** — one row per file in `tasks/active/`, sorted by stage
  priority (`MERGING` first, then `REVIEW`, `ITERATING`, `PLANNING`).
  Each row shows the TODO keyword, who currently has the ball
  (`:agent:` green, `:user:` yellow, `:blocked:` red), the heading, and
  the PR number from the `:PR:` property.
- **STAGING** — every idea sub-heading from `tasks/staging.org`.
- **RECENT** — the 20 most-recently-touched files from
  `tasks/completed/` and `tasks/dropped/`.

Keys: `↑`/`↓` or `j`/`k` move, `g`/`G` jump to top/bottom, `Enter`
opens the highlighted task's PR in the default browser, `r` reloads,
`q` quits.

```sh
bin/cloude-dash
```

The script has a PEP 723 inline-dependency header, so the recommended
launcher is `uv` — it handles the `orgparse` install transparently.
If `uv` isn't available, `pip install --user orgparse` then run the
script with `python3`.

## Running tasks in Docker

Each active task can be run inside a sandboxed Docker container with
`claude --dangerously-skip-permissions`, so the agent can act without
per-tool permission prompts while staying isolated from the host.

The container:

- Runs Claude Code as an unprivileged `cloude` user whose UID/GID match
  the invoking host user (so files written through bind mounts are
  owned correctly on the host).
- Has Docker-in-Docker (DinD), so `docker compose` works inside. Each
  task gets its own `cloude-dind-<slug>` volume backing
  `/var/lib/docker` — necessary because nested `overlay2` on the
  container's own overlay layer hits whiteout permission errors, and
  because multiple in-flight tasks can't share one docker data dir
  (dockerd holds an exclusive lock). The volume persists across
  restarts of the same task to cache pulled images.
- Persists Claude credentials/history in a named volume
  (`cloude-claude-creds`), so login is required only once per
  workstation.
- Inherits git, gh, and docker-registry auth read-only from the host's
  `~/.gitconfig`, `~/.config/gh`, and `~/.docker/config.json` (the
  docker config mount is optional — skipped if absent). Mounting
  `~/.docker/config.json` lets the in-container `docker pull` reach
  private registries the host is logged into (e.g. ghcr.io).
- The host's `GH_TOKEN` env var is forwarded into the container (when
  set) so `gh` and the git credential helper baked into
  `/etc/gitconfig` can authenticate against GitHub for HTTPS `git
  fetch`/`push`. SSH-form remotes are not supported inside the
  container (no SSH keys mounted); `/promote` clones via HTTPS to
  avoid this.
- Mounts the cloude repo at the same absolute path it has on the host
  (read-only) plus rw overlays for the task's source clone, worktree,
  and active `.org` file. Other tasks remain read-only.

### One-time setup

```sh
make build       # build the image (takes a few minutes the first time)
make login       # run claude interactively to perform the first-time login
```

After `make login` exits, credentials live in the `cloude-claude-creds`
volume and persist across runs.

### Launching a task

`/promote` automatically starts the container in the task's tmux
session. To launch (or relaunch) by hand:

```sh
bin/cloude-run <worktree-abs-path> <task-file-abs-path>
```

Both arguments are absolute paths the caller already has — `cloude-run`
doesn't look up tasks by slug or parse org files.

### Per-repo pre-launch hooks

Some projects ship config that doesn't behave inside the container —
plugin entries pointing at host binaries, project skills that depend
on external services, etc. To shape the worktree before the container
starts, drop an executable script at:

```
repo-hooks/<repo-name>          (e.g. repo-hooks/acme-webapp)
```

`cloude-run` invokes the hook (if present and executable) with cwd =
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

### Make targets

- `make build` / `make rebuild` — build (cached) / rebuild (no cache).
- `make shell` — bash shell in a transient container, for debugging the
  image without a real task.
- `make login` — interactive `claude` in a clean container; first-time
  login flow.
- `make info` — image and volume status.
- `make clean-image` / `make clean-volume` / `make clean-dind-data` /
  `make clean` — teardown. `clean-volume` erases saved credentials;
  `clean-dind-data` removes every per-task `cloude-dind-*` volume
  (image caches inside containers).

## Slash commands

Project-scoped slash commands live in `.claude/commands/`. Available
commands:

- **`/promote`** — Promote an idea from `tasks/staging.org` into an
  active task. Interactive: lists ideas grouped by project, asks which
  to promote, auto-slugs the heading. Two modes:
  - **Standard**: creates the active task file under `tasks/active/`,
    a `cloude/<slug>` branch in the project's repo off the default
    branch, a worktree under `worktrees/<repo-name>/<slug>`, a draft
    PR, and a detached tmux session named `cloude-<slug>`. Starts in
    `PLANNING :user:`.
  - **ADOPT**: triggered when the staging idea is `ADOPT <PR url>`.
    No new branch or PR — checks out the existing PR's branch as a
    worktree, uses the PR's title for the task heading, and starts in
    `ITERATING :user:` so the user can direct the agent on what to do
    with the adopted work. Refuses to adopt closed/merged or
    cross-repository (forked) PRs.

  Source clones are kept in `repos/<repo-name>` (auto-cloned on first
  use); worktrees share that clone's git object store. Both `repos/`
  and `worktrees/` are gitignored.
- **`/advance`** *(in-container)* — Advance the task's TODO keyword
  forward to the next workflow stage (`PLANNING → ITERATING →
  REVIEW → MERGING → COMPLETE`). Loads the current stage's
  Definition of Done from `CLAUDE.md`, evaluates each item
  (programmatically where it can — PR exists, CI status, git
  clean — and via the agent's judgment for the rest), and
  complains (lists unmet items + asks for explicit confirm)
  before the transition lands. Only edits `$CLOUDE_TASK_FILE`;
  the host sees the diff afterward.
- **`/iterate`** *(in-container)* — Flip the TODO keyword back to
  `ITERATING` (with `:agent:` tag). Used when review comments come
  in on a `REVIEW` PR, or a `MERGING` task hits a merge break. No
  preconditions; mechanical.
- **`/drop`** *(in-container)* — Flip the TODO keyword to
  `DROPPED` (with `:user:` tag) from any non-terminal state.
  Refuses to drop from `COMPLETE` (work already landed); no-op
  from `DROPPED`. Reminds the agent that the host now needs
  `/sweep` (or `/finalize` directly) to do the actual cleanup.
- **`/babysit-ci`** *(in-container)* — Monitor CI on the task's PR
  autonomously after a push. Push-driven: kicks off `gh pr checks
  --watch` as a background bash; the harness fires a new turn when
  the watch returns. On that turn, the agent reads the result —
  green stops the loop, failures get diagnosed, fixed (commit +
  push), and watched again. Budgets: 2h wall-clock, 3 post-fix
  retries per failing check. On bail, flips the heading tag to
  `:user:` so the user knows attention is needed. Zero token cost
  during the watch — Claude is fully idle until CI ends.
- **`/sweep`** — Scan `tasks/active/` for tasks whose TODO keyword is
  already `COMPLETE` or `DROPPED` (the in-container agent has flipped
  the state but the file is still in `active/`). For each candidate,
  prompts you per-task with `Approve /finalize for <task>? [y/N/skip]`
  and only invokes `/finalize` on an explicit `y`. Quick to run (one
  line of output when nothing's pending), so safe to drive on a `/loop`
  poll (e.g. `/loop 1m /sweep`) in your main host session.
- **`/finalize`** — Finalize an active task and perform the cleanup
  the in-container agent can't do (the cloude repo is mounted ro from
  inside the container). Interactive: lists active tasks with their
  current TODO state, asks which to finalize. For `COMPLETE`,
  verifies the PR is merged, kills the tmux session, removes the
  worktree, removes the task's `cloude-dind-<slug>` DinD volume,
  deletes the local branch, and `git mv`s the task file to
  `tasks/completed/`. For `DROPPED`, closes the PR, kills the tmux
  session, removes the worktree, removes the DinD volume, preserves
  the local branch, and `git mv`s the file to `tasks/dropped/`.
  Force-drop is allowed from any non-terminal state; force-complete
  is not (COMPLETE requires the agent to have verified the merge).
