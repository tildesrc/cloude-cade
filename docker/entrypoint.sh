#!/usr/bin/env bash
# Container entrypoint. Runs as root (required to start dockerd), then
# drops privileges to the unprivileged `cloude` user before exec'ing the
# requested command.

set -euo pipefail

mkdir -p /var/log

# Start dockerd in the background. Output goes to a log file so it doesn't
# interleave with the user's terminal; tail it on failure for diagnosis.
dockerd >/var/log/dockerd.log 2>&1 &

# Wait for dockerd to be ready.
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

# Drop privileges and exec the requested command as the cloude user.
exec gosu cloude "$@"
