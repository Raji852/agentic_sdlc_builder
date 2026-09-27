from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pipeline.state import RunState, utcnow


class AuditLog:
    def __init__(self, run: RunState):
        self.run = run
        self.path = run.run_dir / "audit.jsonl"

    def emit(self, event_type: str, **payload: Any) -> None:
        rec = {"at": utcnow(), "event": event_type, "run_id": self.run.run_id, **payload}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")

    def finalize(self, success: bool) -> dict[str, Any]:
        started = datetime.fromisoformat(self.run.metrics["started_at"])
        ended = datetime.fromisoformat(utcnow())
        self.run.metrics.update(
            {
                "ended_at": ended.isoformat(),
                "success": success,
                "latency_ms": int((ended - started).total_seconds() * 1000),
                "retry_frequency": self.run.metrics.get("retries", 0),
                "rollback_frequency": self.run.metrics.get("rollbacks", 0),
            }
        )
        (self.run.run_dir / "metrics.json").write_text(json.dumps(self.run.metrics, indent=2), encoding="utf-8")
        lineage = [f"# Decision Lineage — {self.run.run_id}", ""]
        for d in self.run.decisions:
            lineage.append(f"- `{d.at}` | **{d.stage}** | {d.decision} — {d.rationale} ({d.actor})")
        (self.run.run_dir / "decision_lineage.md").write_text("\n".join(lineage) + "\n", encoding="utf-8")
        self.emit("metrics_finalized", success=success)
        return self.run.metrics