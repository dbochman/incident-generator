# Random Pair Fixture Preview

`pair-preview` renders the checked fixed-seed pair list for the next warm-kind
random-8 benchmark chunk.

```sh
python3 -m incident_generator pair-preview --json
```

The preview uses seed `20260506`, `kind` archetype filtering, and `real`
compatibility checks without starting infrastructure. The current audited pool
has `476` included and `20` rejected pairs out of `496` candidate `kind` pairs.
The report records eight selected pairs, expected hypotheses, relative scenario
paths, aggregate resource claims, and target-state conflict counts.
