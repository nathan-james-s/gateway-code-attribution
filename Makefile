# Gateway Code Attribution — developer entry points (T006). Script bodies live in scripts/.
GATEWAY ?= agentgateway
VALUES ?=
SECRET ?=
CLUSTER ?= kind

.PHONY: lint test test-lib demo demo-upgrade demo-down eval perf images

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

test-lib:
	uv run pytest lib/tests

test: test-lib
	uv run pytest tests/integration tests/conformance

demo:
	GATEWAY=$(GATEWAY) VALUES=$(VALUES) SECRET=$(SECRET) CLUSTER=$(CLUSTER) scripts/demo.sh

demo-upgrade:
	VALUES=$(VALUES) scripts/demo-upgrade.sh

demo-down:
	CLUSTER=$(CLUSTER) scripts/demo-down.sh

eval:
	uv run gca eval --scenarios eval/scenarios --gateway both --out report.json

perf:
	tests/perf/run.sh

images:
	scripts/build-images.sh
