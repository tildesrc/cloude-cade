#!/usr/bin/env bash
# Container entrypoint. Runs as root (required to start dockerd and to
# fix up bind/volume permissions), then drops privileges to the
# unprivileged `cloude` user before running the requested command.

set -euo pipefail

# --- Claude credentials persistence -----------------------------------
#
# Claude Code stores state in two places under $HOME:
#   - $HOME/.claude/           (directory; .credentials.json holds OAuth tokens)
#   - $HOME/.claude.json       (sibling file; 100KB+ of config and account state)
#
# Both must persist across container runs or the user has to log in every
# time. We mount a single named volume at /persist and stage both paths
# inside it:
#   /persist/dot-claude/   <- bind point for ~/.claude (via symlink)
#   /persist/claude.json   <- snapshot of ~/.claude.json
#
# A named volume created fresh is owned by root; chown it so the
# unprivileged cloude user can actually write to it.

PERSIST=/persist
mkdir -p "$PERSIST/dot-claude"
chown -R cloude:cloude "$PERSIST"

# Replace ~/.claude with a symlink into the volume. Anything baked into
# the image's home dir (none today, but defensive) is discarded.
rm -rf /home/cloude/.claude
ln -sfn "$PERSIST/dot-claude" /home/cloude/.claude
chown -h cloude:cloude /home/cloude/.claude

# Restore the sibling config file from the prior run, if any. We can't
# symlink this one: Claude Code writes it via atomic rename, which
# would replace the symlink with a regular file and break persistence.
# Instead, copy in on start and copy out on exit.
if [[ -f "$PERSIST/claude.json" ]]; then
    cp -a "$PERSIST/claude.json" /home/cloude/.claude.json
    chown cloude:cloude /home/cloude/.claude.json
fi

persist_claude_json() {
    if [[ -f /home/cloude/.claude.json ]]; then
        cp -a /home/cloude/.claude.json "$PERSIST/claude.json" 2>/dev/null || true
    fi
}
trap persist_claude_json EXIT

# --- dockerd (DinD) ---------------------------------------------------
mkdir -p /var/log
dockerd >/var/log/dockerd.log 2>&1 &

for _ in $(seq 1 30); do
    if docker info >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! docker info >/dev/null 2>&1; then
    echo "ERROR: dockerd failed to start within 30s. Last lines of /var/log/dockerd.log:" >&2
    tail -50 /var/log/dockerd.log >&2 || true
    exit 1
fi

# --- Run the command as the cloude user -------------------------------
# IMPORTANT: do NOT `exec` here — the EXIT trap must fire after the
# command finishes so ~/.claude.json gets copied back into the volume.
gosu cloude "$@"
