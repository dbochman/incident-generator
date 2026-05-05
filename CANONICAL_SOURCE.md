# Canonical Source

`incident-generator` is exported from the canonical `sre-incident-agent-skills` repository.

Do not edit the standalone package repository by hand. Make changes in the canonical repo, run:

```sh
python3 tools/export_incident_generator_package.py --target ../incident-generator
```

Then validate the exported repo with its package gates before publishing or pushing it.
