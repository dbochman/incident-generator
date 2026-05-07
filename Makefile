.PHONY: list catalog validate smoke doctor docs-check fixture-hygiene lint test package release-manifest benchmark-sets fixture-benchmark-gate training-curriculum skill-drill-export live-smoke clean-generated release-check check-focused check-package check-release check-operator-live

PYTHON ?= python3
PYTHON_NOBYTECODE := PYTHONDONTWRITEBYTECODE=1

list:
	$(PYTHON_NOBYTECODE) $(PYTHON) -m incident_generator list

catalog:
	$(PYTHON_NOBYTECODE) $(PYTHON) -m incident_generator catalog

validate:
	$(PYTHON_NOBYTECODE) $(PYTHON) -m incident_generator validate

smoke:
	$(PYTHON_NOBYTECODE) $(PYTHON) -m incident_generator run --scenario scenarios/linux/disk-full/capacity --collection-mode fixture --json

doctor:
	$(PYTHON_NOBYTECODE) $(PYTHON) -m incident_generator doctor

docs-check:
	$(PYTHON_NOBYTECODE) $(PYTHON) -m incident_generator docs-check

fixture-hygiene:
	$(PYTHON_NOBYTECODE) $(PYTHON) -m incident_generator fixture-hygiene

lint:
	tmp=$$(mktemp -d); PYTHONPYCACHEPREFIX="$$tmp" $(PYTHON) -m compileall incident_generator tests; status=$$?; rm -rf "$$tmp"; exit $$status
	bash -n harness/live-smoke.sh

test:
	$(PYTHON_NOBYTECODE) $(PYTHON) -m unittest discover -s tests

package:
	$(PYTHON_NOBYTECODE) $(PYTHON) -m pip wheel --no-deps -w dist .

release-manifest:
	$(PYTHON_NOBYTECODE) $(PYTHON) -m incident_generator release-manifest --output dist/release-manifest.json

benchmark-sets:
	$(PYTHON_NOBYTECODE) $(PYTHON) -m incident_generator benchmark-sets --json >/dev/null

fixture-benchmark-gate:
	$(PYTHON_NOBYTECODE) $(PYTHON) -m incident_generator validate --json >/dev/null
	$(PYTHON_NOBYTECODE) $(PYTHON) -m incident_generator catalog --json >/dev/null
	$(PYTHON_NOBYTECODE) $(PYTHON) -m incident_generator benchmark-sets --json >/dev/null

training-curriculum:
	$(PYTHON_NOBYTECODE) $(PYTHON) -m incident_generator training-curriculum --json >/dev/null

skill-drill-export:
	$(PYTHON_NOBYTECODE) $(PYTHON) -m incident_generator skill-drill-export --output-dir dist/training-drills --created-at 2026-05-06T00:00:00Z --json >/dev/null

live-smoke:
	PYTHON=$(PYTHON) harness/live-smoke.sh

clean-generated:
	rm -rf .tmp build dist .pytest_cache incident_generator.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

check-focused:
	$(MAKE) --no-print-directory lint
	$(MAKE) --no-print-directory fixture-benchmark-gate

check-package:
	$(MAKE) --no-print-directory check-focused
	$(MAKE) --no-print-directory smoke
	$(MAKE) --no-print-directory docs-check
	$(MAKE) --no-print-directory fixture-hygiene
	$(MAKE) --no-print-directory test

check-release:
	$(MAKE) --no-print-directory release-check

check-operator-live:
	@echo "Operator-live package checks are opt-in and require live tools."
	@echo "Run: make live-smoke PYTHON=$(PYTHON)"

release-check:
	$(MAKE) --no-print-directory lint
	$(MAKE) --no-print-directory fixture-benchmark-gate
	$(MAKE) --no-print-directory smoke
	$(MAKE) --no-print-directory docs-check
	$(MAKE) --no-print-directory fixture-hygiene
	$(MAKE) --no-print-directory test
	tmp=$$(mktemp -d); \
	status=0; \
	$(PYTHON_NOBYTECODE) $(PYTHON) -m pip wheel --no-deps -w "$$tmp/dist" . || status=$$?; \
	if [ $$status -eq 0 ]; then $(PYTHON_NOBYTECODE) $(PYTHON) -m incident_generator release-manifest --output "$$tmp/dist/release-manifest.json" --artifact-dir "$$tmp/dist" || status=$$?; fi; \
	if [ $$status -eq 0 ]; then $(PYTHON_NOBYTECODE) $(PYTHON) -m incident_generator training-curriculum --json >/dev/null || status=$$?; fi; \
	if [ $$status -eq 0 ]; then $(PYTHON_NOBYTECODE) $(PYTHON) -m incident_generator skill-drill-export --output-dir "$$tmp/dist/training-drills" --created-at 2026-05-06T00:00:00Z --json >/dev/null || status=$$?; fi; \
	rm -rf "$$tmp" build incident_generator.egg-info; \
	exit $$status
