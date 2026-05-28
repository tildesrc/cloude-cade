IMAGE := cloude
# Claude credentials/state volume is per-repo: cloude-claude-creds-<repo>.
# bin/cloude-run picks the same name based on the worktree's parent dir
# (the repo name), so `make login REPO=foo` authenticates the volume
# that a `foo` task will mount on launch. REPO is required for `login`
# and `clean-volume`; `info` lists every cloude-claude-creds-* volume
# instead. The sed sanitization here MUST match bin/cloude-run's so the
# names line up.
VOLUME_PREFIX := cloude-claude-creds
REPO_SAFE := $(shell printf '%s' '$(REPO)' | sed 's/[^a-zA-Z0-9_.-]/-/g')
VOLUME := $(VOLUME_PREFIX)-$(REPO_SAFE)
HOST_UID := $(shell id -u)
HOST_GID := $(shell id -g)

# Host-side Python venv for the bin/ helpers that import third-party
# packages (orgparse, etc.). Built from pyproject.toml + uv.lock by
# `make sync`. The matching container venv lives at /opt/cloude-venv/
# inside the image (built in the Dockerfile from the same lockfile).
# Pinned to a distinct name so the cloude repo's bind-mount into the
# container can't shadow /opt/cloude-venv/.
HOST_VENV := .venv-host

.PHONY: help build rebuild shell login info sync test clean-image clean-volume clean-all-volumes clean-dind-data clean-venv clean require-repo

help:
	@echo "Targets:"
	@echo "  build               Build the cloude image (UID/GID match host user)"
	@echo "  rebuild             Build with --no-cache"
	@echo "  shell               Open a bash shell in a transient container"
	@echo "  login REPO=<repo>   Run claude interactively to authenticate <repo>'s creds volume"
	@echo "  sync                Build the host venv ($(HOST_VENV)/) from uv.lock (incl. dev deps)"
	@echo "  test                Run the pytest suite under tests/"
	@echo "  info                Show image and per-repo creds-volume status"
	@echo "  clean-image         Remove the image"
	@echo "  clean-volume REPO=<repo>  Remove one repo's creds volume (forces re-login for it)"
	@echo "  clean-all-volumes   Remove every per-repo creds volume (forces re-login for all)"
	@echo "  clean-dind-data     Remove per-task DinD data volumes (cloude-dind-*)"
	@echo "  clean-venv          Remove the host venv ($(HOST_VENV)/)"
	@echo "  clean               clean-image + clean-all-volumes + clean-dind-data + clean-venv"

require-repo:
	@if [ -z "$(REPO)" ]; then \
		echo "ERROR: REPO is required (e.g. 'make $(MAKECMDGOALS) REPO=<repo>')"; \
		echo "       <repo> is the cloude-side repo dir name — the parent of the worktree dir,"; \
		echo "       i.e. the name under $$PWD/worktrees/. Lists with 'ls worktrees/'."; \
		exit 1; \
	fi

build:
	docker build \
		--platform linux/amd64 \
		--build-arg HOST_UID=$(HOST_UID) \
		--build-arg HOST_GID=$(HOST_GID) \
		-t $(IMAGE) .

rebuild:
	docker build --no-cache \
		--platform linux/amd64 \
		--build-arg HOST_UID=$(HOST_UID) \
		--build-arg HOST_GID=$(HOST_GID) \
		-t $(IMAGE) .

shell: build
	docker run --rm -it --privileged \
		-v /var/lib/docker \
		--entrypoint bash $(IMAGE)

login: require-repo build
	docker run --rm -it --privileged \
		-v $(VOLUME):/persist \
		-v /var/lib/docker \
		-v $$HOME/.gitconfig:/home/cloude/.gitconfig:ro \
		-v $$HOME/.config/gh:/home/cloude/.config/gh:ro \
		$$([ -f $$HOME/.docker/config.json ] && echo "-v $$HOME/.docker/config.json:/home/cloude/.docker/config.json:ro") \
		$(IMAGE) claude

info:
	@echo "Image:"
	@docker images $(IMAGE) --format "table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedAt}}" 2>/dev/null || echo "  (not built)"
	@echo
	@echo "Per-repo creds volumes ($(VOLUME_PREFIX)-*):"
	@vols=$$(docker volume ls -q --filter name='^$(VOLUME_PREFIX)-'); \
	if [ -n "$$vols" ]; then \
		echo "$$vols"; \
	else \
		echo "  (none — run 'make login REPO=<repo>' to create one)"; \
	fi

sync:
	UV_PROJECT_ENVIRONMENT=$(HOST_VENV) uv sync --frozen --no-install-project

test: sync
	$(HOST_VENV)/bin/python -m pytest

clean-image:
	-docker image rm $(IMAGE)

clean-volume: require-repo
	@echo "WARNING: removing $(VOLUME) erases $(REPO)'s saved Claude credentials. Next launch of a $(REPO) task requires 'make login REPO=$(REPO)' or an interactive login on first use."
	-docker volume rm $(VOLUME)

clean-all-volumes:
	@vols=$$(docker volume ls -q --filter name='^$(VOLUME_PREFIX)-'); \
	if [ -n "$$vols" ]; then \
		echo "WARNING: removing every per-repo creds volume — re-login required for each repo:"; \
		echo "$$vols"; \
		echo "$$vols" | xargs docker volume rm; \
	else \
		echo "No $(VOLUME_PREFIX)-* volumes to remove."; \
	fi

clean-dind-data:
	@vols=$$(docker volume ls -q --filter name='^cloude-dind-'); \
	if [ -n "$$vols" ]; then \
		echo "Removing per-task DinD volumes:"; echo "$$vols"; \
		echo "$$vols" | xargs docker volume rm; \
	else \
		echo "No cloude-dind-* volumes to remove."; \
	fi

clean-venv:
	-rm -rf $(HOST_VENV)

clean: clean-image clean-all-volumes clean-dind-data clean-venv
