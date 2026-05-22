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
| `:COMPANION:`    | *(optional)* ID of a sibling cloude task this task is paired with (slug-dated form, e.g. `2026-05-20-acme-webapp-side`) — used when work spans two cloude tasks (typically in different repos) that should land together. Resolves to a file by scanning `tasks/{active,completed,dropped}/<id>.org`. |

`:ID:` and `:REPO:` are set when the task is promoted from staging.
The rest are filled in as the task progresses (branch + worktree at
the start of `PLANNING`, `:PR:` at the end of `PLANNING`, `:AGENT:`
whenever an agent is attached). `:ADOPTED:`, `:SKIP_REVIEW:`, and
`:COMPANION:` are set by `/promote` when the situation applies
(see *Staging-idea trigger properties* below for what each one keys
off of); they're omitted on ordinary tasks.

## Staging-idea trigger properties

`/promote` reads three optional properties from each staging idea
sub-heading's properties drawer (in addition to the project-level
`:REPO:` and `:SKIP_REVIEW:`):

| Property            | Meaning                                                            |
| ------------------- | ------------------------------------------------------------------ |
| `:ADOPT:`           | *(optional)* URL of an existing open PR in the project's repo. Triggers ADOPT mode (`/promote` checks out the PR's branch as a worktree rather than opening a new draft PR). Without this property, the idea promotes as a standard task. Renders `:ADOPTED: t` into the new active task's properties drawer. |
| `:COMPANION:`       | *(optional)* Sibling cloude task ID (slug-dated form, e.g. `2026-05-20-acme-webapp-side`). Copied verbatim into the new active task file's `:COMPANION:` property. |
| `:SLUG:`            | *(optional)* Filesystem slug for `/promote` to use when promoting this idea, in place of its mechanical kebab derivation from the heading. Normally written by the staging-slug watcher (`bin/cloude-watch-staging-slugs` → `/suggest-slugs` → `bin/cloude-set-staging-slug`); see the "Helper scripts" section below. An empty `:SLUG:` (no value) is the explicit "please suggest one" sentinel — `cloude-list-staging --slugless` treats it as missing, and `bin/cloude-set-staging-slug` replaces it. A non-empty user-set value is preserved (clobber-rejected). |

All three are detected by `bin/cloude-list-staging` (which emits
`MODE` / `PR_URL` / `COMPANION` / `SLUG` lines for the chosen idea).
`:ADOPT:` and `:COMPANION:` are forwarded by `/promote` to
`bin/cloude-promote-setup` via the matching `--mode` / `--pr-url` /
`--companion` flags; `:SLUG:` is consumed in step 3 of the
slash-command flow as the proposed slug (still subject to user
confirmation). The staging idea's heading text and body are
free-form — mode, pairing, and the slug are determined entirely by
property presence, never by heading-text pattern matching.

## Per-stage log entry: schema and hook check

Each task file has a `** Log` top-level section that is the per-stage
audit trail. Every stage transition / `/iterate` appends one entry
under it, and the stop hook reads the latest entry's DoD verdict to
decide whether to block.

### Two `#+TODO:` sequences

Each task file declares two file-level TODO sequences (the second is
added by `tasks/TEMPLATE.org` for new tasks; existing in-flight files
need it added by hand as part of migration):

```
#+TODO: PLANNING(p!) ITERATING(i!) REVIEW(r!) MERGING(m!) | COMPLETE(c!) DROPPED(x@)
#+TODO: PENDING(P!) UNSATISFIABLE(U!) | PASS(D!)
```

The first sequence is the *stage* keyword carried on the level-1
heading. The second is the *verdict* keyword carried on each log
entry's `**** DoD` sub-sub-heading. Org doesn't scope sequences to
heading levels — discipline keeps stage keywords on level 1 and
verdict keywords on level 4 `DoD` headings only. The parsers care
about structural position (level + parent), so a cross-applied
keyword is silently ignored rather than mis-classified.

### Entry shape

```
*** [2026-05-20 Wed 11:30] ITERATING (via /advance from PLANNING)
    :PROPERTIES:
    :STAGE:       ITERATING
    :ENTERED:     [2026-05-20 Wed 11:30]
    :ENTERED_VIA: /advance from PLANNING
    :EXITED:      [2026-05-20 Wed 14:00]   (only on past entries)
    :DURATION:    2h 30m                    (only on past entries)
    :END:
**** Request
     What the user asked.
**** Work
     What was done (updated over the stage's lifetime).
**** [5/6] UNSATISFIABLE DoD
     CLOSED: [2026-05-20 Wed 14:00]        (auto-written on PASS only)
     :LOGBOOK:
     - State "UNSATISFIABLE" from "PENDING" [2026-05-20 Wed 13:50]
     - State "PENDING"       from ""        [2026-05-20 Wed 11:30]
     :END:
     - [X] one
     - [X] two
     ... (more checkboxes; `- [ ]/[X]/[-]`) ...
     - [ ] one that isn't met yet

     Optional explanation prose (required when verdict is
     UNSATISFIABLE).
```

The level-3 heading text is prefixed with `[<timestamp>]` so org
doesn't mistake the stage word for a TODO state. The stage is read
from the `:STAGE:` property (the canonical source); the heading text
is informational.

### Parser & helpers

All schema-aware code lives in `bin/cloude_org.py`. The module is
stdlib-only by convention rather than necessity — see [Why hot-path
hooks don't use `uv run`](#why-hot-path-hooks-dont-use-uv-run) for
the launcher that resolves the shared venv (orgparse, etc.) and the
cold-start reasoning behind the split. The exposed surface:

- `iter_log_entries(text)` / `latest_log_entry(text)` — yield one
  dict per entry with `stage`, `entered`, `entered_via`, `exited`,
  `duration`, `request`, `work`, `dod_verdict`, `dod_cookie`,
  `dod_checkboxes` (list of `'open'` / `'ticked'` / `'na'` per
  bullet), `dod_body`, and `span` / `dod_span` char-offset pairs for
  surgical rewrites.
- `append_log_entry_skeleton(text, stage=..., via=..., prev_stage=...,
  when=...)` — appends a fresh entry skeleton with one `- [ ]` per
  `STAGE_DOD[stage]` bullet under `**** [0/N] PENDING DoD`, and
  stamps `:EXITED:` + `:DURATION:` on the previous entry.
- `set_dod_verdict(text, new_verdict=..., when=..., body=None)` —
  flips the latest entry's DoD heading's TODO keyword, prepends a
  state-change line to its `:LOGBOOK:` drawer, writes the `CLOSED:`
  timestamp on PASS, and validates the verdict/cookie consistency
  rule. Raises `DodConsistencyError` on inconsistency
  (`PASS` ⇒ all ticked/N/A; `UNSATISFIABLE` ⇒ ≥1 open;
  `PENDING` ⇒ no constraint).
- `STAGE_DOD: dict[str, tuple[str, ...]]` — per-stage DoD bullets,
  consumed by the skeleton generator and the hook. CLAUDE.md's
  *Stage details* sections mirror these as the human-facing copy.
- `set_idea_slug(content, heading_text, slug)` — write a `:SLUG:`
  property into the level-2 idea heading matching `heading_text` in
  `tasks/staging.org`. Inserts a new properties drawer if none
  exists, otherwise inserts the `:SLUG:` line before the drawer's
  `:END:` (preserving drawer indent). Raises `SlugClobberError`
  when an existing non-empty `:SLUG:` doesn't match (user-set slugs
  win); an empty `:SLUG:` is the "please suggest" sentinel and gets
  replaced. Backs `bin/cloude-set-staging-slug`.
- `SLUG_RE` / `SLUG_MAX_LEN` / `SlugClobberError` — validation
  pattern and exception used by `set_idea_slug` and
  `cloude-set-staging-slug`.

### Lifecycle

- `cloude-promote-setup` seeds the initial entry (`/promote`,
  PLANNING for standard mode or ITERATING for ADOPT mode).
- `cloude-task-set-state --todo <STAGE>` (called by `/advance`,
  `/iterate`, `/drop`) flips the level-1 keyword *and* appends a
  fresh entry skeleton via `append_log_entry_skeleton`, inferring
  `:ENTERED_VIA:` from the transition direction
  (`/advance` for forward, `/iterate` for backward, `/drop` for
  `→ DROPPED`). Pass `--via TEXT` to override.
- `cloude-task-set-state --dod-state <verdict> [--reason "..."]`
  flips the latest entry's DoD verdict via `set_dod_verdict`. Refuses
  inconsistent transitions (exit code `31`).
- `cloude-on-stop` consumes the per-task DoD marker on a transition /
  `/iterate` turn and runs the verdict check. The hook blocks once
  on any of: `PENDING` verdict, verdict/cookie mismatch, missing
  `** Log` section, empty log section, or stage mismatch between
  level-1 and latest entry's `:STAGE:`.

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
  that `/promote` skips. The `[ADOPT]` suffix on a listing line is
  derived from the idea's own `:ADOPT:` property (see *Staging-idea
  trigger properties*); idea heading text is free-form and never
  pattern-matched. With `--select N`, instead emits the chosen
  idea's full record (`REPO`, `HEADING`, `MODE`, `PR_URL`,
  `COMPANION`, `SKIP_REVIEW`, `SLUG`) as shell-safe `KEY=VALUE`
  lines, so `/promote` can `eval` it rather than re-parsing
  staging.org. `MODE` is `adopt` iff the idea has `:ADOPT:` set;
  `PR_URL` carries the `:ADOPT:` value in that case. `COMPANION`
  carries the idea's `:COMPANION:` property (empty if absent).
  `SKIP_REVIEW` carries the project heading's optional
  `:SKIP_REVIEW:` property. `SLUG` carries the idea's `:SLUG:`
  property (empty if absent — `/promote` falls back to the
  mechanical kebab derivation). With `--slugless`, emits a
  tab-separated `<project>\t<heading>` line per idea whose `:SLUG:`
  is missing or empty (the "needs a suggestion" set); empty
  output means there's nothing to do. Used by `/promote` step 1
  (default + `--select`) and by `bin/cloude-watch-staging-slugs` /
  `/suggest-slugs` (`--slugless`).
- **`cloude-set-staging-slug <heading-text> <slug>`** — Write a
  `:SLUG:` property into the staging.org idea sub-heading whose text
  matches `<heading-text>`. Inserts a fresh properties drawer if the
  idea has none, otherwise inserts the `:SLUG:` line just before the
  drawer's `:END:`. Refuses to overwrite an existing non-empty
  `:SLUG:` (exit 3 — user-set slugs win over the LLM-generated
  ones); an *empty* `:SLUG:` is treated as the explicit "please
  suggest" sentinel and gets replaced. Validates `<slug>` against
  `SLUG_RE` (exit 30 on malformed). Called by `/suggest-slugs` once
  per heading returned by `cloude-list-staging --slugless`.
- **`cloude-watch-staging-slugs`** — Long-running watcher: emits
  `STAGING_HAS_SLUGLESS_IDEAS` on stdout each time
  `tasks/staging.org` ends up with an idea lacking a `:SLUG:`. The
  host-side `Monitor` armed by `/suggest-slugs-watch` consumes those
  lines as notification turns that route to `/suggest-slugs`.
  Singleton via non-blocking `flock -n` on
  `/tmp/cloude-watch-staging-slugs.lock` — exactly one watcher
  runs across concurrent host sessions; losers exit immediately
  (no standby, no retry). Honors `CLOUDE_NO_SLUG_WATCH=1`.
  Requires `inotifywait` (Debian/Ubuntu: `apt install inotify-tools`).
- **`cloude-on-host-session-start`** — Host-side `SessionStart` hook
  (registered in `.claude/settings.json`). Emits a
  `hookSpecificOutput.additionalContext` JSON that tells claude to
  call `/suggest-slugs-watch` early in the session — the auto-arm
  step for the staging-slug watcher. Always exits 0; never blocks
  session start. Honors `CLOUDE_NO_SLUG_WATCH=1` by emitting no
  additionalContext.
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
  `SKIP_REVIEW` / `COMPANION` when present), and derived fields (`SLUG`,
  `REPO_NAME`, `SOURCE_CLONE`, `TMUX_SESSION`, `DIND_VOLUME`,
  `CLOUDE_ROOT`). Sourced by `cloude-finalize-cleanup` and by the
  `/advance`, `/iterate`, `/drop`, `/babysit-ci`, `/babysit-merge`
  skills at their read-the-task-file step. Exit 3 names the missing
  key when a required property is absent.
- **`cloude-task-set-state <task-file> [--todo NAME] [--tag NAME] [--via TEXT]`**
  / **`cloude-task-set-state <task-file> --dod-state NAME [--reason TEXT]`** —
  Two modes, sharing one entry point. The first rewrites the
  level-1 stage heading: `--todo` swaps the stage keyword (and on
  any TODO change also appends a fresh log-entry skeleton via
  `cloude_org.append_log_entry_skeleton`, stamping `:EXITED:` +
  `:DURATION:` on the previous entry); `--tag` replaces the
  trailing tag chain with one tag; `--via TEXT` overrides the
  auto-inferred `:ENTERED_VIA:` text on the new skeleton (default:
  `/advance` for forward, `/iterate` for backward, `/drop` for
  `→ DROPPED`). The second flips the latest `** Log` entry's DoD
  verdict via `cloude_org.set_dod_verdict` — enforces the
  verdict/cookie consistency rule (`PASS` ⇒ all ticked; `UNSATISFIABLE`
  ⇒ ≥1 open) and exits `31` on violation, prepends a state-change
  line to the DoD heading's `:LOGBOOK:` drawer, and on `PASS`
  writes a `CLOSED:` timestamp (mirroring what `org-log-done` would
  do). `--reason TEXT` (second form only) replaces the prose block
  below the checkbox lines. The two modes are mutually exclusive.
  This is the one place the task-heading and DoD-heading edits are
  spelled out — the `/advance`, `/iterate`, `/drop`, `/babysit-ci`,
  `/babysit-merge` skills, `cloude-finalize-cleanup`'s force-drop,
  and the stop hook's deterministic tag flip all call it instead of
  re-deriving the rewrite. Prints the resulting `TODO` / `TAG` (first
  form) or `DOD_VERDICT` (second form). Regex-based, no dependency,
  runs on plain `python3`.
- **`cloude-promote-setup`** — Bash orchestrator for `/promote`
  steps 4-9: ensure source clone, create worktree + branch, push
  (standard) or fetch (ADOPT), open draft PR (standard only),
  render task file from `tasks/TEMPLATE.org`, remove staging entry,
  start tmux session, and queue the staging entry (heading + body,
  with any properties drawer stripped) to pre-fill the container's
  input box via `cloude-prefill-prompt` — both modes get the
  prefill, since the staging idea is the user's free-form direction
  in either case. The tmux session is created with two windows:
  window 0 (`agent`, selected by default) runs `bin/cloude-run`;
  window 1 (`task`) runs `bin/cloude-open-task-file` as a read-only
  live view of the task's `.org` file. Optional flags
  `--skip-review` and `--companion <id>` render
  `:SKIP_REVIEW: t` and `:COMPANION: <id>` respectively into
  the new task file's properties drawer. Distinct non-zero exit
  codes per failure mode (10 clone, 11 worktree, 12 PR, 13 render,
  14 staging removal, 20 tmux collision, 30 arg validation) and a
  "Succeeded so far" trail on stderr.
- **`cloude-prefill-prompt <tmux-session> <prompt-file>`** —
  Best-effort background poller that pre-fills a freshly promoted
  task's Claude Code input box. Launched detached by
  `cloude-promote-setup` (both standard and ADOPT modes): it watches
  the task's tmux pane until Claude Code's interactive input box is
  ready, then
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
- **`cloude-open-task-file <task-file-abs-path>`** — Editor
  launcher for the `task` window of the per-task tmux session.
  Picks an editor by this order: `emacs` on `PATH` (terminal mode
  via `-nw`, with `read-only-mode` and `auto-revert-mode` enabled
  via `--eval`); else `$EDITOR` if its basename is `vim` / `nvim` /
  `vi` (`-R` for read-only, `autoread` + a `CursorHold` `checktime`
  autocmd for on-disk-change refresh); else a generic `exec
  "$EDITOR" "$FILE"` (no enforced read-only / auto-revert); else
  print an error and `exit 1`. The `; exec bash` wrapper in the
  caller (`cloude-promote-setup`) keeps the window alive at a
  shell on the error path. Atomic-rename-aware: `less +F` is
  intentionally **not** used as a fallback because it holds the
  pre-rename inode and would silently show stale content as
  `cloude-task-set-state` rewrites the file.
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
  `/babysit-merge` owns its tag). *DoD check:* blocks the stop once
  with a targeted message when the latest `** Log` entry's verdict is
  not yet acceptable — **but only** on turns that began with a stage
  transition or an `/iterate`, not on ordinary conversational turns.
  Those transition turns drop a per-task marker file (in `/tmp`);
  `cloude-task-set-state` arms it on every `--todo` change into an
  in-flight stage, and this hook consumes it. The check is a pure
  org-parse of the latest log entry (see the
  [per-stage log entry section](#per-stage-log-entry-schema-and-hook-check)
  below): the verdict is the TODO keyword on the `**** DoD` heading
  (drawn from the secondary `#+TODO:` sequence), and the per-bullet
  checkboxes must agree with it (`PASS` ⇒ every box ticked or N/A;
  `UNSATISFIABLE` ⇒ at least one open). The hook blocks for
  `PENDING`, an inconsistent verdict/cookie pair, a missing `** Log`
  section, or a stage mismatch between the level-1 keyword and the
  latest entry's `:STAGE:`. `stop_hook_active` bounds the block to
  once per stop cycle. *Background-work carve-out:* the hook is a
  full no-op (no tag flip, no DoD check, the marker stays armed for
  next turn) whenever the agent is still waiting on background work
  it kicked off. Two signals each suffice: a `/babysit-ci` or
  `/babysit-merge` state file in the worktree
  (`.cloude-babysit-*-state.json`), and an in-flight background Bash
  detected by scanning the transcript JSONL for a
  `run_in_background: true` start without a matching completion
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
heading parsing, the DoD-marker path helper, the per-stage `STAGE_DOD`
bullets, and the `** Log` entry helpers (`iter_log_entries`,
`latest_log_entry`, `append_log_entry_skeleton`, `set_dod_verdict`,
`find_log_section`) through `bin/cloude_org.py`.

### Host-side hooks (`.claude/settings.json`)

A separate `.claude/settings.json` at the cloude repo root configures
hooks for *host* claude sessions (the ones running in the cloude
repo, not inside a per-task container). These do not affect the
in-container settings file above; they're loaded independently by
Claude Code based on the cwd.

- **`SessionStart` → `bin/cloude-on-host-session-start`.** Fires when
  a host claude session opens against the cloude repo. Emits JSON
  with `hookSpecificOutput.additionalContext` instructing claude to
  call `/suggest-slugs-watch` early in the session — that arms the
  staging-slug watcher (`bin/cloude-watch-staging-slugs`) via a
  persistent `Monitor`. Idempotent across concurrent sessions thanks
  to the watcher's `flock -n`. `CLOUDE_NO_SLUG_WATCH=1` makes this
  emit nothing.

### Why hot-path hooks don't use `uv run`

The hook scripts above and `cloude-task-set-state` are on the
per-turn hot path — `Stop`, `UserPromptSubmit`, and
`PreToolUse:AskUserQuestion` fire on every agent turn. Running each
through `uv run --script` would pay `uv`'s resolution / venv-creation
overhead per invocation (tens-to-hundreds of ms warm, more cold) —
multiplied across every turn of every concurrent task, that adds up
fast. So instead the dependencies are pre-resolved into a venv on
disk once and the hooks re-exec into its Python:

- `pyproject.toml` + `uv.lock` at the repo root declare the shared
  Python deps (currently `orgparse>=0.4` and `inotify_simple>=1.3;
  sys_platform=='linux'`). One source of truth across host and
  container.
- `make sync` (host) runs `uv sync --frozen --no-install-project`
  into `./.venv-host/`.
- The Dockerfile runs the same `uv sync` against the same lockfile
  into `/opt/cloude-venv/` — outside the cloude repo's read-only
  bind mount so the host's `.venv-host/` can't shadow it.
- `bin/cloude-python` is a 5-line `sh` launcher that exec's the
  in-container venv's `python3` if present, falling back to the
  host venv. It self-locates via `$0`, so neither side needs
  `cloude-python` on `PATH`.
- Each Python hook carries an sh/Python polyglot shebang
  (`#!/bin/sh` + a `:` no-op + `exec "$(dirname …)/cloude-python"`
  + a closing `" """`) so the kernel runs `sh`, sh `exec`s the
  launcher on this same file, and Python then re-reads it. The
  polyglot string takes Python's implicit module-docstring slot, so
  scripts that read `__doc__` (currently just `cloude-task-set-state`
  for `--help`) rebind it with an explicit `__doc__ = """…"""`.

`cloude-promote-setup` is a bash orchestrator whose orgmode-touching
steps (render task file, seed initial log entry, remove staging
entry) shell out to `cloude-python -c '...'` one-liners that call
named helpers in `cloude_org.py`. No inline `python3 - <<'PY'`
heredocs — the bash script is just process glue around git, `gh`,
`tmux`, and the three Python helpers.

`cloude_org.py` imports `orgparse` for its read-side parsers
(`parse_heading`, `has_level2_section`, `remove_staging_entry`).
Writers (`find_log_section`, `iter_log_entries`,
`append_log_entry_skeleton`, `set_dod_verdict`,
`mark_plan_approved`, `_stamp_exited_duration`) and the heading
rewriter in `cloude-task-set-state` stay on regex: they all need
byte/line ranges per node so they can splice replacements back into
the file, and `orgparse` doesn't expose those ranges.

The org-reading helper scripts (`cloude-dash`, `cloude-list-active`,
`cloude-list-staging`, `cloude-task-info`) are off the hot path and
keep their PEP 723 `uv run --script` shebangs — `uv` caches its
resolutions, so warm starts are fast enough and the inline-deps
header keeps each script self-describing.

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
- The host's IANA timezone is forwarded as `TZ=<zone>` so in-container
  timestamps (the task file's `** Log` entries, `date`, etc.) match
  host-side `/promote` / `/finalize` stamps instead of mixing two
  clocks in the same org file. The name is taken from `$TZ` if set,
  otherwise derived by resolving `/etc/localtime`'s symlink target
  and stripping everything up to and including `/zoneinfo/` (works on
  Linux's `/usr/share/zoneinfo/...` and macOS's
  `/var/db/timezone/zoneinfo/...`). The container ships
  `tzdata`/`/usr/share/zoneinfo` via the `node:20-bookworm` base, so
  setting `TZ` alone is enough — no bind mount of `/etc/localtime`,
  no Dockerfile change. Hosts whose `/etc/localtime` isn't a symlink
  and have no `$TZ` set silently fall back to UTC.
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

## Test suite

The Python helpers in `bin/` are tested under `tests/`. Run the suite
with `make test` (which depends on `make sync` so the host venv is up
to date) or directly with `.venv-host/bin/python -m pytest`. The same
command runs in `.github/workflows/test.yml` on every pull request and
push to `master`.

Two layers, sharing one `conftest.py`:

- **In-process unit tests** import `cloude_org` directly and call its
  functions (parse / iterate / mark / append / set-verdict). The
  no-extension scripts in `bin/` are loaded via the `import_script`
  fixture (a `SourceFileLoader` shim) when a single helper is worth
  unit-testing without spawning a subprocess.
- **Subprocess tests** spawn the script under `.venv-host/bin/python`
  via the `run_script` fixture, feed stdin / args, and assert on the
  exit code, on stdout, and on side effects against a `task_file_factory`
  fixture that writes throwaway task `.org` files into `tmp_path/tasks/active/`.

Out of scope (intentionally): the bash helpers (`cloude-finalize-cleanup`,
`cloude-promote-setup`, `cloude-run`, `cloude-prefill-prompt`,
`cloude-open-task-file`, `cloude-python`); the curses rendering and
inotify watcher in `cloude-dash` (the pure data layer is covered); and
any real Docker / tmux / `gh` side effects.
