IMAGE := cloude
VOLUME := cloude-claude-creds
HOST_UID := $(shell id -u)
HOST_GID := $(shell id -g)

.PHONY: help build rebuild shell login info clean-image clean-volume clean

help:
	@echo "Targets:"
	@echo "  build         Build the cloude image (UID/GID match host user)"
	@echo "  rebuild       Build with --no-cache"
	@echo "  shell         Open a bash shell in a transient container"
	@echo "  login         Run claude interactively to perform first-time login"
	@echo "  info          Show image and volume status"
	@echo "  clean-image   Remove the image"
	@echo "  clean-volume  Remove the credentials volume (forces re-login)"
	@echo "  clean         clean-image + clean-volume"

build:
	docker build \
		--build-arg HOST_UID=$(HOST_UID) \
		--build-arg HOST_GID=$(HOST_GID) \
		-t $(IMAGE) .

rebuild:
	docker build --no-cache \
		--build-arg HOST_UID=$(HOST_UID) \
		--build-arg HOST_GID=$(HOST_GID) \
		-t $(IMAGE) .

shell: build
	docker run --rm -it --privileged --entrypoint bash $(IMAGE)

login: build
	docker run --rm -it --privileged \
		-v $(VOLUME):/persist \
		-v $$HOME/.gitconfig:/home/cloude/.gitconfig:ro \
		-v $$HOME/.config/gh:/home/cloude/.config/gh:ro \
		$(IMAGE) claude

info:
	@echo "Image:"
	@docker images $(IMAGE) --format "table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedAt}}" 2>/dev/null || echo "  (not built)"
	@echo
	@echo "Volume:"
	@docker volume inspect $(VOLUME) 2>/dev/null || echo "  (not created)"

clean-image:
	-docker image rm $(IMAGE)

clean-volume:
	@echo "WARNING: removing $(VOLUME) erases saved Claude credentials. Next run requires 'make login' or interactive login on first use."
	-docker volume rm $(VOLUME)

clean: clean-image clean-volume
