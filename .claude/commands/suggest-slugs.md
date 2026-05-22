---
description: Generate concise `:SLUG:` properties for any staging.org idea that's missing one
---

You are generating filesystem slugs for `tasks/staging.org` ideas that have no `:SLUG:` property yet. Each generated slug becomes the default `/promote` uses for that idea later, so the goal is *short and descriptive* — better than the mechanical kebab-case derivation `/promote` falls back to.

This skill runs in two situations:

- *Auto*: the staging-slug watcher (armed by `/suggest-slugs-watch`) fires a `STAGING_HAS_SLUGLESS_IDEAS` notification.
- *Manual*: the user invokes `/suggest-slugs` directly.

Both paths do the same work — read the slugless list, generate slugs, write them back.

## 1. List slugless ideas

Run:

```
bin/cloude-list-staging --slugless
```

Each output line is tab-separated `<project>\t<heading-text>`. Empty output means nothing to do — print a one-liner like `No slugless ideas.` and stop.

## 2. Generate a slug for each heading

For each heading, derive a concise kebab-case slug. Aim for:

- 3-5 words, lowercase, hyphen-separated (`[a-z0-9][a-z0-9-]*[a-z0-9]`).
- Captures the action/subject the heading describes — favour verbs + the salient noun, drop articles and filler ("the", "a", "to", "for").
- ≤ ~40 chars where feasible (hard cap is 80).
- Distinct from sibling slugs in the same project — if a generated slug collides, add a differentiating word.

Examples (illustrative; pick what fits the actual heading):

- `Hook to auto-move COMPLETE files` → `auto-move-complete-files`
- `Serialize repo-hooks/unsupervised-main edits to the shared cloude-claude-creds volume` → `serialize-repo-hook-edits`
- `Support multiple workflows` → `multiple-workflows`
- `Take over the WIP refactor from someone else's branch` → `adopt-wip-refactor`

You're the LLM — the whole point of routing through the host claude session rather than a deterministic helper is that you can do this judgment well. Don't ask the user to confirm each one; just generate them.

## 3. Write each slug back

For every heading, call:

```
bin/cloude-set-staging-slug "<heading-text>" "<slug>"
```

The helper refuses to overwrite an existing user-set `:SLUG:` (exit 3) — that's the user winning over your suggestion, not a real failure, so just note it and continue. Malformed slug (exit 30) is a real bug in your generation; regenerate. Heading-not-found (exit 2) usually means the user edited staging.org between the listing and the write; skip that heading and continue.

## 4. Report

End with a compact summary listing each `heading → slug` that was set, plus any skips:

```
Suggested slugs:
  - Hook to auto-move COMPLETE files → auto-move-complete-files
  - Support multiple workflows       → multiple-workflows
Skipped:
  - Some other idea (user already set :SLUG: existing-slug)
```

Keep it tight — no extra prose.
