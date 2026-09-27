# Scenario: Brownfield (enhance existing)

## Scope mapping
Brownfield scenarios (enhancements, refactors, bug fixes).

## Default requirement
Enhance an existing shortener with custom aliases + rate-limit metadata, APIs, and regression tests.

## Behavior
1. Seeds (or copies) a baseline MVP codebase without alias/rate-limit
2. Impact analysis tasks/modules recorded
3. Implement **patches** the existing tree (does not start empty)

## Run
```bash
python -m pipeline build --scenario brownfield --auto-approve

# Or enhance a specific existing project:
python -m pipeline build --scenario brownfield --auto-approve --base-project workspace\<prior_project>
```

## What to show
- `01_requirements.json` → `impacted_modules`
- `03_decompose.json` → impact-analysis task T0
- `05_implement.json` → `enhance_mode: true`
- Generated app supports `custom_alias`