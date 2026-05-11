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

Stage defaults:

- `PLANNING`, `ITERATING` — `:agent:` while the agent is working,
  `:user:` when waiting for feedback, `:blocked:` if waiting on
  something external.
- `REVIEW` — `:blocked:` by default (waiting on peer reviewers). Flip
  to `:user:` if reviewers leave comments that need a triage decision.
- `MERGING` — `:agent:` while the agent manages the merge queue,
  `:user:` if something requires human judgment to resolve.

### Stage details

Each in-flight stage has explicit responsibilities and a definition of
done (DoD). The agent works toward the DoD; the user uses the DoD to
decide when to advance the state.

#### PLANNING

**Responsibilities**
- Collect requirements.
- Produce a plan for the implementation.

**Definition of done**
- The plan is written into the task's org file.
- The user has approved the plan.
- A draft PR has been created on GitHub.

#### ITERATING

**Responsibilities**
- Implement the plan.
- Implement any additional user requests or feedback.
- Implement any review comments the user has approved for
  implementation.

**Definition of done**
- The plan is implemented in code.
- All user requests are implemented in code.
- New and relevant tests pass locally.
- Changes are committed and pushed.
- CI tests are passing, or any failures can be attributed to
  irrelevant flakes.

#### REVIEW

**Responsibilities**
- Wait for review or approval of the PR.

**Definition of done**
- The PR has been reviewed.

#### MERGING

**Responsibilities**
- Add the PR to the merge queue.
- If the PR exits the merge queue, re-add it.

**Definition of done**
- The PR is merged.

#### COMPLETE (terminal)

**Responsibilities**
- Move the task's org file from `tasks/active/` to `tasks/completed/`.

**Definition of done**
- The file is in `tasks/completed/`.

#### DROPPED (terminal)

**Responsibilities**
- Move the task's org file from `tasks/active/` to `tasks/dropped/`.

**Definition of done**
- The file is in `tasks/dropped/`.

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

## Running tasks in Docker

Each active task can be run inside a sandboxed Docker container with
`claude --dangerously-skip-permissions`, so the agent can act without
per-tool permission prompts while staying isolated from the host.

The container:

- Runs Claude Code as an unprivileged `cloude` user whose UID/GID match
  the invoking host user (so files written through bind mounts are
  owned correctly on the host).
- Has Docker-in-Docker (DinD), so `docker compose` works inside.
- Persists Claude credentials/history in a named volume
  (`cloude-claude-creds`), so login is required only once per
  workstation.
- Inherits git, gh, and docker-registry auth read-only from the host's
  `~/.gitconfig`, `~/.config/gh`, and `~/.docker/config.json` (the
  docker config mount is optional — skipped if absent). Mounting
  `~/.docker/config.json` lets the in-container `docker pull` reach
  private registries the host is logged into (e.g. ghcr.io).
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
- `make clean-image` / `make clean-volume` / `make clean` — teardown.
  Note that `clean-volume` erases saved credentials.

## Slash commands

Project-scoped slash commands live in `.claude/commands/`. Available
commands:

- **`/promote`** — Promote an idea from `tasks/staging.org` into an
  active task. Interactive: lists ideas grouped by project, asks which
  to promote, auto-slugs the heading. Then creates the active task
  file under `tasks/active/`, a `cloude/<slug>` branch in the
  project's repo, a worktree under `worktrees/<repo-name>/<slug>`, a
  draft PR, and a detached tmux session named `cloude-<slug>`. Source
  clones are kept in `repos/<repo-name>` (auto-cloned on first use);
  worktrees share that clone's git object store. Both `repos/` and
  `worktrees/` are gitignored.
