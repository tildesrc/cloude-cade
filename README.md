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
staging.org              ;; lightweight captures, not yet started
active/                  ;; one file per in-flight task
  YYYY-MM-DD-<slug>.org
completed/               ;; one file per merged task (COMPLETE)
  YYYY-MM-DD-<slug>.org
dropped/                 ;; one file per abandoned task (DROPPED)
  YYYY-MM-DD-<slug>.org
TEMPLATE.org             ;; scaffold for new active tasks (copy, don't edit)
```

- **Top-level state** is encoded by which directory a task lives in
  (`staging` → `active/` → `completed/` or `dropped/`). The high-level
  overview comes from directory listings, not a global index file.
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
- Move the task's org file from `active/` to `completed/`.

**Definition of done**
- The file is in `completed/`.

#### DROPPED (terminal)

**Responsibilities**
- Move the task's org file from `active/` to `dropped/`.

**Definition of done**
- The file is in `dropped/`.

### Lifecycle

1. Capture the idea in `staging.org` under `* Ideas`.
2. When ready to start, copy the scaffold:
   `cp TEMPLATE.org active/$(date +%F)-<slug>.org`. Move any notes from
   staging into the new file and remove the staging entry. Initial state
   is `PLANNING` with the `:user:` tag — the task is waiting for the
   user to give the planning prompt.
3. Update the TODO keyword as the task moves through stages, and flip
   the `:agent:`/`:user:` tag as the agent moves between working and
   waiting.
4. When the task reaches `COMPLETE`, move the file into `completed/`;
   when it reaches `DROPPED`, move the file into `dropped/`. Filename
   unchanged in either case.
