# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

This repo holds tools for parallelizing and managing
development with Claude Code. See `README.md` for the current description
of the repo and the task workflow. The agent-facing wiring reference —
helper bin/ scripts, in-container hooks, container internals, the active
task properties drawer schema — lives in `docs/internals.md`.

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
  task into the active file when it's promoted. A project may also
  carry an optional `:SKIP_REVIEW: t` property — it travels into the
  active file the same way and tells `/advance` to skip the `REVIEW`
  stage (see Workflow states).
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

Repos that opt out of peer review skip the `REVIEW` stage entirely. A
task whose properties drawer has `:SKIP_REVIEW: t` advances straight
from `ITERATING` to `MERGING` — `/advance` consults the property and
bypasses `REVIEW`. The `REVIEW` keyword still exists; it's simply never
entered for such tasks.

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
- The user has approved the plan. *Auto-ticked* when the user
  triggers a transition out of PLANNING — `/advance`, `/iterate`,
  or plan-mode acceptance. The act of pulling that trigger is
  itself the approval, so the matching DoD checkbox is ticked by
  `bin/cloude-task-set-state` (or `bin/cloude-on-plan-accepted`)
  rather than by the agent.
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

Skipped entirely for tasks with `:SKIP_REVIEW: t` — `/advance` goes
`ITERATING → MERGING` and this stage is never entered.

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

The host-side `/finalize` then moves the file to `tasks/completed/`,
kills the tmux session, removes the worktree, and deletes the local
branch.

#### DROPPED (terminal)

Same read-only-mount caveat as COMPLETE: the file move and cleanup
happen from the host via `/finalize`.

**Responsibilities (in-container agent)**
- Set the TODO keyword to `DROPPED` and flip the tag to `:user:`.
  Then stop.

**Definition of done**
- The task file has TODO state `DROPPED` and tag `:user:`.

The host-side `/finalize` then closes the PR, moves the file to
`tasks/dropped/`, kills the tmux session, and removes the worktree.
The local branch is preserved on DROPPED in case you want to
revisit.

#### Per-stage tag defaults

- `PLANNING`, `ITERATING` — `:agent:` while you're working, `:user:`
  when waiting for feedback, `:blocked:` if waiting on something
  external.
- `REVIEW` — `:blocked:` by default (waiting on peer reviewers). Flip
  to `:user:` if reviewers leave comments that need a triage decision.
- `MERGING` — `:agent:` while you manage the merge queue, `:user:` if
  something requires human judgment to resolve.

### Per-stage log entry

Every stage entry / re-entry appends one *log entry* under the task
file's `** Log` section. The entry is the per-stage audit trail —
*what was asked, what was done, and whether the Definition of Done
was met* — and the stop hook's DoD check is a deterministic parse of
its DoD verdict, not a transcript-level reminder.

Shape:

```
*** [2026-05-20 Wed 11:30] ITERATING (via /advance from PLANNING)
    :PROPERTIES:
    :STAGE:       ITERATING
    :ENTERED:     [2026-05-20 Wed 11:30]
    :ENTERED_VIA: /advance from PLANNING
    :END:
**** Request
     Paraphrase of what the user asked for this stage.
**** Work
     What you did (updated over the stage's lifetime).
**** [N/M] <VERDICT> DoD
     - [ ]/[X]/[-] (one per stage-DoD bullet)
```

The verdict (`PENDING` / `UNSATISFIABLE` / `PASS`) is the org TODO
keyword on the `**** DoD` heading, drawn from the file's secondary
`#+TODO:` sequence (`PENDING(P!) UNSATISFIABLE(U!) | PASS(D!)`). The
`[N/M]` cookie auto-tracks how many checkboxes are ticked (`[X]`) or
N/A (`[-]`).

Lifecycle:

- `/promote` seeds the initial PLANNING (or ITERATING, in ADOPT
  mode) entry with `**** [/] PENDING DoD` plus one `- [ ]` per
  stage-DoD bullet.
- `/advance` and `/iterate` (and `/drop`) flip the level-1 stage and
  also append a fresh entry skeleton via `bin/cloude-task-set-state`,
  stamping `:EXITED:` and `:DURATION:` on the previous entry. On a
  transition out of PLANNING into any non-DROPPED stage, the helper
  additionally auto-ticks the "user has approved the plan" DoD bullet
  on the closing PLANNING entry — invoking the command is itself the
  approval, so the agent doesn't tick that one by hand. Plan-mode
  acceptance (`bin/cloude-on-plan-accepted`) does the same.
- The agent fills `**** Request` / `**** Work` as the stage
  progresses, ticks (`[X]`) or marks N/A (`[-]`) each DoD checkbox
  as it's resolved, and flips the verdict via:

  ```
  cloude-task-set-state $CLOUDE_TASK_FILE --dod-state {pass|unsatisfiable}
  ```

  with an optional `--reason "..."` (replaces the body prose).

Consistency rule (enforced by the flip command *and* the stop hook):

- `PASS` requires every checkbox ticked (`[X]`) or N/A (`[-]`) —
  no `[ ]`.
- `UNSATISFIABLE` requires at least one open `[ ]` box (documenting
  what *can't* be met).
- `PENDING` has no checkbox constraint.

The stop hook (`bin/cloude-on-stop`) consumes the per-transition DoD
marker and blocks once if the latest log entry's verdict is `PENDING`
(or the verdict/cookie are inconsistent, or the `** Log` section is
missing, or the latest entry's `:STAGE:` doesn't match the level-1
TODO keyword). It does **not** fire on ordinary turns or once the
verdict is `PASS` / `UNSATISFIABLE` — so the agent's organic
end-of-turn message stays as the visible last content on every
happy path.

The per-stage DoD bullets live in `bin/cloude_stages.WORKFLOW`
(consumed by the skeleton generator and the hook via
`bin/cloude_org.STAGE_DOD`'s read-only re-export, and by the
`/advance` skill via `bin/cloude-stages dod <STAGE>`). The *Stage
details* section above is the human-facing reference; agents
evaluate against the CLI, not against this prose, so prose drift
is a documentation lag rather than a correctness bug — but please
keep them aligned anyway.

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

The `:agent:` / `:user:` flips happen automatically: the in-container
hooks (`bin/cloude-on-user-prompt` and `bin/cloude-on-stop`) set
`:agent:` when a turn starts and `:user:` when a PLANNING / ITERATING
turn ends. The end-of-turn flip is suppressed while the agent is still
waiting on background work it kicked off (any Bash launched with
`run_in_background: true` whose completion `task-notification` hasn't
arrived yet, or an active `/babysit-ci` / `/babysit-merge` loop), so
the tag stays `:agent:` until the background work settles. You only
need to set `:blocked:` deliberately — and you *can* set it during a
turn to keep the ball off the user at end of turn (e.g., when you've
spawned external CI you want to wait on).

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
