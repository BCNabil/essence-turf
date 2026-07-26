# Essence Turf repository operating contract

This repository is the public static surface for ESSENCE. Publish only canonical
morning predictions already frozen before races and evening results already
validated by the private ESSENCE system. Keep proprietary generators, algorithms,
training data, credentials and internal evidence out of this repository. Preserve
the absolute anti-odds boundary.

<!-- SUMAPR:BEGIN -->
## SUMAPR operating gate

SUMAPR (Système Universel de Mémoire Active, de Prévention et de Réplication)
is mandatory for every material action in this repository. It is deterministic
and does not run an additional agent.

Before editing, executing, deciding or generating an implementation prompt:

```bash
python3 tools/sumapr.py preflight --task "<exact scope>" --domains "<comma-separated domains>" --mutating
```

Read only the generated capsule under `.git/sumapr/capsule.md` plus the files
needed for the task. Respect `READY`, `BLOCKED`, `CONTRADICTION`,
`HUMAN DECISION REQUIRED` and `RECOVERY MODE`. Do not bypass a non-READY
verdict. Use `--allow-dirty` only after proving that existing changes belong to
the same scope.

After execution, run proportionate project tests and close the action:

```bash
python3 tools/sumapr.py close --status success --validation "<commands and evidence>"
```

Use `failed` or `blocked` when appropriate. Errors, user corrections,
contradictions and avoidable rework must become candidate incidents. Promote a
candidate with `learn` only after cause, fix, evidence and a deterministic guard
are proven. Never turn an assumption into project truth.

Run `python3 tools/sumapr.py install` once per clone to activate the local
pre-commit gate. CI runs `python3 tools/sumapr.py check`; neither the hook nor CI
replaces the repository's existing tests or stricter instructions.
<!-- SUMAPR:END -->
