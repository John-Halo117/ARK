SHELL := /usr/bin/env bash

.PHONY: ci-once ci-loop smoke deploy-local install-hooks install-local-ci-service sync-online ai-enqueue ai-loop ai-apply ai-repair-last

ci-once:
	bash scripts/ci/run_once.sh "$$(git rev-parse HEAD)"

ci-loop:
	bash scripts/ci/watch_loop.sh

smoke:
	bash scripts/ci/smoke.sh

deploy-local:
	bash scripts/ci/deploy_local.sh "$$(pwd)"

install-hooks:
	git config core.hooksPath .githooks

install-local-ci-service:
	bash scripts/ci/install_service.sh

sync-online:
	bash scripts/sync/online_sync.sh

ai-enqueue:
	bash scripts/ai/enqueue_task.sh "$(TASK)"

ai-loop:
	python3 scripts/ai/local_codegen_loop.py

ai-apply:
	bash scripts/ai/apply_proposal.sh "$(PATCH)"

ai-repair-last:
	bash scripts/ai/enqueue_repair_last_failure.sh
