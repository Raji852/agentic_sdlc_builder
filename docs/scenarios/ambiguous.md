# Scenario: Ambiguous requirements

## Scope mapping
Well-defined and **ambiguous** requirements (this scenario is the ambiguous path).

## Default requirement
“Make the URL shortener enterprise ready and better overall.”

## Behavior
- GatherRequirements forces ambiguities + options A/B/C (C deferred)
- Clarify waits for `scope_approval` (unless `--auto-approve`)
- Bounded slice is implemented after human/auto choice

## Run
```bash
# Interactive (best for demo)
python -m pipeline build --scenario ambiguous
python -m pipeline approve --run-id <ID> --approval scope_approval --choice A
python -m pipeline approve --run-id <ID> --approval design_approval
python -m pipeline approve --run-id <ID> --approval release_approval

# Unattended
python -m pipeline build --scenario ambiguous --auto-approve
```