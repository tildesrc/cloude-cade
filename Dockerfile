FROM node:20-bookworm

# Base tools
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg lsb-release \
        git tmux less jq gosu sudo vim \
    && rm -rf /var/lib/apt/lists/*

# Docker CE (engine + CLI + compose plugin) for DinD
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
       | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" \
       > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# GitHub CLI (Debian's gh is older than upstream)
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
       | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
       > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# uv (Astral's Python package/project manager). Common dev dependency
# for projects that use `uvx ...` or `uv run ...` (e.g. plugin hooks).
# Pinned to /usr/local/bin so it's on PATH for every user.
RUN curl -LsSf https://astral.sh/uv/install.sh \
    | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh

# Shared cloude Python venv at /opt/cloude-venv/, built from the
# repo-root pyproject.toml + uv.lock. The in-container hook scripts
# (cloude-on-stop, cloude-on-user-prompt, …) re-exec through
# bin/cloude-python, which prefers this venv. Living outside the
# cloude repo's read-only bind mount keeps the host's .venv-host/
# from shadowing it. `uv sync --frozen --no-install-project` resolves
# from the lockfile only and skips installing the (virtual) project
# itself. Only this layer is invalidated when deps change.
COPY pyproject.toml uv.lock /tmp/uv/
RUN cd /tmp/uv \
    && UV_PROJECT_ENVIRONMENT=/opt/cloude-venv \
       uv sync --frozen --no-install-project \
    && rm -rf /tmp/uv

# bun (JS/TS runtime + package manager). Installer needs unzip and
# drops the binary at $BUN_INSTALL/bin/bun; pin to /usr/local so it's
# on PATH for every user.
RUN apt-get update && apt-get install -y --no-install-recommends unzip \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://bun.sh/install \
       | env BUN_INSTALL=/usr/local bash

# UID/GID match the invoking host user. Defaults are sane for most Linux
# users; bin/cloude-run and the Makefile pass the actual host values.
ARG HOST_UID=1000
ARG HOST_GID=1000

# The base image ships a default `node` user (uid/gid 1000). If HOST_UID
# or HOST_GID collides with an existing user/group, remove it first so
# we can create `cloude` cleanly.
RUN set -eux; \
    if getent passwd "${HOST_UID}" >/dev/null; then \
        existing_user="$(getent passwd "${HOST_UID}" | cut -d: -f1)"; \
        userdel -r "$existing_user" 2>/dev/null || true; \
    fi; \
    if getent group "${HOST_GID}" >/dev/null; then \
        existing_group="$(getent group "${HOST_GID}" | cut -d: -f1)"; \
        groupdel "$existing_group" 2>/dev/null || true; \
    fi; \
    groupadd --gid "${HOST_GID}" cloude; \
    useradd --uid "${HOST_UID}" --gid "${HOST_GID}" \
        --create-home --shell /bin/bash cloude; \
    usermod -aG docker cloude; \
    echo "cloude ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/cloude; \
    chmod 0440 /etc/sudoers.d/cloude

# System-level git config: route HTTPS GitHub auth through the gh CLI,
# which gets its PAT from the host's mounted ~/.config/gh. The user's
# ~/.gitconfig (mounted read-only) takes precedence for everything
# else.
RUN { \
        echo '[credential "https://github.com"]'; \
        echo '    helper = !gh auth git-credential'; \
    } >> /etc/gitconfig

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Cloude-managed Claude Code settings, baked into the image. Surfaced
# to the in-container claude via `claude --settings /etc/cloude/settings.json`
# (added by bin/cloude-run). Layers on top of the user-scoped settings
# in the persist volume — doesn't replace them.
COPY docker/cloude-settings.json /etc/cloude/settings.json

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["claude", "--dangerously-skip-permissions"]
