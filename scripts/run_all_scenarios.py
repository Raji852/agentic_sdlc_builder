from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Default to mock for offline/CI; set AGENT_MODE=openai in env for live LLM.
os.environ.setdefault("AGENT_MODE", "mock")

from pipeline.engine import AgenticPipeline
from pipeline.scenarios import DEFAULT_REQUIREMENTS, SCENARIOS


def main() -> int:
    pipeline = AgenticPipeline(auto_approve=True)
    results = []
    for scenario in SCENARIOS:
        run = pipeline.start(DEFAULT_REQUIREMENTS[scenario], scenario=scenario)
        results.append(
            {
                "scenario": scenario,
                "run_id": run.run_id,
                "status": run.status.value,
                "project_path": run.context.get("project_path"),
                "implement_source": run.context.get("implement_source"),
            }
        )
    print(json.dumps(results, indent=2))
    return 0 if all(r["status"] == "completed" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())