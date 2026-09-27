# Engineering Summary — Agentic SDLC Builder

## What this is
An agentic pipeline that transforms a natural-language requirement into a **generated, testable URL shortener** under human approval gates.

## Why this matches the assignment
- Requirement understanding + ambiguity handling  
- Task decomposition with dependencies  
- Non-linear stateful orchestration (parallel Document/Security after Implement/Test)  
- **Implementation agent writes real code** into `workspace/`  
- Validation via pytest on generated output  
- Policy guardrails, retries, rollback/safe-stop  
- Audit trail, metrics, decision lineage  
- Human approvals for scope, design, release  

## LLM usage
- Provider: **OpenAI**
- Model: **`gpt-4o-mini`** (`OPENAI_MODEL`, overridable)
- Key: `OPENAI_API_KEY` in local `.env` (never commit)
- Mode: `AGENT_MODE=openai` for live runs; `mock` for offline/unit tests
- Trace: each call logged to `runs/<id>/llm_calls.jsonl`

## Trade-offs
| Choice | Trade-off |
|---|---|
| OpenAI gpt-4o-mini for stage agents | Cheap/fast; less capable than larger models for huge codegen |
| Template gap-fill if LLM omits files | Higher reliability for demo; hybrid not “pure LLM only” |
| LLM test-repair loop (one pass) | Can fix flaky codegen; bounded to avoid infinite spend |
| SQLite target app | Perfect for prototype; not multi-node HA |

## Limitations
- Requires a valid OpenAI API key for real agentic runs  
- Rollback deletes generated project folder; not git-based  
- Rate-limit is feature-flagged metadata when requested  

## Autonomy boundaries
- **Agents may:** parse requirements, design, generate code/tests/docs, run tests, security scan  
- **Humans approve:** scope choice, design, release readiness