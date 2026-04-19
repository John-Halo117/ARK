SHELL := /usr/bin/env bash

.PHONY: ci-once ci-loop smoke deploy-local install-hooks install-local-ci-service sync-online

ci-once:
	bash scripts/ci/run_once.sh

ci-loop:
	bash scripts/ci/watch_loop.sh

smoke:
	bash scripts/ci/smoke.sh

deploy-local:
	bash scripts/ci/deploy_local.sh

install-hooks:
	git config core.hooksPath .githooks

install-local-ci-service:
	bash scripts/ci/install_service.sh

sync-online:
	bash scripts/sync/online_sync.sh
