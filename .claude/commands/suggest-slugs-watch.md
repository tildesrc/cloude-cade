---
description: Arm a background watcher that asks you to generate `:SLUG:` properties for new staging.org ideas
---

You are arming the staging-slug watcher in this host claude session. The watcher is a long-running `Monitor`-armed background process that fires a notification line into the chat every time `tasks/staging.org` ends up with an idea sub-heading lacking a `:SLUG:` property. On each such notification you run `/suggest-slugs` to generate slugs and write them back.

The watcher script (`bin/cloude-watch-staging-slugs`) uses a non-blocking flock on `/tmp/cloude-watch-staging-slugs.lock` to enforce a singleton: if another host claude session is already watching, this arming is a near-no-op (the script logs a message to stderr and exits — its `Monitor` reports the exit and goes quiet). So this slash command is safe to call multiple times and across sessions.

## 1. Arm the Monitor

Call the `Monitor` tool with:

- `command`: `bin/cloude-watch-staging-slugs`
- `description`: `staging-slug watcher`
- `persistent`: `true`
- (no `timeout_ms` needed when persistent)

The cwd is the cloude repo (this slash command is host-side; you're already there). The watcher's stdout is the event stream; expect lines like:

```
STAGING_HAS_SLUGLESS_IDEAS
```

It also emits one initial check at arm time, so if any pre-existing staging ideas are slugless you'll be triggered immediately.

## 2. Standing instruction

For the lifetime of this session: whenever a notification arrives that contains `STAGING_HAS_SLUGLESS_IDEAS`, run `/suggest-slugs` to handle it. Do not run `/suggest-slugs` on unrelated notifications (background bash completions, etc.).

## 3. Report

After arming, print a short confirmation:

```
Staging-slug watcher armed (persistent Monitor). I'll run /suggest-slugs on each STAGING_HAS_SLUGLESS_IDEAS notification.
```

If `Monitor` reports the watcher exited immediately (another session holds the lock, or `CLOUDE_NO_SLUG_WATCH` is set), say so instead — there's nothing to do.
