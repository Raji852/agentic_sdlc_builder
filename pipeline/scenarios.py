from __future__ import annotations

"""Assignment scope scenarios: greenfield, brownfield, ambiguous, test_docs."""

import shutil
from pathlib import Path
from typing import Any

from pipeline.codegen.generator import generate_url_shortener
from pipeline.state import WORKSPACE, RunState

SCENARIOS = ("greenfield", "brownfield", "ambiguous", "test_docs")

DEFAULT_REQUIREMENTS: dict[str, str] = {
    "greenfield": (
        "Build a URL shortener service from scratch with core APIs for shortening and redirect, "
        "click analytics, reliability features including URL validation and health checks, "
        "and support for custom aliases."
    ),
    "brownfield": (
        "Enhance the existing URL shortener codebase: add custom aliases and per-link "
        "rate-limit metadata, update APIs/schemas, and ensure regression tests cover the changes. "
        "Perform impact analysis before modifying modules."
    ),
    "ambiguous": (
        "Make the URL shortener enterprise ready and better overall."
    ),
    "test_docs": (
        "Improve the existing URL shortener by expanding automated test coverage "
        "(edge cases, validation failures, analytics) and upgrading documentation "
        "(README runbook, API examples, limitations)."
    ),
}

SCENARIO_META: dict[str, dict[str, Any]] = {
    "greenfield": {
        "title": "Greenfield — new system",
        "scope": "New system/features from a well-defined requirement",
        "mode": "create",
    },
    "brownfield": {
        "title": "Brownfield — enhance existing system",
        "scope": "Enhancements / refactors / bug-fix style change on an existing codebase",
        "mode": "enhance",
    },
    "ambiguous": {
        "title": "Ambiguous requirements",
        "scope": "Vague ask; clarify options then deliver a bounded slice",
        "mode": "create",
    },
    "test_docs": {
        "title": "Test & documentation improvements",
        "scope": "Improve tests and docs on an existing baseline system",
        "mode": "enhance",
    },
}


def resolve_requirement(scenario: str, requirement: str | None, requirement_file: str | None) -> str:
    if requirement_file:
        return Path(requirement_file).read_text(encoding="utf-8").strip()
    if requirement:
        return requirement.strip()
    return DEFAULT_REQUIREMENTS[scenario]


def seed_baseline_project(run: RunState, base_project: str | None = None) -> Path:
    """Ensure an existing codebase exists for brownfield / test_docs scenarios."""
    project_dir = run.project_dir

    if base_project:
        src = Path(base_project)
        if not src.exists():
            raise FileNotFoundError(f"Base project not found: {src}")
        if project_dir.exists():
            shutil.rmtree(project_dir)
        shutil.copytree(src, project_dir)
        run.context["baseline_source"] = str(src.resolve())
        run.decide("SeedBaseline", "copy_base_project", f"Copied existing project from {src}")
    else:
        # Deterministic MVP without alias/rate-limit — room for brownfield enhancements
        if project_dir.exists():
            shutil.rmtree(project_dir)
        project_dir.mkdir(parents=True, exist_ok=True)
        baseline_spec = {
            "app_name": "Baseline URL Shortener",
            "normalized_requirement": "MVP shortener with create/redirect/analytics/health",
            "features": {
                "shorten_api": True,
                "redirect": True,
                "analytics": True,
                "health_check": True,
                "url_validation": True,
                "custom_alias": False,
                "rate_limit": False,
            },
        }
        files = generate_url_shortener(project_dir, baseline_spec)
        # Make docs intentionally thinner for test_docs scenario demos
        if run.context.get("scenario") == "test_docs":
            thin = (
                "# Baseline URL Shortener\n\n"
                "Minimal README. Needs better runbook, API examples, and limitations.\n\n"
                "Run: `uvicorn app.main:app --reload`\n"
            )
            (project_dir / "README.md").write_text(thin, encoding="utf-8")
            # Keep only a smoke test to show "improvement" opportunity
            smoke = '''from __future__ import annotations
import sys
from pathlib import Path
from fastapi.testclient import TestClient
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.database import Base, engine, init_db
from app.main import app

def setup_module():
    Base.metadata.drop_all(bind=engine)
    init_db()

client = TestClient(app)

def test_health():
    assert client.get("/health").json()["status"] == "ok"
'''
            (project_dir / "tests" / "test_app.py").write_text(smoke, encoding="utf-8")
        run.context["baseline_source"] = "seeded_mvp_template"
        run.context["baseline_files"] = files
        run.decide("SeedBaseline", "seed_mvp", f"Seeded baseline MVP with {len(files)} files")

    run.context["project_path"] = str(project_dir)
    run.context["existing_files"] = _list_files(project_dir)
    # Snapshot for rollback
    snapshot = WORKSPACE / f".snapshot_{run.run_id}"
    if snapshot.exists():
        shutil.rmtree(snapshot)
    shutil.copytree(project_dir, snapshot)
    run.context.setdefault("rollback_stack", []).append(
        {"action": "restore_snapshot", "path": str(project_dir), "snapshot": str(snapshot)}
    )
    return project_dir


def _list_files(project_dir: Path) -> list[str]:
    return sorted(
        str(p.relative_to(project_dir)).replace("\\", "/")
        for p in project_dir.rglob("*")
        if p.is_file() and ".snapshot" not in p.parts
    )


def read_project_files(project_dir: Path, limit_chars: int = 6000) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in _list_files(project_dir):
        if not rel.endswith((".py", ".md", ".txt")):
            continue
        text = (project_dir / rel).read_text(encoding="utf-8")
        out[rel] = text[:limit_chars]
    return out
