from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from pipeline.codegen.generator import generate_url_shortener
from pipeline.llm import LLMError, agent_mode, chat_json, chat_text
from pipeline.state import RunState

Handler = Callable[[RunState], dict[str, Any]]

REQUIRED_PROJECT_FILES = [
    "requirements.txt",
    "app/__init__.py",
    "app/main.py",
    "app/database.py",
    "app/models.py",
    "app/schemas.py",
    "app/services.py",
    "tests/test_app.py",
]


def _write_artifact(run: RunState, name: str, content: str) -> str:
    path = run.run_dir / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def _use_llm() -> bool:
    return agent_mode() == "openai"


# ---------------------------------------------------------------------------
# GatherRequirements
# ---------------------------------------------------------------------------

def gather_requirements(run: RunState) -> dict[str, Any]:
    raw = run.requirement
    scenario = run.context.get("scenario", "greenfield")
    if _use_llm():
        try:
            data = chat_json(
                system=(
                    "You are a senior requirements analyst agent in an agentic SDLC pipeline. "
                    "Return ONLY JSON with keys: normalized_requirement (str), "
                    "features (object of booleans: shorten_api, redirect, analytics, health_check, "
                    "url_validation, custom_alias, rate_limit), ambiguities (string array), "
                    "assumptions (string array), options (array of {id,title,includes,deferred?}), "
                    "impacted_modules (string array, for brownfield/test_docs), "
                    "app_name (str), rationale (str). "
                    "Always enable analytics, health_check, url_validation, shorten_api, redirect. "
                    "Scenario hints: greenfield=new system; brownfield=enhance existing "
                    "(prefer custom_alias+rate_limit true); ambiguous=MUST populate ambiguities "
                    "and options A/B/C with C deferred; test_docs=focus on tests+docs improvements "
                    "(custom_alias may stay false)."
                ),
                user=json.dumps({"scenario": scenario, "requirement": raw, "existing_files": run.context.get("existing_files", [])}),
                run_dir=run.run_dir,
                stage="GatherRequirements",
            )
            spec = _normalize_spec(raw, data, scenario=scenario)
            run.decide("GatherRequirements", "llm_normalize", data.get("rationale", "LLM normalized requirement"))
        except LLMError as exc:
            spec = _mock_gather(raw, scenario=scenario)
            run.decide("GatherRequirements", "fallback_mock", f"LLM unavailable: {exc}")
    else:
        spec = _mock_gather(raw, scenario=scenario)
        run.decide("GatherRequirements", "mock_normalize", f"Mock gather for scenario={scenario}")

    run.context["spec"] = spec
    run.context["features"] = spec["features"]
    run.context["ambiguities"] = spec["ambiguities"]
    run.context["options"] = spec["options"]
    run.context["impacted_modules"] = spec.get("impacted_modules", [])
    run.context["llm_mode"] = agent_mode()
    path = _write_artifact(run, "01_requirements.json", json.dumps(spec, indent=2))
    return {"artifact": path}


def _normalize_spec(raw: str, data: dict[str, Any], scenario: str = "greenfield") -> dict[str, Any]:
    features = {
        "shorten_api": True,
        "redirect": True,
        "analytics": True,
        "health_check": True,
        "url_validation": True,
        "custom_alias": bool(data.get("features", {}).get("custom_alias", False)),
        "rate_limit": bool(data.get("features", {}).get("rate_limit", False)),
    }
    if scenario == "brownfield":
        features["custom_alias"] = True
        features["rate_limit"] = True
    if scenario == "test_docs":
        features["custom_alias"] = bool(features.get("custom_alias", False))
        features["rate_limit"] = bool(features.get("rate_limit", False))
    ambiguities = list(data.get("ambiguities") or [])
    if scenario == "ambiguous" and not ambiguities:
        ambiguities = ["Business priority underspecified", "Non-functional targets unclear"]
    options = data.get("options") or [{"id": "A", "title": "As specified", "includes": [k for k, v in features.items() if v]}]
    if scenario == "ambiguous" and len(options) < 2:
        options = [
            {"id": "A", "title": "MVP reliability slice", "includes": ["analytics", "validation", "health"]},
            {"id": "B", "title": "Growth slice", "includes": ["analytics", "custom_alias"]},
            {"id": "C", "title": "Full enterprise", "includes": ["sso", "multi-region"], "deferred": True},
        ]
    impacted = data.get("impacted_modules") or []
    if scenario in {"brownfield", "test_docs"} and not impacted:
        impacted = ["app/models.py", "app/services.py", "app/schemas.py", "app/main.py", "tests/", "README.md"]
    return {
        "raw": raw,
        "scenario": scenario,
        "normalized_requirement": data.get("normalized_requirement") or raw,
        "features": features,
        "ambiguities": ambiguities,
        "assumptions": data.get("assumptions")
        or [
            "Python + FastAPI stack",
            "SQLite for local prototype persistence",
            "No multi-tenant auth in MVP",
        ],
        "options": options,
        "impacted_modules": impacted,
        "app_name": data.get("app_name") or "Agent-Built URL Shortener",
        "llm": data.get("_llm"),
    }


def _mock_gather(raw: str, scenario: str = "greenfield") -> dict[str, Any]:
    lowered = raw.lower()
    features = {
        "shorten_api": True,
        "redirect": True,
        "analytics": True,
        "health_check": True,
        "url_validation": True,
        "custom_alias": any(k in lowered for k in ("alias", "custom", "vanity")),
        "rate_limit": any(k in lowered for k in ("rate limit", "throttle", "reliability")),
    }
    if scenario == "brownfield":
        features["custom_alias"] = True
        features["rate_limit"] = True
    if scenario == "test_docs":
        features["custom_alias"] = False
        features["rate_limit"] = False

    ambiguities = [f"Ambiguous phrase detected: '{w}'" for w in ("enterprise", "better", "improve", "scale") if w in lowered]
    if scenario == "ambiguous" and not ambiguities:
        ambiguities = ["Ambiguous phrase detected: 'enterprise ready'", "Ambiguous phrase detected: 'better'"]

    if ambiguities or scenario == "ambiguous":
        options = [
            {"id": "A", "title": "MVP reliability slice", "includes": ["analytics", "validation", "health"]},
            {"id": "B", "title": "Growth slice", "includes": ["analytics", "custom_alias"]},
            {"id": "C", "title": "Full enterprise", "includes": ["sso", "multi-region"], "deferred": True},
        ]
    else:
        options = [{"id": "A", "title": "As specified", "includes": [k for k, v in features.items() if v]}]

    if scenario == "greenfield":
        normalized = "Build a URL shortener with create/redirect APIs, click analytics, health checks, and URL validation"
        if features["custom_alias"]:
            normalized += ", custom aliases"
        if features["rate_limit"]:
            normalized += ", rate-limit metadata"
    elif scenario == "brownfield":
        normalized = (
            "Enhance existing shortener with custom aliases + rate-limit metadata, "
            "update APIs, and add regression tests"
        )
    elif scenario == "test_docs":
        normalized = "Improve automated tests (edge cases/validation/analytics) and upgrade README/runbook docs"
    else:
        normalized = (
            "Clarify and deliver a bounded enterprise-readiness slice: validation, health, analytics, docs"
        )

    impacted = []
    if scenario in {"brownfield", "test_docs"}:
        impacted = ["app/models.py", "app/services.py", "app/schemas.py", "app/main.py", "tests/test_app.py", "README.md"]

    return {
        "raw": raw,
        "scenario": scenario,
        "normalized_requirement": normalized,
        "features": features,
        "ambiguities": ambiguities,
        "assumptions": [
            "Python + FastAPI stack",
            "SQLite for local prototype persistence",
            "No multi-tenant auth in MVP",
            f"Scenario mode: {scenario}",
        ],
        "options": options,
        "impacted_modules": impacted,
        "app_name": "Agent-Built URL Shortener",
        "llm": {"mode": "mock"},
    }


# ---------------------------------------------------------------------------
# Clarify / Decompose / Design
# ---------------------------------------------------------------------------

def clarify(run: RunState) -> dict[str, Any]:
    options = run.context.get("options", [])
    choice = run.approvals.get("scope_approval", {}).get("choice", "A")
    selected = next((o for o in options if o["id"] == choice), options[0] if options else {"id": "A"})
    if selected.get("deferred"):
        raise RuntimeError("Option C (full enterprise) is out of prototype bounds — choose A or B")

    features = dict(run.context.get("features", {}))
    if _use_llm() and "scope_approval" in run.approvals:
        try:
            data = chat_json(
                system=(
                    "You are a scope clarification agent. Given features and a chosen option, "
                    "return JSON: features (updated booleans), rationale (str). "
                    "Keep shorten_api, redirect, analytics, health_check, url_validation true."
                ),
                user=json.dumps({"choice": choice, "selected": selected, "features": features}),
                run_dir=run.run_dir,
                stage="Clarify",
            )
            for key in ("custom_alias", "rate_limit"):
                if key in data.get("features", {}):
                    features[key] = bool(data["features"][key])
            run.decide("Clarify", "llm_scope", data.get("rationale", "LLM applied scope choice"))
        except LLMError as exc:
            features = _apply_choice(features, choice)
            run.decide("Clarify", "fallback_scope", str(exc))
    else:
        features = _apply_choice(features, choice)
        run.decide(
            "Clarify",
            "scope_selected",
            f"Selected option {selected.get('id')}",
            actor="human" if "scope_approval" in run.approvals else "agent-default",
        )

    run.context["features"] = features
    run.context["chosen_option"] = selected
    run.context["spec"]["features"] = features
    run.context["spec"]["chosen_option"] = selected
    path = _write_artifact(
        run,
        "02_clarify.json",
        json.dumps({"chosen": selected, "features": features, "llm_mode": agent_mode()}, indent=2),
    )
    return {"artifact": path, "needs_approval": "scope_approval"}


def _apply_choice(features: dict[str, Any], choice: str) -> dict[str, Any]:
    features = dict(features)
    if choice == "B":
        features["custom_alias"] = True
    return features


def decompose(run: RunState) -> dict[str, Any]:
    scenario = run.context.get("scenario", "greenfield")
    if _use_llm():
        try:
            data = chat_json(
                system=(
                    "You are a task decomposition agent. Return JSON with key tasks: "
                    "array of {id,title,depends_on:string[],impacted?:string[]}. "
                    "For brownfield/test_docs include an impact-analysis task first. 5-8 tasks."
                ),
                user=json.dumps(
                    {
                        "scenario": scenario,
                        "requirement": run.context.get("spec", {}).get("normalized_requirement"),
                        "features": run.context.get("features"),
                        "impacted_modules": run.context.get("impacted_modules"),
                    }
                ),
                run_dir=run.run_dir,
                stage="Decompose",
            )
            tasks = data.get("tasks") or []
            if not tasks:
                raise LLMError("Empty task list from LLM")
            run.decide("Decompose", "llm_task_graph", f"{len(tasks)} tasks from LLM")
        except LLMError as exc:
            tasks = _mock_tasks(scenario)
            run.decide("Decompose", "fallback_tasks", str(exc))
    else:
        tasks = _mock_tasks(scenario)
        run.decide("Decompose", "mock_tasks", f"{len(tasks)} mock tasks for {scenario}")

    run.context["task_graph"] = tasks
    path = _write_artifact(
        run,
        "03_decompose.json",
        json.dumps(
            {
                "scenario": scenario,
                "tasks": tasks,
                "impacted_modules": run.context.get("impacted_modules", []),
                "llm_mode": agent_mode(),
            },
            indent=2,
        ),
    )
    return {"artifact": path}


def _mock_tasks(scenario: str = "greenfield") -> list[dict[str, Any]]:
    if scenario == "brownfield":
        return [
            {"id": "T0", "title": "Impact analysis on existing modules/APIs/data flows", "depends_on": [], "impacted": ["app/", "tests/"]},
            {"id": "T1", "title": "Design alias + rate-limit change set", "depends_on": ["T0"]},
            {"id": "T2", "title": "Implement model/schema/service/API updates", "depends_on": ["T1"]},
            {"id": "T3", "title": "Add/adjust regression tests", "depends_on": ["T2"]},
            {"id": "T4", "title": "Update docs for new fields", "depends_on": ["T2"]},
            {"id": "T5", "title": "Run tests + security review", "depends_on": ["T3", "T4"]},
        ]
    if scenario == "test_docs":
        return [
            {"id": "T0", "title": "Inventory current tests and docs gaps", "depends_on": []},
            {"id": "T1", "title": "Expand pytest coverage (validation, analytics, conflicts)", "depends_on": ["T0"]},
            {"id": "T2", "title": "Upgrade README runbook + API examples + limitations", "depends_on": ["T0"]},
            {"id": "T3", "title": "Execute improved test suite", "depends_on": ["T1"]},
            {"id": "T4", "title": "Security + release checklist", "depends_on": ["T2", "T3"]},
        ]
    if scenario == "ambiguous":
        return [
            {"id": "T1", "title": "Clarify ambiguous scope into bounded option", "depends_on": []},
            {"id": "T2", "title": "Design bounded slice architecture", "depends_on": ["T1"]},
            {"id": "T3", "title": "Implement selected slice", "depends_on": ["T2"]},
            {"id": "T4", "title": "Tests + docs for selected slice", "depends_on": ["T3"]},
            {"id": "T5", "title": "Security + release readiness", "depends_on": ["T4"]},
        ]
    return [
        {"id": "T1", "title": "Define API contracts & data model", "depends_on": []},
        {"id": "T2", "title": "Generate application package (app/*)", "depends_on": ["T1"]},
        {"id": "T3", "title": "Generate unit/integration tests", "depends_on": ["T2"]},
        {"id": "T4", "title": "Generate README & run instructions", "depends_on": ["T2"]},
        {"id": "T5", "title": "Execute tests against generated code", "depends_on": ["T3"]},
        {"id": "T6", "title": "Security review + release checklist", "depends_on": ["T5", "T4"]},
    ]


def design(run: RunState) -> dict[str, Any]:
    features = run.context.get("features", {})
    scenario = run.context.get("scenario", "greenfield")
    if _use_llm():
        try:
            data = chat_json(
                system=(
                    "You are a software architect agent. Return JSON design with keys: "
                    "architecture, components (array), apis (array), data_model (array), "
                    "non_functionals (array), risks (array), change_set (array), rationale (str). "
                    "Target stack must be FastAPI + SQLAlchemy + SQLite. "
                    "For brownfield/test_docs, emphasize change_set and impacted modules."
                ),
                user=json.dumps(
                    {
                        "scenario": scenario,
                        "normalized_requirement": run.context.get("spec", {}).get("normalized_requirement"),
                        "features": features,
                        "tasks": run.context.get("task_graph"),
                        "impacted_modules": run.context.get("impacted_modules"),
                        "existing_files": run.context.get("existing_files", []),
                    }
                ),
                run_dir=run.run_dir,
                stage="Design",
            )
            design_doc = {
                **data,
                "scenario": scenario,
                "features": features,
                "impacted_modules": run.context.get("impacted_modules", []),
                "output_dir": str(run.project_dir),
                "normalized_requirement": run.context.get("spec", {}).get("normalized_requirement"),
            }
            run.decide("Design", "llm_design", data.get("rationale", "LLM produced design"))
        except LLMError as exc:
            design_doc = _mock_design(run, features)
            run.decide("Design", "fallback_design", str(exc))
    else:
        design_doc = _mock_design(run, features)
        run.decide("Design", "mock_design", f"Deterministic design for {scenario}")

    run.context["design"] = design_doc
    run.context["spec"]["design"] = design_doc
    md = "# Technical Design\n\n```json\n" + json.dumps(design_doc, indent=2) + "\n```\n"
    path = _write_artifact(run, "04_design.md", md)
    return {"artifact": path, "needs_approval": "design_approval"}


def _mock_design(run: RunState, features: dict[str, Any]) -> dict[str, Any]:
    scenario = run.context.get("scenario", "greenfield")
    change_set: list[str] = []
    if scenario == "brownfield":
        change_set = [
            "Add custom_alias + rate_limit_per_minute fields",
            "Validate alias uniqueness/format",
            "Expose fields in API schemas/responses",
            "Extend regression tests",
        ]
    elif scenario == "test_docs":
        change_set = [
            "Expand pytest coverage for validation/analytics/aliases",
            "Rewrite README with runbook, API examples, limitations",
            "Add ENGINEERING notes for reviewers",
        ]
    return {
        "architecture": "Single FastAPI service + SQLAlchemy + SQLite",
        "scenario": scenario,
        "components": ["HTTP API", "Service layer", "ORM models", "Click analytics store", "Health endpoint"],
        "apis": [
            "POST /api/v1/urls",
            "GET /{code}",
            "GET /api/v1/urls/{code}",
            "GET /api/v1/urls/{code}/analytics",
            "GET /health",
        ],
        "features": features,
        "change_set": change_set,
        "impacted_modules": run.context.get("impacted_modules", []),
        "non_functionals": ["input validation", "open-redirect hardening", "test coverage"],
        "output_dir": str(run.project_dir),
        "normalized_requirement": run.context.get("spec", {}).get("normalized_requirement"),
        "llm": {"mode": "mock"},
    }


# ---------------------------------------------------------------------------
# Implement — greenfield create OR brownfield/test_docs enhance
# ---------------------------------------------------------------------------

def implement(run: RunState) -> dict[str, Any]:
    scenario = run.context.get("scenario", "greenfield")
    project_dir = run.project_dir
    enhance = scenario in {"brownfield", "test_docs"}

    if not enhance:
        if project_dir.exists():
            for child in project_dir.iterdir():
                if child.is_file():
                    child.unlink()
                else:
                    shutil.rmtree(child)

    spec = {
        **run.context.get("spec", {}),
        "features": run.context.get("features", {}),
        "app_name": run.context.get("spec", {}).get("app_name", "Agent-Built URL Shortener"),
        "design": run.context.get("design", {}),
    }

    source = "mock_template"
    files: list[str] = []
    llm_meta: dict[str, Any] = {}

    if enhance:
        files, source, llm_meta = _implement_enhance(run, project_dir, spec)
    elif _use_llm():
        try:
            data = chat_json(
                system=(
                    "You are an implementation agent that writes a complete FastAPI URL shortener. "
                    "Return JSON: {files: {relative_path: file_content_string}, notes: str}. "
                    "MUST include exactly these paths: requirements.txt, README.md, "
                    "app/__init__.py, app/main.py, app/database.py, app/models.py, "
                    "app/schemas.py, app/services.py, tests/__init__.py, tests/test_app.py. "
                    "Constraints: SQLite+SQLAlchemy; endpoints POST /api/v1/urls, GET /{code} "
                    "307 redirect, GET /api/v1/urls/{code}, GET /api/v1/urls/{code}/analytics, "
                    "GET /health; block localhost targets; include pytest TestClient tests; "
                    "use relative imports from app.*; Python 3.11+ typing. "
                    "If custom_alias feature true, support optional custom_alias "
                    "(Pydantic: custom_alias: str | None = None). "
                    "Tests MUST create a URL via POST then use the returned code for redirect — "
                    "never hard-code short codes like abc123. Reset DB in setup. "
                    "Keep each file complete and runnable."
                ),
                user=json.dumps(
                    {
                        "scenario": scenario,
                        "normalized_requirement": spec.get("normalized_requirement"),
                        "features": spec.get("features"),
                        "design": {
                            "architecture": spec.get("design", {}).get("architecture"),
                            "apis": spec.get("design", {}).get("apis"),
                            "components": spec.get("design", {}).get("components"),
                        },
                    }
                ),
                run_dir=run.run_dir,
                stage="Implement",
                temperature=0.1,
            )
            file_map = data.get("files") or {}
            if not isinstance(file_map, dict) or not file_map:
                raise LLMError("LLM returned empty files map")
            files = _write_file_map(project_dir, file_map)
            missing = [f for f in REQUIRED_PROJECT_FILES if not (project_dir / f).exists()]
            if missing:
                generate_url_shortener(project_dir, spec)
                files = _list_project_files(project_dir)
                source = "llm_with_template_gapfill"
                run.decide("Implement", "gapfill", f"Filled missing files from template: {missing}")
            else:
                source = "openai_llm"
            llm_meta = data.get("_llm") or {}
            run.decide("Implement", "llm_codegen", data.get("notes", f"LLM wrote {len(files)} files"))
        except LLMError as exc:
            files = generate_url_shortener(project_dir, spec)
            source = "template_fallback"
            run.decide("Implement", "fallback_codegen", f"LLM codegen failed: {exc}")
    else:
        files = generate_url_shortener(project_dir, spec)
        run.decide("Implement", "mock_codegen", f"Template wrote {len(files)} files")

    run.context["generated_files"] = files
    run.context["project_path"] = str(project_dir)
    run.context["implement_source"] = source
    if not enhance:
        run.context.setdefault("rollback_stack", []).append({"action": "delete_project", "path": str(project_dir)})
    run.metrics["files_generated"] = len(files)

    manifest = {
        "scenario": scenario,
        "project_dir": str(project_dir),
        "files": files,
        "source": source,
        "enhance_mode": enhance,
        "feature_flags": run.context.get("features"),
        "impacted_modules": run.context.get("impacted_modules", []),
        "llm": llm_meta,
    }
    path = _write_artifact(run, "05_implement.json", json.dumps(manifest, indent=2))
    return {"artifact": path}


def _implement_enhance(run: RunState, project_dir: Path, spec: dict[str, Any]) -> tuple[list[str], str, dict[str, Any]]:
    """Brownfield / test_docs: modify existing codebase instead of wiping it."""
    from pipeline.scenarios import read_project_files

    scenario = run.context.get("scenario")
    llm_meta: dict[str, Any] = {}
    existing = read_project_files(project_dir)

    if _use_llm():
        try:
            if scenario == "test_docs":
                system = (
                    "You are a brownfield improvement agent focused on tests and documentation. "
                    "Given existing files, return JSON {files:{path:content}, notes}. "
                    "Improve tests/test_app.py with broader coverage and rewrite README.md "
                    "with runbook, API examples, and limitations. You may add tests/test_edge_cases.py. "
                    "CRITICAL: malformed URLs like 'invalid-url' yield HTTP 422 from Pydantic/FastAPI "
                    "(assert 422, not 400). Localhost targets yield 400 from business validation. "
                    "Create-then-redirect in tests; never hard-code short codes. "
                    "Do NOT remove core app functionality. Keep FastAPI shortener working."
                )
            else:
                system = (
                    "You are a brownfield implementation agent. Given an existing FastAPI URL shortener, "
                    "return JSON {files:{path:content}, notes} with UPDATED files to add custom_alias "
                    "and rate_limit_per_minute end-to-end (models, schemas, services, main, tests, README). "
                    "Preserve working create/redirect/analytics/health behavior and localhost blocking."
                )
            data = chat_json(
                system=system,
                user=json.dumps(
                    {
                        "scenario": scenario,
                        "normalized_requirement": spec.get("normalized_requirement"),
                        "features": spec.get("features"),
                        "change_set": run.context.get("design", {}).get("change_set"),
                        "existing_files": existing,
                    }
                ),
                run_dir=run.run_dir,
                stage="ImplementEnhance",
                temperature=0.1,
            )
            file_map = data.get("files") or {}
            if not file_map:
                raise LLMError("Empty enhancement file map")
            _write_file_map(project_dir, file_map)
            # Ensure still complete/runnable
            if scenario == "brownfield":
                missing = [f for f in REQUIRED_PROJECT_FILES if not (project_dir / f).exists()]
                if missing or "custom_alias" not in (project_dir / "app" / "models.py").read_text(encoding="utf-8"):
                    generate_url_shortener(project_dir, spec)
                    run.decide("Implement", "enhance_gapfill", "Applied enhanced template after LLM patch gaps")
                    return _list_project_files(project_dir), "llm_enhance_with_template", data.get("_llm") or {}
            files = _list_project_files(project_dir)
            run.decide("Implement", "llm_enhance", data.get("notes", f"Patched {len(file_map)} files"))
            return files, "openai_llm_enhance", data.get("_llm") or {}
        except LLMError as exc:
            run.decide("Implement", "enhance_fallback", str(exc))

    # Mock / fallback enhance
    if scenario == "brownfield":
        files = generate_url_shortener(project_dir, spec)
        run.decide("Implement", "mock_enhance_features", "Applied enhanced template onto baseline")
        return files, "mock_brownfield_enhance", llm_meta

    # test_docs mock: restore full tests + richer README while keeping MVP features
    files = generate_url_shortener(project_dir, spec)
    readme = f"""# URL Shortener (Improved Docs)

Improved by the agentic `test_docs` scenario.

## Requirement
{spec.get('normalized_requirement')}

## Run
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## API examples
```bash
curl -X POST http://127.0.0.1:8000/api/v1/urls -H "Content-Type: application/json" -d "{{\\"url\\":\\"https://example.com/x\\"}}"
curl -i http://127.0.0.1:8000/<code>
curl http://127.0.0.1:8000/api/v1/urls/<code>/analytics
```

## Limitations
- SQLite prototype
- No auth/SSO
"""
    (project_dir / "README.md").write_text(readme, encoding="utf-8")
    (project_dir / "docs_improvements.md").write_text(
        "# Documentation & Test Improvements\n\n- Expanded pytest coverage via regenerated suite\n- Upgraded README runbook and API examples\n",
        encoding="utf-8",
    )
    files = _list_project_files(project_dir)
    run.decide("Implement", "mock_test_docs_improve", "Expanded tests and documentation on baseline")
    return files, "mock_test_docs_enhance", llm_meta


def _list_project_files(project_dir: Path) -> list[str]:
    return sorted(
        str(p.relative_to(project_dir)).replace("\\", "/")
        for p in project_dir.rglob("*")
        if p.is_file()
    )


def _write_file_map(project_dir: Path, file_map: dict[str, Any]) -> list[str]:
    written: list[str] = []
    for rel, content in file_map.items():
        rel_norm = str(rel).replace("\\", "/").lstrip("/")
        if ".." in rel_norm.split("/"):
            continue
        if not isinstance(content, str):
            content = str(content)
        path = project_dir / rel_norm
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(rel_norm)
    return sorted(written)


# ---------------------------------------------------------------------------
# Test / Document / Security / Release
# ---------------------------------------------------------------------------

def test_stage(run: RunState) -> dict[str, Any]:
    project_dir = Path(run.context["project_path"])
    cmd = [sys.executable, "-m", "pytest", "-q"]
    proc = subprocess.run(cmd, cwd=str(project_dir), capture_output=True, text=True)
    report = {
        "command": " ".join(cmd),
        "cwd": str(project_dir),
        "returncode": proc.returncode,
        "passed": proc.returncode == 0,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-2000:],
    }

    llm_sources = {"openai_llm", "openai_llm_enhance", "llm_with_template_gapfill", "llm_enhance_with_template"}
    # If LLM-generated code fails tests, ask LLM to patch once then retest
    if not report["passed"] and _use_llm() and run.context.get("implement_source") in llm_sources:
        try:
            patch = chat_json(
                system=(
                    "You are a debugging agent fixing a FastAPI URL shortener so pytest passes. "
                    "Return JSON {files:{path:content}} with fixed files only. "
                    "Common fixes: (1) response schema custom_alias must be Optional[str]=None; "
                    "(2) tests must CREATE a short URL then redirect using returned code — "
                    "never assume hard-coded codes like abc123 exist; "
                    "(3) reset DB between tests; (4) avoid UNIQUE conflicts on short_code; "
                    "(5) invalid URL strings like 'invalid-url' are rejected by Pydantic as 422, "
                    "NOT 400 — assert status_code in (400, 422) or exactly 422."
                ),
                user=json.dumps(
                    {
                        "stdout": report["stdout"],
                        "stderr": report["stderr"],
                        "files": {
                            rel: (project_dir / rel).read_text(encoding="utf-8")[:8000]
                            for rel in run.context.get("generated_files", [])
                            if (project_dir / rel).exists() and rel.endswith((".py", ".txt", ".md"))
                        },
                    }
                ),
                run_dir=run.run_dir,
                stage="TestRepair",
                temperature=0.1,
            )
            if patch.get("files"):
                _write_file_map(project_dir, patch["files"])
                proc2 = subprocess.run(cmd, cwd=str(project_dir), capture_output=True, text=True)
                report = {
                    "command": " ".join(cmd) + " (after LLM repair)",
                    "cwd": str(project_dir),
                    "returncode": proc2.returncode,
                    "passed": proc2.returncode == 0,
                    "stdout": proc2.stdout[-4000:],
                    "stderr": proc2.stderr[-2000:],
                    "repaired_by_llm": True,
                }
                run.decide("Test", "llm_repair", "Applied LLM patch and retested")
        except LLMError as exc:
            run.decide("Test", "repair_skipped", str(exc))

    # Final safety net: wipe leftover LLM test files, rewrite known-good template, retest
    if not report["passed"]:
        spec = {
            **run.context.get("spec", {}),
            "features": run.context.get("features", {}),
            "app_name": run.context.get("spec", {}).get("app_name", "Agent-Built URL Shortener"),
        }
        tests_dir = project_dir / "tests"
        if tests_dir.exists():
            for leftover in tests_dir.glob("test_*.py"):
                leftover.unlink(missing_ok=True)
        generate_url_shortener(project_dir, spec)
        run.context["generated_files"] = _list_project_files(project_dir)
        run.context["implement_source"] = "template_after_test_failure"
        proc3 = subprocess.run(cmd, cwd=str(project_dir), capture_output=True, text=True)
        report = {
            "command": " ".join(cmd) + " (after template fallback)",
            "cwd": str(project_dir),
            "returncode": proc3.returncode,
            "passed": proc3.returncode == 0,
            "stdout": proc3.stdout[-4000:],
            "stderr": proc3.stderr[-2000:],
            "repaired_by_template_fallback": True,
            "prior_llm_failure": True,
        }
        run.decide("Test", "template_fallback", "LLM output failed tests; applied known-good template")

    run.context["test_report"] = report
    path = _write_artifact(run, "06_test.json", json.dumps(report, indent=2))
    if not report["passed"]:
        raise RuntimeError(f"Generated project tests failed:\n{report.get('stdout')}\n{report.get('stderr')}")
    run.decide("Test", "quality_gate", "pytest passed on generated code")
    return {"artifact": path}


def document(run: RunState) -> dict[str, Any]:
    project_dir = Path(run.context["project_path"])
    if _use_llm():
        try:
            summary = chat_text(
                system=(
                    "You are a documentation agent. Write a concise Engineering Outcome markdown "
                    "for a generated URL shortener: requirement, design summary, how to run, "
                    "assumptions, limitations, and AI/LLM usage notes."
                ),
                user=json.dumps(
                    {
                        "requirement": run.requirement,
                        "normalized": run.context.get("spec", {}).get("normalized_requirement"),
                        "features": run.context.get("features"),
                        "files": run.context.get("generated_files"),
                        "project_dir": str(project_dir),
                        "implement_source": run.context.get("implement_source"),
                        "llm_mode": agent_mode(),
                    }
                ),
                run_dir=run.run_dir,
                stage="Document",
            )
            run.decide("Document", "llm_docs", "LLM wrote engineering outcome docs")
        except LLMError as exc:
            summary = _mock_docs(run, project_dir)
            run.decide("Document", "fallback_docs", str(exc))
    else:
        summary = _mock_docs(run, project_dir)
        run.decide("Document", "mock_docs", "Mock documentation")

    (project_dir / "ENGINEERING_OUTCOME.md").write_text(summary, encoding="utf-8")
    path = _write_artifact(run, "07_docs.md", summary)
    run.context["docs_path"] = path
    return {"artifact": path}


def _mock_docs(run: RunState, project_dir: Path) -> str:
    return f"""# Engineering Outcome Summary

## Requirement
{run.requirement}

## Normalized
{run.context.get('spec', {}).get('normalized_requirement')}

## Generated project
`{project_dir}`

## Implement source
{run.context.get('implement_source')}

## Files
{json.dumps(run.context.get('generated_files', []), indent=2)}

## How to run
```bash
cd "{project_dir}"
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
"""


def security_review(run: RunState) -> dict[str, Any]:
    project_dir = Path(run.context["project_path"])
    services_path = project_dir / "app" / "services.py"
    services = services_path.read_text(encoding="utf-8") if services_path.exists() else ""

    if _use_llm():
        try:
            data = chat_json(
                system=(
                    "You are a security review agent. Return JSON: "
                    "{findings:[{severity:critical|high|medium|low,issue,recommendation}], "
                    "critical_findings:int, passed:bool, summary:str}. "
                    "Flag missing URL scheme validation or localhost allow as critical/high."
                ),
                user=json.dumps({"services_py": services[:12000], "features": run.context.get("features")}),
                run_dir=run.run_dir,
                stage="SecurityReview",
            )
            report = {
                "findings": data.get("findings") or [],
                "critical_findings": int(data.get("critical_findings") or 0),
                "passed": bool(data.get("passed", True)),
                "summary": data.get("summary"),
                "llm": data.get("_llm"),
            }
            # Enforce local hard gates even if LLM is lenient
            if "validate_target_url" not in services and "BLOCKED_HOSTS" not in services:
                report["critical_findings"] = max(report["critical_findings"], 1)
                report["passed"] = False
                report["findings"].append(
                    {"severity": "critical", "issue": "Missing URL validation / host blocklist", "recommendation": "Add validate_target_url"}
                )
            run.decide("SecurityReview", "llm_security", report.get("summary") or "LLM security review complete")
        except LLMError as exc:
            report = _mock_security(services)
            run.decide("SecurityReview", "fallback_security", str(exc))
    else:
        report = _mock_security(services)
        run.decide("SecurityReview", "mock_security", "Deterministic security checks")

    run.context["security_report"] = report
    path = _write_artifact(run, "08_security.json", json.dumps(report, indent=2))
    if report.get("critical_findings", 0) > 0 or not report.get("passed", False):
        raise RuntimeError("Security review failed with critical findings")
    return {"artifact": path}


def _mock_security(services: str) -> dict[str, Any]:
    findings = []
    if "validate_target_url" not in services:
        findings.append({"severity": "critical", "issue": "Missing URL validation"})
    if "BLOCKED_HOSTS" not in services:
        findings.append({"severity": "high", "issue": "Missing localhost blocklist"})
    critical = sum(1 for f in findings if f["severity"] == "critical")
    return {"findings": findings, "critical_findings": critical, "passed": critical == 0, "llm": {"mode": "mock"}}


def release_ready(run: RunState) -> dict[str, Any]:
    checklist = {
        "code_generated": bool(run.context.get("generated_files")),
        "tests_passed": bool(run.context.get("test_report", {}).get("passed")),
        "docs_present": bool(run.context.get("docs_path")),
        "security_passed": run.context.get("security_report", {}).get("critical_findings", 1) == 0,
        "design_approved": "design_approval" in run.approvals,
        "project_path": run.context.get("project_path"),
        "llm_mode": agent_mode(),
        "implement_source": run.context.get("implement_source"),
        "limitations": [
            "SQLite single-node prototype",
            "No SSO / multi-region",
            "Uses OpenAI gpt-4o-mini for agent reasoning/codegen when AGENT_MODE=openai",
        ],
    }
    run.context["release_checklist"] = checklist
    run.context["release_ready"] = all(
        [
            checklist["code_generated"],
            checklist["tests_passed"],
            checklist["docs_present"],
            checklist["security_passed"],
            checklist["design_approved"],
        ]
    )
    path = _write_artifact(run, "09_release.md", "# Release Readiness\n\n" + json.dumps(checklist, indent=2))
    run.decide("ReleaseReady", "checklist", "Release package ready for human sign-off")
    return {"artifact": path, "needs_approval": "release_approval"}


STAGE_HANDLERS: dict[str, Handler] = {
    "GatherRequirements": gather_requirements,
    "Clarify": clarify,
    "Decompose": decompose,
    "Design": design,
    "Implement": implement,
    "Test": test_stage,
    "Document": document,
    "SecurityReview": security_review,
    "ReleaseReady": release_ready,
}
