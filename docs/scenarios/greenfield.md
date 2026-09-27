# Scenario: Greenfield (new system)

## Scope mapping
Greenfield scenarios (new systems/features) + well-defined requirements.

## Default requirement
Build a URL shortener from scratch with shorten/redirect, analytics, validation, health, custom aliases.

## Run
```bash
python -m pipeline build --scenario greenfield --auto-approve
```

## What to show
- Agents create a new project under `workspace/url_shortener_greenfield_<id>/`
- `05_implement.json` source is create-mode (not enhance)
- Tests/docs generated as part of SDLC stages