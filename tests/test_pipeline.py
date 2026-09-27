from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["AGENT_MODE"] = "mock"

from pipeline.engine import AgenticPipeline
from pipeline.state import RunStatus


def test_greenfield_generates_project():
    pipeline = AgenticPipeline(auto_approve=True)
    run = pipeline.start(
        "Build a URL shortener with analytics, health checks, validation, and custom aliases",
        scenario="greenfield",
    )
    assert run.status == RunStatus.COMPLETED
    assert run.context["scenario"] == "greenfield"
    project = Path(run.context["project_path"])
    assert (project / "app" / "main.py").exists()
    assert run.context["test_report"]["passed"] is True


def test_brownfield_enhances_baseline():
    pipeline = AgenticPipeline(auto_approve=True)
    run = pipeline.start(
        "Enhance existing shortener with custom aliases and rate limits",
        scenario="brownfield",
    )
    assert run.status == RunStatus.COMPLETED
    assert run.context["scenario"] == "brownfield"
    models = (Path(run.context["project_path"]) / "app" / "models.py").read_text(encoding="utf-8")
    assert "custom_alias" in models
    assert run.context.get("impacted_modules")


def test_ambiguous_requires_or_completes_with_approvals():
    pipeline = AgenticPipeline(auto_approve=False)
    run = pipeline.start(
        "Make it enterprise ready and better",
        scenario="ambiguous",
    )
    assert run.status == RunStatus.WAITING_APPROVAL
    assert run.context.get("ambiguities")

    run = pipeline.resume(run, {"scope_approval": {"approved": True, "choice": "A"}})
    if run.status == RunStatus.WAITING_APPROVAL:
        run = pipeline.resume(run, {"design_approval": {"approved": True}})
    if run.status == RunStatus.WAITING_APPROVAL:
        run = pipeline.resume(run, {"release_approval": {"approved": True}})
    assert run.status == RunStatus.COMPLETED


def test_test_docs_improves_baseline():
    pipeline = AgenticPipeline(auto_approve=True)
    run = pipeline.start(
        "Improve tests and documentation",
        scenario="test_docs",
    )
    assert run.status == RunStatus.COMPLETED
    project = Path(run.context["project_path"])
    readme = (project / "README.md").read_text(encoding="utf-8")
    assert "API" in readme or "Run" in readme or "runbook" in readme.lower() or "Improved" in readme
    assert run.context["test_report"]["passed"] is True
