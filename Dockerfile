FROM node:20-bookworm

# Base tools
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg lsb-release \
        git tmux less jq gosu sudo \
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

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["claude", "--dangerously-skip-permissions"]
