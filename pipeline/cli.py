from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from pipeline.engine import AgenticPipeline  # noqa: E402
from pipeline.scenarios import SCENARIO_META, SCENARIOS, resolve_requirement  # noqa: E402
from pipeline.state import RUNS, RunState  # noqa: E402


def cmd_build(args: argparse.Namespace) -> int:
    from pipeline.llm import agent_mode

    scenario = args.scenario
    requirement = resolve_requirement(scenario, args.requirement, args.requirement_file)

    mode = agent_mode()
    if mode == "openai" and not os.getenv("OPENAI_API_KEY"):
        print(
            "ERROR: AGENT_MODE=openai but OPENAI_API_KEY is not set.\n"
            "Copy .env.example to .env and add your OpenAI key.\n"
            "Or set AGENT_MODE=mock for offline/template agents.",
            file=sys.stderr,
        )
        return 2

    meta = SCENARIO_META[scenario]
    print(f"Scenario: {scenario} — {meta['title']}")
    print(f"Agent mode: {mode} | model: {os.getenv('OPENAI_MODEL', 'gpt-4o-mini')}")

    pipeline = AgenticPipeline(auto_approve=args.auto_approve)
    run = pipeline.start(requirement, scenario=scenario, base_project=args.base_project)
    _print_run(run)
    if run.status.value == "waiting_approval":
        print(
            "\nHuman approval required. Examples:\n"
            f"  python -m pipeline approve --run-id {run.run_id} --approval scope_approval --choice A\n"
            f"  python -m pipeline approve --run-id {run.run_id} --approval design_approval\n"
            f"  python -m pipeline approve --run-id {run.run_id} --approval release_approval\n"
        )
    if run.status.value == "completed":
        print(f"\nGenerated/updated project: {run.context.get('project_path')}")
        print(
            "Next:\n"
            f"  cd \"{run.context.get('project_path')}\"\n"
            "  pip install -r requirements.txt\n"
            "  uvicorn app.main:app --reload --port 8000\n"
        )
    return 0 if run.status.value in {"completed", "waiting_approval"} else 1


def cmd_approve(args: argparse.Namespace) -> int:
    run = RunState.load(args.run_id)
    payload = {"approved": True, "rationale": args.rationale or "Human approved"}
    if args.approval == "scope_approval":
        payload["choice"] = args.choice or "A"
    run = AgenticPipeline(auto_approve=False).resume(run, {args.approval: payload})
    _print_run(run)
    if run.status.value == "completed":
        print(f"\nGenerated/updated project: {run.context.get('project_path')}")
    return 0 if run.status.value in {"completed", "waiting_approval"} else 1


def cmd_status(args: argparse.Namespace) -> int:
    run = RunState.load(args.run_id)
    print(
        json.dumps(
            {
                "run_id": run.run_id,
                "status": run.status.value,
                "scenario": run.context.get("scenario"),
                "nodes": {k: v.status.value for k, v in run.nodes.items()},
                "project_path": run.context.get("project_path"),
                "files": run.context.get("generated_files"),
                "approvals": list(run.approvals),
            },
            indent=2,
        )
    )
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    if not RUNS.exists():
        print("[]")
        return 0
    print(json.dumps(sorted([p.name for p in RUNS.iterdir() if p.is_dir()], reverse=True), indent=2))
    return 0


def cmd_scenarios(_: argparse.Namespace) -> int:
    print(json.dumps({k: SCENARIO_META[k] for k in SCENARIOS}, indent=2))
    return 0


def cmd_retest(args: argparse.Namespace) -> int:
    """Re-run tests for an existing run_id without rebuilding Gather→Implement."""
    run = RunState.load(args.run_id)
    print(
        f"Retesting run {run.run_id} | scenario={run.context.get('scenario')} | "
        f"project={run.context.get('project_path')}"
    )
    pipeline = AgenticPipeline(auto_approve=args.auto_approve)
    try:
        run = pipeline.retest(
            run,
            repair=args.repair,
            continue_pipeline=args.continue_pipeline,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    _print_run(run)
    report = run.context.get("test_report") or {}
    if report:
        print(f"\npytest passed: {report.get('passed')} | returncode: {report.get('returncode')}")
        if report.get("stdout"):
            print(report["stdout"][-1500:])
    if run.nodes["Test"].status.value != "passed":
        print(
            "\nTip: use --repair to apply LLM repair / known-good template, then retest.\n"
            "  python -m pipeline retest --run-id "
            f"{args.run_id} --repair --continue --auto-approve\n",
            file=sys.stderr,
        )
        return 1
    if args.continue_pipeline and run.status.value == "waiting_approval":
        print(
            f"\nApproval needed:\n"
            f"  python -m pipeline approve --run-id {run.run_id} --approval release_approval\n"
        )
    return 0


def _print_run(run: RunState) -> None:
    print(
        json.dumps(
            {
                "run_id": run.run_id,
                "scenario": run.context.get("scenario"),
                "status": run.status.value,
                "project_path": run.context.get("project_path"),
                "files_generated": run.metrics.get("files_generated"),
                "nodes": {k: v.status.value for k, v in run.nodes.items()},
            },
            indent=2,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Agentic SDLC Builder — turn a requirement into a generated URL shortener"
    )
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="Run an assignment scenario through the agentic SDLC pipeline")
    b.add_argument(
        "--scenario",
        choices=list(SCENARIOS),
        default="greenfield",
        help="greenfield | brownfield | ambiguous | test_docs",
    )
    b.add_argument("--requirement", default=None, help="Override requirement text")
    b.add_argument("--requirement-file", default=None, help="Path to a requirements .md/.txt file")
    b.add_argument(
        "--base-project",
        default=None,
        help="For brownfield/test_docs: existing project path (default: seed MVP baseline)",
    )
    b.add_argument("--auto-approve", action="store_true", help="Auto-approve human gates (demo)")
    b.set_defaults(func=cmd_build)

    a = sub.add_parser("approve", help="Approve a gate and resume the pipeline")
    a.add_argument("--run-id", required=True)
    a.add_argument("--approval", required=True, choices=["scope_approval", "design_approval", "release_approval"])
    a.add_argument("--choice", default="A")
    a.add_argument("--rationale", default=None)
    a.set_defaults(func=cmd_approve)

    s = sub.add_parser("status", help="Show run status")
    s.add_argument("--run-id", required=True)
    s.set_defaults(func=cmd_status)

    l = sub.add_parser("list", help="List runs")
    l.set_defaults(func=cmd_list)

    sc = sub.add_parser("scenarios", help="List supported assignment scenarios")
    sc.set_defaults(func=cmd_scenarios)

    rt = sub.add_parser(
        "retest",
        help="Re-run pytest for an existing run_id (no full app rebuild). Optional --repair/--continue",
    )
    rt.add_argument("--run-id", required=True, help="Existing run id, e.g. 20260927T163945Z-8dafe392")
    rt.add_argument(
        "--repair",
        action="store_true",
        help="Use Test-stage repair (LLM patch and/or known-good template) before/while testing",
    )
    rt.add_argument(
        "--continue",
        dest="continue_pipeline",
        action="store_true",
        help="After tests pass, continue SecurityReview + ReleaseReady for this run",
    )
    rt.add_argument("--auto-approve", action="store_true", help="Auto-approve remaining gates")
    rt.set_defaults(func=cmd_retest)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "auto_approve", False):
        os.environ["AUTO_APPROVE"] = "true"
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())