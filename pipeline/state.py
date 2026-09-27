from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
WORKSPACE = ROOT / "workspace"
RUNS.mkdir(parents=True, exist_ok=True)
WORKSPACE.mkdir(parents=True, exist_ok=True)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"


class RunStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    SAFE_STOPPED = "safe_stopped"


@dataclass
class Decision:
    at: str
    stage: str
    decision: str
    rationale: str
    actor: str = "agent"


@dataclass
class NodeState:
    name: str
    status: NodeStatus = NodeStatus.PENDING
    attempts: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    artifact: str | None = None
    error: str | None = None


@dataclass
class RunState:
    run_id: str
    requirement: str
    status: RunStatus = RunStatus.CREATED
    created_at: str = field(default_factory=utcnow)
    updated_at: str = field(default_factory=utcnow)
    nodes: dict[str, NodeState] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    decisions: list[Decision] = field(default_factory=list)
    approvals: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def run_dir(self) -> Path:
        path = RUNS / self.run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def project_dir(self) -> Path:
        """Where agents write the generated URL shortener."""
        name = self.context.get("project_name", f"url_shortener_{self.run_id}")
        path = WORKSPACE / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def touch(self) -> None:
        self.updated_at = utcnow()

    def decide(self, stage: str, decision: str, rationale: str, actor: str = "agent") -> None:
        self.decisions.append(Decision(utcnow(), stage, decision, rationale, actor))
        self.touch()

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "requirement": self.requirement,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "nodes": {k: {**asdict(v), "status": v.status.value} for k, v in self.nodes.items()},
            "context": self.context,
            "decisions": [asdict(d) for d in self.decisions],
            "approvals": self.approvals,
            "metrics": self.metrics,
            "project_dir": str(self.project_dir),
        }

    def save(self) -> Path:
        path = self.run_dir / "state.json"
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path

    @classmethod
    def create(
        cls,
        requirement: str,
        node_names: list[str],
        *,
        scenario: str = "greenfield",
    ) -> "RunState":
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        state = cls(
            run_id=run_id,
            requirement=requirement,
            nodes={n: NodeState(name=n) for n in node_names},
            context={
                "requirement_raw": requirement,
                "scenario": scenario,
                "project_name": f"url_shortener_{scenario}_{run_id}",
                "features": {},
                "spec": {},
                "design": {},
                "generated_files": [],
                "test_report": {},
                "docs_path": None,
                "release_ready": False,
                "rollback_stack": [],
            },
            metrics={
                "started_at": utcnow(),
                "ended_at": None,
                "retries": 0,
                "rollbacks": 0,
                "success": False,
                "latency_ms": None,
                "files_generated": 0,
            },
        )
        state.save()
        return state

    @classmethod
    def load(cls, run_id: str) -> "RunState":
        data = json.loads((RUNS / run_id / "state.json").read_text(encoding="utf-8"))
        nodes = {
            k: NodeState(
                name=v["name"],
                status=NodeStatus(v["status"]),
                attempts=v.get("attempts", 0),
                started_at=v.get("started_at"),
                finished_at=v.get("finished_at"),
                artifact=v.get("artifact"),
                error=v.get("error"),
            )
            for k, v in data["nodes"].items()
        }
        return cls(
            run_id=data["run_id"],
            requirement=data["requirement"],
            status=RunStatus(data["status"]),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            nodes=nodes,
            context=data.get("context", {}),
            decisions=[Decision(**d) for d in data.get("decisions", [])],
            approvals=data.get("approvals", {}),
            metrics=data.get("metrics", {}),
        )