# Agentic SDLC Builder — Requirement → Working URL Shortener

LLM-powered agentic SDLC pipeline: agents call **OpenAI `gpt-4o-mini`** to gather requirements, design, generate code, document, and security-review a URL shortener under human approval gates.

```
Requirement  →  Gather → Clarify → Decompose → Design
             →  Implement (LLM writes code) → Test (+ optional LLM repair)
             →  Document + Security → Release approval
             →  workspace/<generated app>
```

## LLM setup (required for real runs)

1. Copy env file and add your key:
```powershell
copy .env.example .env
# edit .env and set:
# OPENAI_API_KEY=sk-...
# OPENAI_MODEL=gpt-4o-mini
# AGENT_MODE=openai
```

2. Install deps and run:
```powershell
cd "d:\CS Assignment\agentic-sdlc-builder"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# One-command demo (auto-approves human gates; uses OpenAI)
python -m pipeline build --scenario greenfield --auto-approve

# Assignment scope scenarios
python -m pipeline build --scenario greenfield --auto-approve
python -m pipeline build --scenario brownfield --auto-approve
python -m pipeline build --scenario ambiguous --auto-approve
python -m pipeline build --scenario test_docs --auto-approve

# Run all four offline (mock agents)
python scripts\run_all_scenarios.py

python -m pipeline scenarios
```

Scenario write-ups: `docs/scenarios/`.  
`AGENT_MODE=mock` skips OpenAI (unit tests / offline). Do **not** commit `.env`.

When the run completes, the agents have created a real app under `workspace/url_shortener_<run_id>/`.

```powershell
cd workspace\url_shortener_<run_id>
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# open http://127.0.0.1:8000/docs
```

## Interactive approvals (controlled autonomy)

```powershell
python -m pipeline build --requirement-file docs\sample_requirement.md
python -m pipeline approve --run-id <RUN_ID> --approval scope_approval --choice A
python -m pipeline approve --run-id <RUN_ID> --approval design_approval
python -m pipeline approve --run-id <RUN_ID> --approval release_approval
```

## What each agent does (LLM-backed)

| Stage | Agent action |
|---|---|
| GatherRequirements | `gpt-4o-mini` normalizes requirement → features/ambiguities/options |
| Clarify | Applies human scope choice (LLM can refine feature flags) |
| Decompose | LLM builds task graph |
| Design | LLM architecture/API design; wait for approval |
| **Implement** | **LLM generates project files into `workspace/`** (template gap-fill if needed) |
| Test | pytest on generated app; LLM repair pass if tests fail |
| Document | LLM engineering outcome markdown |
| SecurityReview | LLM review + hard validation gates |
| ReleaseReady | Checklist + human release sign-off |

## Evidence per run (`runs/<run_id>/`)

- `state.json` — full orchestration state  
- `01_requirements.json` … `09_release.md` — stage artifacts  
- `llm_calls.jsonl` — OpenAI call trace (prompts/usage previews)  
- `audit.jsonl` — event trace  
- `metrics.json` — latency, retries, rollbacks, files generated  
- `decision_lineage.md` — decision history  

## Docs

- Flow + execution guide: [`docs/flow-and-execution.html`](docs/flow-and-execution.html)
- Engineering summary: [`ENGINEERING_SUMMARY.md`](ENGINEERING_SUMMARY.md)

## Principle

Agents execute multi-step SDLC work; humans approve scope, design, and release.