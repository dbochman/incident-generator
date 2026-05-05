.PHONY: list catalog validate smoke doctor docs-check fixture-hygiene lint test package release-check

PYTHON ?= python3

list:
	$(PYTHON) -m incident_generator list

catalog:
	$(PYTHON) -m incident_generator catalog

validate:
	$(PYTHON) -m incident_generator validate

smoke:
	$(PYTHON) -m incident_generator run --scenario scenarios/linux/disk-full/capacity --collection-mode fixture --json

doctor:
	$(PYTHON) -m incident_generator doctor

docs-check:
	$(PYTHON) -m incident_generator docs-check

fixture-hygiene:
	$(PYTHON) -m incident_generator fixture-hygiene

lint:
	$(PYTHON) -m compileall incident_generator tests

test:
	$(PYTHON) -m unittest discover -s tests

package:
	$(PYTHON) -m pip wheel --no-deps -w dist .

release-check: lint validate catalog smoke docs-check fixture-hygiene test package
