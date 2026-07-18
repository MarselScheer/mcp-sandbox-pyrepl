SHELL := /bin/bash
.ONESHELL:

PARENT_NAME := $(shell basename $(dir $(PWD)))

emacs-docker:
	@echo -------------------- $@ $$(date) --------------------
	sudo docker image inspect mcp-sandbox-pyrepl-ide:latest >/dev/null 2>&1 || make rebuild-docker
	docker ps --filter "name=id" --filter "status=running" --quiet | grep -q . || make start-docker
	xhost +si:localuser:$$USER
	sudo docker exec $(PARENT_NAME)-ide /bin/sh -c "emacs"
	xhost -si:localuser:$$USER


build-docker-context:
	@echo -------------------- $@ $$(date) --------------------
	-rm -rf docker_context
	mkdir docker_context
	cp Dockerfile docker_context
	cp entrypoint.sh docker_context
	cp build-emacs.sh docker_context
	echo
	echo "Docker context created"

build-docker: build-docker-context
	@echo -------------------- $@ $$(date) --------------------
	sudo docker compose -f docker-compose.yaml -p $(PARENT_NAME) build || { exit 1; }
	rm -rf docker_context
	echo
	echo "Docker image build"

start-docker:
	@echo -------------------- $@ $$(date) --------------------
	sudo docker compose -f docker-compose.yaml -p $(PARENT_NAME) up -d || { exit 1; }
	echo
	echo "Docker container is running..."

shell-docker:
	@echo -------------------- $@ $$(date) --------------------
	sudo docker exec -it $(PARENT_NAME)-ide /bin/sh -c "/entrypoint.sh bash" || { exit 1; }
	echo
	echo "Docker container is running..."


root-docker:
	@echo -------------------- $@ $$(date) --------------------
	sudo docker exec -u root -it $(PARENT_NAME)-ide /bin/sh -c "/entrypoint.sh bash" || { exit 1; }
	echo
	echo "Docker container is running..."

stop-docker:
	@echo -------------------- $@ $$(date) --------------------
	sudo docker compose -f docker-compose.yaml -p $(PARENT_NAME) stop || { exit 1; }
	echo
	echo "Docker container is stopped"

rebuild-docker: stop-docker build-docker start-docker
