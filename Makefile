.PHONY: list catalog validate smoke doctor docs-check fixture-hygiene test

list:
	python3 -m incident_generator list

catalog:
	python3 -m incident_generator catalog

validate:
	python3 -m incident_generator validate

smoke:
	python3 -m incident_generator run --scenario scenarios/linux/disk-full/capacity --collection-mode fixture --json

doctor:
	python3 -m incident_generator doctor

docs-check:
	python3 -m incident_generator docs-check

fixture-hygiene:
	python3 -m incident_generator fixture-hygiene

test:
	python3 -m unittest discover -s tests
