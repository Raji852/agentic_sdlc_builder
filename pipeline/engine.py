from __future__ import annotations

import os
import shutil
import time
from typing import Any

from pipeline.agents.stages import STAGE_HANDLERS
from pipeline.graph import SDLC_GRAPH, ordered_nodes
from pipeline.observability import AuditLog
from pipeline.policies import check_release, check_requirement
from pipeline.state import NodeStatus, RunState, RunStatus, utcnow


class AgenticPipeline:
    """Stateful agentic SDLC runner that generates a working product from a requirement."""

    def __init__(self, auto_approve: bool | None = None, max_retries: int | None = None):
        env_auto = os.getenv("AUTO_APPROVE", "false").lower() in {"1", "true", "yes"}
        self.auto_approve = env_auto if auto_approve is None else auto_approve
        self.max_retries = max_retries if max_retries is not None else int(os.getenv("MAX_RETRIES", "2"))

    def start(
        self,
        requirement: str,
        *,
        scenario: str = "greenfield",
        base_project: str | None = None,
    ) -> RunState:
        from pipeline.scenarios import SCENARIOS, seed_baseline_project

        if scenario not in SCENARIOS:
            raise ValueError(f"Unknown scenario '{scenario}'. Choose from {SCENARIOS}")
        ok, reason = check_requirement(requirement)
        if not ok:
            raise ValueError(reason)
        run = RunState.create(requirement, ordered_nodes(), scenario=scenario)
        audit = AuditLog(run)
        audit.emit("run_created", requirement=requirement, scenario=scenario)
        if scenario in {"brownfield", "test_docs"}:
            seed_baseline_project(run, base_project=base_project)
            audit.emit("baseline_seeded", project=run.context.get("project_path"), source=run.context.get("baseline_source"))
        run.status = RunStatus.RUNNING
        run.save()
        return self._loop(run, audit)

    def resume(self, run: RunState, approvals: dict[str, Any] | None = None) -> RunState:
        audit = AuditLog(run)
        if approvals:
            for name, payload in approvals.items():
                run.approvals[name] = {**payload, "at": utcnow()}
                run.decide(name, "approved", payload.get("rationale", "approved"), actor="human")
                audit.emit("approval_granted", approval=name, payload=payload)

        for node_name, node in run.nodes.items():
            if node.status != NodeStatus.WAITING_APPROVAL:
                continue
            required = SDLC_GRAPH[node_name].requires_approval
            if required and required in run.approvals:
                if node_name == "Clarify":
                    STAGE_HANDLERS["Clarify"](run)
                node.status = NodeStatus.PASSED
                node.finished_at = utcnow()
                audit.emit("node_passed_after_approval", node=node_name)

        run.status = RunStatus.RUNNING
        run.save()
        return self._loop(run, audit)

    def retest(
        self,
        run: RunState,
        *,
        repair: bool = False,
        continue_pipeline: bool = False,
    ) -> RunState:
        """Re-run pytest for an existing run's project without rebuilding earlier stages.

        repair=True uses the Test stage (LLM repair + template fallback).
        continue_pipeline=True continues SecurityReview/ReleaseReady after tests pass.
        """
        from pathlib import Path

        from pipeline.agents.stages import test_stage

        audit = AuditLog(run)
        project = Path(run.context.get("project_path") or run.project_dir)
        if not project.exists():
            raise FileNotFoundError(
                f"Project folder missing for run {run.run_id}: {project}\n"
                "This run may have been rolled back. Re-run: "
                "python -m pipeline build --scenario test_docs --auto-approve"
            )

        audit.emit("retest_started", project=str(project), repair=repair)
        node = run.nodes["Test"]
        node.status = NodeStatus.RUNNING
        node.error = None
        node.attempts = max(node.attempts, 1)
        node.started_at = utcnow()
        run.status = RunStatus.RUNNING
        run.save()

        try:
            if repair:
                result = test_stage(run)
                node.artifact = result.get("artifact")
            else:
                import subprocess
                import sys

                proc = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q"],
                    cwd=str(project),
                    capture_output=True,
                    text=True,
                )
                report = {
                    "command": "pytest -q",
                    "cwd": str(project),
                    "returncode": proc.returncode,
                    "passed": proc.returncode == 0,
                    "stdout": proc.stdout[-4000:],
                    "stderr": proc.stderr[-2000:],
                    "retest_only": True,
                }
                run.context["test_report"] = report
                path = run.run_dir / "06_test.json"
                path.write_text(__import__("json").dumps(report, indent=2), encoding="utf-8")
                node.artifact = str(path)
                if not report["passed"]:
                    raise RuntimeError(
                        f"Tests failed:\n{report['stdout']}\n{report['stderr']}"
                    )

            node.status = NodeStatus.PASSED
            node.finished_at = utcnow()
            node.error = None
            run.decide("Test", "retest_passed", "Retest succeeded for existing run")
            audit.emit("retest_passed", project=str(project))
        except Exception as exc:  # noqa: BLE001
            node.status = NodeStatus.FAILED
            node.error = str(exc)
            node.finished_at = utcnow()
            run.status = RunStatus.FAILED
            run.decide("Test", "retest_failed", str(exc))
            audit.emit("retest_failed", error=str(exc))
            run.save()
            return run

        if not continue_pipeline:
            # Tests-only mode: do not advance later stages
            run.status = RunStatus.RUNNING
            run.save()
            return run

        # Reset downstream unfinished nodes and continue orchestration
        for name in ("SecurityReview", "ReleaseReady"):
            if run.nodes[name].status != NodeStatus.PASSED:
                run.nodes[name].status = NodeStatus.PENDING
                run.nodes[name].error = None
                run.nodes[name].attempts = 0
        # Drop stale release approval so ReleaseReady gate runs again if needed
        if run.nodes["ReleaseReady"].status != NodeStatus.PASSED:
            run.approvals.pop("release_approval", None)
        run.status = RunStatus.RUNNING
        run.save()
        audit.emit("retest_continue", next_nodes=["SecurityReview", "ReleaseReady"])
        return self._loop(run, audit)

    def _loop(self, run: RunState, audit: AuditLog) -> RunState:
        active = set(run.nodes)
        while True:
            if run.status in {RunStatus.WAITING_APPROVAL, RunStatus.FAILED, RunStatus.SAFE_STOPPED}:
                break

            ready = self._ready(run, active)
            if not ready:
                terminal = {NodeStatus.PASSED, NodeStatus.SKIPPED}
                if all(run.nodes[n].status in terminal for n in active) and "release_approval" in run.approvals:
                    ok, reason = check_release(run.context)
                    if not ok:
                        run.status = RunStatus.FAILED
                        audit.emit("release_policy_failed", reason=reason)
                        audit.finalize(False)
                    else:
                        run.status = RunStatus.COMPLETED
                        run.context["release_ready"] = True
                        audit.finalize(True)
                        audit.emit("run_completed", project=run.context.get("project_path"))
                    run.save()
                elif any(run.nodes[n].status == NodeStatus.WAITING_APPROVAL for n in active):
                    run.status = RunStatus.WAITING_APPROVAL
                    run.save()
                elif any(run.nodes[n].status == NodeStatus.FAILED for n in active):
                    run.status = RunStatus.FAILED
                    audit.finalize(False)
                    run.save()
                else:
                    run.status = RunStatus.SAFE_STOPPED
                    run.decide("Engine", "safe_stop", "No ready nodes; unresolved work")
                    audit.finalize(False)
                    run.save()
                break

            # Execute non-parallel nodes sequentially; parallel_group together
            groups: dict[str | None, list[str]] = {}
            for name in ready:
                groups.setdefault(SDLC_GRAPH[name].parallel_group, []).append(name)

            for group, names in groups.items():
                for name in sorted(names):
                    outcome = self._run_node(run, name, audit)
                    if outcome in {"wait", "safe_stop", "failed_terminal"}:
                        return run
        run.save()
        return run

    def _ready(self, run: RunState, active: set[str]) -> list[str]:
        ready: list[str] = []
        for name in active:
            node = run.nodes[name]
            if node.status not in {NodeStatus.PENDING}:
                continue
            deps = SDLC_GRAPH[name].depends_on
            if not all(run.nodes[d].status in {NodeStatus.PASSED, NodeStatus.SKIPPED} for d in deps if d in active):
                continue
            # Skip Clarify approval friction when no ambiguities — still run once for default scope
            ready.append(name)
        return sorted(ready)

    def _run_node(self, run: RunState, name: str, audit: AuditLog) -> str:
        spec = SDLC_GRAPH[name]
        node = run.nodes[name]
        handler = STAGE_HANDLERS[name]

        node.status = NodeStatus.RUNNING
        node.started_at = utcnow()
        node.attempts += 1
        audit.emit("node_started", node=name, attempt=node.attempts)
        run.save()

        t0 = time.perf_counter()
        try:
            result = handler(run)
            node.artifact = result.get("artifact")
            node.finished_at = utcnow()
            audit.emit("node_finished", node=name, ms=int((time.perf_counter() - t0) * 1000))

            needs = result.get("needs_approval") or spec.requires_approval
            if needs and needs not in run.approvals:
                if self.auto_approve:
                    payload = {"approved": True, "rationale": "AUTO_APPROVE", "actor": "auto"}
                    if needs == "scope_approval":
                        payload["choice"] = "A"
                    run.approvals[needs] = {**payload, "at": utcnow()}
                    run.decide(needs, "auto_approved", "Auto-approved for demo", actor="auto")
                    # Re-apply clarify with chosen default
                    if name == "Clarify":
                        STAGE_HANDLERS["Clarify"](run)
                    audit.emit("approval_auto", approval=needs)
                else:
                    node.status = NodeStatus.WAITING_APPROVAL
                    run.status = RunStatus.WAITING_APPROVAL
                    audit.emit("approval_required", node=name, approval=needs)
                    run.save()
                    return "wait"

            node.status = NodeStatus.PASSED
            audit.emit("node_passed", node=name)
            run.save()
            return "ok"

        except Exception as exc:  # noqa: BLE001
            node.error = str(exc)
            node.finished_at = utcnow()
            audit.emit("node_failed", node=name, error=str(exc), attempt=node.attempts)
            max_attempts = min(spec.max_retries, self.max_retries) + 1
            if node.attempts < max_attempts:
                run.metrics["retries"] = run.metrics.get("retries", 0) + 1
                node.status = NodeStatus.PENDING
                run.decide(name, "retry", f"Retry after failure: {exc}")
                run.save()
                return "retry"

            return self._rollback(run, name, audit, str(exc))

    def _rollback(self, run: RunState, failed: str, audit: AuditLog, error: str) -> str:
        stack = run.context.get("rollback_stack", [])
        marker = stack.pop() if stack else None
        run.context["rollback_stack"] = stack
        from pathlib import Path

        if marker and marker.get("action") == "delete_project":
            path = marker.get("path")
            if path and Path(path).exists():
                shutil.rmtree(path, ignore_errors=True)
        if marker and marker.get("action") == "restore_snapshot":
            path = Path(marker["path"])
            snap = Path(marker["snapshot"])
            if snap.exists():
                if path.exists():
                    shutil.rmtree(path, ignore_errors=True)
                shutil.copytree(snap, path)
        run.metrics["rollbacks"] = run.metrics.get("rollbacks", 0) + 1
        run.nodes[failed].status = NodeStatus.ROLLED_BACK
        run.status = RunStatus.SAFE_STOPPED
        run.decide(failed, "safe_stop", f"Retries exhausted; rolled back. error={error}")
        audit.emit("rollback_safe_stop", failed=failed, marker=marker, error=error)
        audit.finalize(False)
        run.save()
        return "safe_stop"