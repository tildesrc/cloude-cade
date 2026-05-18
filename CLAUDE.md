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
`COMPLETE`, `DROPPED`.

**On every new session, read your task file first.** When running
inside a container, the absolute path is in the `CLOUDE_TASK_FILE`
env var. The TODO keyword on the heading is your current stage; the
per-stage responsibilities and DoD below tell you what to do and how
to know you're finished.

**Forward transitions out of `PLANNING`, `ITERATING`, and `REVIEW` are
user-driven only.** Do not advance these states on your own — finish
your work to the stage's DoD, set the heading's tag to `:user:`, and
wait for the user to move the task forward (or send you back with
feedback). Transitioning to `DROPPED` is allowed from any state but
should also generally be a user decision unless you have explicit
authorization.

`MERGING` is agent-driven: actively manage the merge — re-add to the
queue on flaky failures, resolve trivial conflicts — and flip the
TODO keyword to `COMPLETE` once the merge has landed. For `COMPLETE`
and `DROPPED`, the in-container agent sets the TODO keyword and tag,
then stops; the file move and worktree/tmux/branch cleanup happen
from the host via the `/finalize` slash command (the cloude repo is
mounted read-only inside the container, so the agent can't perform
the move itself).

To actually flip the TODO keyword and tag, prefer the in-container
slash commands over editing the heading by hand:

- `/advance` — forward to the next stage. Surfaces the current
  stage's DoD checklist and complains if anything's unmet before
  performing the transition.
- `/iterate` — back into `ITERATING` (used when review comments come
  in or a merge breaks).
- `/drop` — to `DROPPED` from any non-terminal state. Reminds you
  that the host then needs `/sweep` / `/finalize` to clean up.

The "forward transitions out of PLANNING/ITERATING/REVIEW are
user-driven only" rule above is still your responsibility; `/advance`
is mechanical and won't enforce it.

### Stage details

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
- Update the PR title and description on GitHub so they describe the
  change as implemented, replacing the placeholder text the draft PR
  was opened with. The description should describe the change only —
  do **not** include a "Test Plan", "Verification", or equivalent
  test-steps section. Verification notes stay local: keep them in the
  task's org file (`** Notes` / acceptance criteria), not on the PR.

**Definition of done**
- The plan is implemented in code.
- All user requests are implemented in code.
- New and relevant tests pass locally.
- Changes are committed and pushed.
- CI tests are passing, or any failures can be attributed to
  irrelevant flakes.
- The PR title and description on GitHub reflect the final change
  (not the draft-PR placeholder), and the description carries no Test
  Plan / Verification section.

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

The container mounts the cloude repo read-only, so the file move
itself is done from the host via `/finalize` — not by the
in-container agent.

**Responsibilities (in-container agent)**
- Once the PR is merged, set the TODO keyword to `COMPLETE` and flip
  the tag to `:user:`. Then stop — `/finalize` on the host will move
  the file and clean up.

**Definition of done**
- The task file has TODO state `COMPLETE` and tag `:user:`.
- (The host-side `/finalize` then moves the file to
  `tasks/completed/`, kills the tmux session, removes the worktree,
  and deletes the local branch.)

#### DROPPED (terminal)

Same read-only-mount caveat as COMPLETE: the file move and cleanup
happen from the host via `/finalize`.

**Responsibilities (in-container agent)**
- Set the TODO keyword to `DROPPED` and flip the tag to `:user:`.
  Then stop.

**Definition of done**
- The task file has TODO state `DROPPED` and tag `:user:`.
- (The host-side `/finalize` then closes the PR, moves the file to
  `tasks/dropped/`, kills the tmux session, and removes the worktree.
  The local branch is preserved on DROPPED in case you want to
  revisit.)

#### Per-stage tag defaults

- `PLANNING`, `ITERATING` — `:agent:` while you're working, `:user:`
  when waiting for feedback, `:blocked:` if waiting on something
  external.
- `REVIEW` — `:blocked:` by default (waiting on peer reviewers). Flip
  to `:user:` if reviewers leave comments that need a triage decision.
- `MERGING` — `:agent:` while you manage the merge queue, `:user:` if
  something requires human judgment to resolve.

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
- Your specific task file path is exported as `$CLOUDE_TASK_FILE`.
  Read it at the start of every session to determine your current
  stage (the TODO keyword on the heading) before deciding what to do.
- The container has Docker-in-Docker, so `docker compose` works for
  spinning up the project's dev environment. The agent runs as an
  unprivileged user; only `dockerd` is privileged.
- **`$CLOUDE_TASK_FILE` is writable. Edit it directly.** Yes, the
  cloude repo as a whole is mounted read-only — *but `bin/cloude-run`
  layers a writable bind mount on top of `tasks/active/` (the whole
  directory)*, so any file under `tasks/active/` is writable from
  inside. Use it: write your `** Plan` content into the task file
  during PLANNING; flip the heading's TODO keyword and tag via
  `/advance`, `/iterate`, `/drop`; append session notes into
  `** Notes`. **Do not** assume "cloude is ro" and write your plan
  into a commit message as a workaround — write the plan into the
  task file's `** Plan` section, which is exactly what PLANNING's
  DoD ("the plan is written into the task's org file") requires.
- **Soft rule: only edit your own task file.** The rw mount covers
  the whole `tasks/active/` directory (because Docker single-file
  bind mounts break when the host writes via atomic-rename — a
  directory-level mount is the inode-stable alternative). You can
  technically read and write the other in-flight tasks' files, but
  **don't**. Concurrent agents rely on each one updating only its
  own file to avoid conflicts. `$CLOUDE_TASK_FILE` is yours; treat
  the rest of `tasks/active/` as read-only by convention.
- The worktree is the cwd and writable. The rest of the cloude repo
  (staging.org, completed/, dropped/, README, scripts) is
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
