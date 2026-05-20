# cloude internals

This document is the agent-facing wiring reference for cloude: the
helper scripts the slash commands shell out to, the in-container hooks
that keep the task heading in sync with what the agent is doing, the
Docker container that runs each task, and the schema of the active
task properties drawer.

Human users normally don't need any of this — `README.md` covers the
concepts and commands a user invokes. This file exists so that when an
agent needs to understand the plumbing (debugging a hook, modifying a
helper, extending a skill), the details live in one place.

## Active task properties drawer

Each active task file's top-level heading carries a properties drawer
with the metadata needed to act on the task without hunting. Most
fields are filled in by `/promote` and the agent as the task
progresses; humans rarely hand-edit them.

| Property         | Meaning                                                        |
| ---------------- | -------------------------------------------------------------- |
| `:ID:`           | Stable task identifier, matches the filename (`YYYY-MM-DD-<slug>`). |
| `:REPO:`         | GitHub repo the task lives in. Carried from the staging project. |
| `:BRANCH:`       | Feature branch name in the repo.                                |
| `:WORKTREE:`     | Local git worktree path where the agent works.                  |
| `:PR:`           | Pull request URL once the draft PR exists.                      |
| `:AGENT:`        | Link to the agent session driving the task.                     |
| `:ADOPTED:`      | *(optional)* `t` if the task was promoted in ADOPT mode (existing PR adopted, not freshly created). |
| `:SKIP_REVIEW:`  | *(optional)* `t` if the repo opts out of peer review. Carried from the staging project; makes `/advance` skip the `REVIEW` stage (`ITERATING → MERGING`). |
| `:COMPANION_PR:` | *(optional)* URL of a related PR this task pairs with — e.g., an acme-webapp companion to an acme-service PR. Used when work spans two PRs that should land together. |

`:ID:` and `:REPO:` are set when the task is promoted from staging.
The rest are filled in as the task progresses (branch + worktree at
the start of `PLANNING`, `:PR:` at the end of `PLANNING`, `:AGENT:`
whenever an agent is attached). `:ADOPTED:`, `:SKIP_REVIEW:`, and
`:COMPANION_PR:` are set by `/promote` when the situation applies
(`:SKIP_REVIEW:` whenever the staging project carries it); they're
omitted on ordinary tasks.

## Helper scripts in `bin/`

`/promote`, `/sweep`, `/finalize`, and the in-container state-flip
commands (`/advance`, `/iterate`, `/drop`, `/babysit-ci`,
`/babysit-merge`) are thin wrappers around a small set of `bin/`
orchestrators — the skills shell out to these instead of parsing or
rewriting `.org` files themselves, so the structural reading and
writing of org files lives in one place. Each script is callable by
hand too (e.g. for scripting outside the skills, or when debugging).
Scripts that *read* `.org` files parse them with `orgparse` via a
PEP 723 inline-deps header (same pattern as `bin/cloude-dash`) and
are intended to be run via `uv`. The one script that only *edits* a
heading (`cloude-task-set-state`) uses a single regex, needs no
dependency, and runs on plain `python3`.

- **`cloude-list-staging`** — Print promotable ideas from
  `tasks/staging.org` numbered globally, plus a trailing
  `TODO_PROJECTS <n>` count of personal-TODO projects (no `:REPO:`)
  that `/promote` skips. With `--select N`, instead emits the chosen
  idea's full record (`REPO`, `HEADING`, `MODE`, `PR_URL`,
  `SKIP_REVIEW`) as shell-safe `KEY=VALUE` lines, so `/promote` can
  `eval` it rather than re-parsing staging.org. (`SKIP_REVIEW` carries
  the project heading's optional `:SKIP_REVIEW:` property.) Used by
  `/promote` step 1.
- **`cloude-list-active`** — Print active tasks under
  `tasks/active/`, numbered, sorted by stage priority (matching the
  dashboard's `MERGING → REVIEW → ITERATING → PLANNING` order). With
  `--terminal`, filters to `COMPLETE`/`DROPPED`; if the filtered set
  is empty, prints exactly `No tasks awaiting finalize.` and exits 0
  — this is `/sweep`'s idle-tick output and what makes a `/loop
  /sweep` cheap. Used by `/sweep` and `/finalize` step 1.
- **`cloude-task-info <task-file>`** — Emit `KEY=VALUE` (shell-safe)
  lines for the heading TODO/tag/text, the properties drawer
  (`WORKTREE`, `BRANCH`, `PR`, `REPO`, `ID`, plus `ADOPTED` /
  `SKIP_REVIEW` / `COMPANION_PR` when present), and derived fields (`SLUG`,
  `REPO_NAME`, `SOURCE_CLONE`, `TMUX_SESSION`, `DIND_VOLUME`,
  `CLOUDE_ROOT`). Sourced by `cloude-finalize-cleanup` and by the
  `/advance`, `/iterate`, `/drop`, `/babysit-ci`, `/babysit-merge`
  skills at their read-the-task-file step. Exit 3 names the missing
  key when a required property is absent.
- **`cloude-task-set-state <task-file> [--todo NAME] [--tag NAME]`** —
  Rewrite the first heading of a task file in place: `--todo` swaps
  the TODO keyword, `--tag` replaces the entire trailing tag chain
  with one tag; an omitted flag leaves that part untouched. The
  heading text and everything below are preserved. This is the one
  place the task-heading edit is spelled out — the `/advance`,
  `/iterate`, `/drop`, `/babysit-ci`, `/babysit-merge` skills and
  `cloude-finalize-cleanup`'s force-drop all call it instead of
  re-deriving the rewrite. Prints the resulting `TODO` / `TAG`.
  Regex-based, no dependency, runs on plain `python3`.
- **`cloude-promote-setup`** — Bash orchestrator for `/promote`
  steps 4-9: ensure source clone, create worktree + branch, push
  (standard) or fetch (ADOPT), open draft PR (standard only),
  render task file from `tasks/TEMPLATE.org`, remove staging entry,
  start tmux session, and — in standard mode — queue the staging
  entry to pre-fill the container's input box via
  `cloude-prefill-prompt`. Distinct non-zero exit codes per failure
  mode (10 clone, 11 worktree, 12 PR, 13 render, 14 staging removal,
  20 tmux collision, 30 arg validation) and a "Succeeded so far"
  trail on stderr.
- **`cloude-prefill-prompt <tmux-session> <prompt-file>`** —
  Best-effort background poller that pre-fills a freshly promoted
  task's Claude Code input box. Launched detached by
  `cloude-promote-setup` (standard mode only): it watches the task's
  tmux pane until Claude Code's interactive input box is ready, then
  *pastes* the prompt in — a bracketed paste, so a multi-line staging
  entry lands as unsent input rather than submitting on the first
  newline. Readiness is detected from the bracketed-paste-enable
  escape (`ESC[?2004h`) in the pane's raw output stream, captured via
  `tmux pipe-pane` — this keys on the exact terminal capability the
  paste relies on and is independent of any on-screen wording. On
  timeout, a vanished session, or any tmux error it just leaves the
  box empty; it never blocks or fails the promote. Env knobs:
  `CLOUDE_NO_PREFILL` (set non-empty to opt out) and
  `CLOUDE_PREFILL_TIMEOUT` (seconds to wait, default 300). Logs to
  `/tmp/cloude-prefill-<slug>.log`.
- **`cloude-finalize-cleanup <task-file>`** — Bash orchestrator for
  `/finalize` steps 4-10: verify/close PR, kill tmux, remove
  worktree, remove DinD volume, delete branch (COMPLETE only), move
  task file. Bails with distinct exit codes for the judgment-call
  cases:
  - `10` — PR not in state `MERGED` (the agent set `COMPLETE`
    prematurely).
  - `11` — task TODO is not `COMPLETE`/`DROPPED`. Pass
    `--force-drop` to flip to `DROPPED` and proceed.
  - `12` — worktree dirty/locked. Pass `--force-worktree` to retry
    with `git worktree remove --force`.
  - `13` — DinD volume still in use. Pass `--skip-volume` to leave
    it in place.
  - `14` — worktree contains files owned by another user (typically
    root, from in-container DinD test runs that bind-mount the
    worktree); the host user can't unlink them. Pass `--force-root`
    to nuke the dir via `docker run --rm --user root … rm -rf`
    (implies `--force-worktree`). The script reports the
    foreign-owned file count so the user can gauge the scope before
    authorizing.

  The skill is responsible for prompting the user and rerunning with
  the matching override; the script itself has no interactive
  fallback logic.

## In-container hooks

`docker/cloude-settings.json` registers Claude Code hooks that fire
inside the container, keeping the task heading's TODO keyword and
who-has-the-ball tag in sync with what the agent is actually doing:

- **`PostToolUse:ExitPlanMode` → `bin/cloude-on-plan-accepted`.** When
  the user accepts a plan in plan mode and the task is in `PLANNING`,
  writes the accepted plan into the task file's `** Plan` section,
  flips the heading to `ITERATING :agent:`, and arms the DoD marker
  (see the Stop hook below) so the next `Stop` fires its reminder
  once. Lets the agent start implementing on its next turn without a
  separate `/advance` step.
- **`UserPromptSubmit` → `bin/cloude-on-user-prompt`.** Fires at the
  start of every agent turn. If the task is in an in-flight stage
  (PLANNING / ITERATING / REVIEW / MERGING) with tag `:user:`, flips
  it to `:agent:` — the user has just handed the ball back, so the
  agent is now the one working. Matters most for `PLANNING`, which is
  *born* `:user:` and has no other transition into it: without this
  hook a long planning turn would show a stale `:user:` on the
  dashboard the whole time. `:blocked:` is left untouched (set
  deliberately, not cleared by a stray prompt) and the hook never
  blocks a prompt.
- **`Stop` → `bin/cloude-on-stop`.** Fires at the end of every agent
  turn and does two distinct jobs. *Tag maintenance:* if the task is
  in PLANNING or ITERATING with tag `:agent:`, flips it to `:user:`
  deterministically — the end-of-turn counterpart to
  `cloude-on-user-prompt`'s `:user:` -> `:agent:` flip. `:blocked:` is
  never touched (a deliberate state); REVIEW and MERGING are skipped
  too (REVIEW defaults to `:blocked:` and MERGING is agent-driven —
  `/babysit-merge` owns its tag). *DoD reminder:* blocks the stop
  once and injects the current stage's Definition of Done — **but
  only** on turns that began with a stage transition or an `/iterate`,
  not on ordinary conversational turns. Those transition turns drop a
  per-task marker file (in `/tmp`); `cloude-task-set-state` arms it on
  every `--todo` change into an in-flight stage, and this hook
  consumes it. `stop_hook_active` bounds the block to once per stop
  cycle. *Background-work carve-out:* the hook is a full no-op (no tag
  flip, no DoD reminder, the marker stays armed for next turn)
  whenever the agent is still waiting on background work it kicked
  off. Two signals each suffice: a `/babysit-ci` or `/babysit-merge`
  state file in the worktree (`.cloude-babysit-*-state.json`), and an
  in-flight background Bash detected by scanning the transcript JSONL
  for a `run_in_background: true` start without a matching completion
  `task-notification`. The transcript scan generalizes the babysit
  carve-out to every background Bash the agent launches, so the
  dashboard accurately shows `:agent:` while the agent is genuinely
  waiting on its own work.
- **`PreToolUse:AskUserQuestion` / `PostToolUse:AskUserQuestion` →
  `bin/cloude-on-user-question pre` / `… post`.** Manages the tag
  around an `AskUserQuestion` wait window — neither `Stop` nor
  `UserPromptSubmit` runs during one (the turn is still alive inside
  the tool call, and the answer comes back as a tool result rather
  than a fresh prompt), so without this hook the tag stays `:agent:`
  while the user is being asked something. `pre` flips `:agent:` →
  `:user:` just before the question is shown; `post` flips `:user:` →
  `:agent:` once the answer arrives. Only acts on in-flight stages
  and leaves `:blocked:` alone. Unlike `cloude-on-stop`, this hook
  has no background-work carve-out: an `AskUserQuestion` round trip
  is genuinely transient (the user really does have the ball while
  the question is open), and `post` restores `:agent:` afterward, so
  the carve-out's tag invariant is preserved automatically. Never
  blocks the tool call — exits 0 on every path, including a tag-flip
  helper failure.

`cloude-on-user-prompt`, `cloude-on-stop`, `cloude-on-plan-accepted`,
`cloude-on-user-question`, and `cloude-task-set-state` all share
parsing and the DoD-marker path helper through `bin/cloude_org.py`.
Unlike the org-reading helper scripts, those scripts deliberately
*don't* use `orgparse`: Claude Code's hook runner executes them on
plain stdlib `python3`, not through `uv`, so a third-party import
would fail — and a one-line heading grammar is well within reach of a
regex anyway.

The settings file is baked into the image (Dockerfile `COPY
docker/cloude-settings.json /etc/cloude/settings.json`) and surfaced
to the in-container `claude` via `--settings
/etc/cloude/settings.json` (added by `bin/cloude-run`). The hook
scripts themselves live in `bin/` and are read via the read-only
bind mount of the cloude repo, so editing them needs no image
rebuild — only changes to `cloude-settings.json` do.

## Docker container wiring

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
- `tasks/active/` is mounted as a directory-level rw bind, not a
  per-file mount: single-file bind mounts break when the host writes
  via atomic-rename (the inode changes; the container keeps reading
  the old inode). Mounting the directory keeps the bind stable
  through atomic-rename writes from the host. The cost is that every
  task file under `tasks/active/` is technically writable from any
  in-container agent — agents must by convention only edit their
  own `$CLOUDE_TASK_FILE`.

### `bin/cloude-run`

`/promote` launches the container automatically in the task's tmux
session. To launch (or relaunch) by hand:

```sh
bin/cloude-run <worktree-abs-path> <task-file-abs-path>
```

Both arguments are absolute paths the caller already has — `cloude-run`
doesn't look up tasks by slug or parse org files.

The `cloude-<slug>` tmux session `/promote` creates carries
`CLOUDE_TASK_FILE` in its session environment — the absolute path of
the task's active `.org` file. It's inherited by every pane, so the
host shell left behind once `cloude-run` exits still knows which task
the session belongs to (matching the `CLOUDE_TASK_FILE` `cloude-run`
exports inside the container).

### Make targets

`make help` lists every target with a one-liner. The full set:

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
