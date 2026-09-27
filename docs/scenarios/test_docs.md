# Scenario: Test & documentation improvements

## Scope mapping
Test and documentation improvements (on an existing baseline).

## Default requirement
Expand automated tests and upgrade README/runbook/API examples/limitations.

## Behavior
1. Seeds a thin baseline (smoke test + minimal README)
2. Agents improve tests + docs on that existing codebase
3. Implement enhance-mode writes richer suite/docs

## Run
```bash
python -m pipeline build --scenario test_docs --auto-approve
```

## What to show
- Baseline started with only `test_health`
- After run: fuller `tests/test_app.py` and improved `README.md` / `docs_improvements.md`