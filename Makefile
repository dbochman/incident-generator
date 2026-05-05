.PHONY: list catalog validate smoke doctor test

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

test:
	python3 -m unittest discover -s tests
