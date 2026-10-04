# Open-source Release Audit

## Current Release Boundary

The GitHub release should contain source code, anonymous examples, tests, and documentation only. Generated files and local business data must stay out of Git.

## Removed From Tracking

The repository previously tracked `tmp/` artifacts, including generated spreadsheets, ZIP packages, screenshots, stdout/stderr logs, and pytest scratch directories. Those are now removed from Git tracking.

## Enforced By Tests

`verification/fixes/tests/test_engineering_hygiene.py` checks:

- runtime artifact directories are ignored;
- generated screenshots and snapshots are not in the repository root;
- generated artifacts are not tracked by Git;
- production modules do not use bare `print(...)`.

`verification/fixes/ai_or_acceptance_audit.py` checks the generic AI OR kernel, Agent topology, Agent orchestration workflow, scheduler-to-generic rule bridge, scheduler solver-control bridge, scheduler conflict-detection generic backend bridge, non-scheduler CP-SAT smoke, documentation positioning, Git release boundary, and open-source deidentification markers. Its smoke problems cover resource scheduling, table/Element lookup, Automaton, Inverse, Circuit, MultipleCircuit, NoOverlap2D, Reservoir, MapDomain, arithmetic equality constraints, enforced linear constraints, solver parameters, hints, assumptions, decision strategies, and assumption-core debugging without depending on the K12 scheduler domain.

The scheduler bridge audit also reports `exact_cp_sat_shape_contract` and `catalog_contract` counts. `catalog_contract` is intentionally weaker: it proves the legacy rule is visible to the rule-first migration catalog, not that the old CP-SAT branch has exact generic parity.

## Manual Pre-publish Checks

Run:

```powershell
git status --short
git ls-files tmp outputs scheduler/outputs
.\.venv\Scripts\python.exe verification\fixes\ai_or_acceptance_audit.py
.\.venv\Scripts\python.exe -m pytest verification\fixes\tests\test_engineering_hygiene.py -q
```

Expected:

- no tracked `tmp/`, `outputs/`, or `scheduler/outputs/` files;
- no tracked `.xlsx`, `.zip`, generated screenshots, `.out`, `.err`, or `.log` artifacts; only explicitly reviewed product static images may be tracked;
- no real school, teacher, student, contact, address, or historical solve data in tracked files.

## Public Repository History

Publish this reviewed source snapshot into a new public repository with a fresh root commit. Do not change the visibility of the original private repository: its old branches and commits contain historical generated workbooks and screenshots, even though the current branch no longer tracks those files.
