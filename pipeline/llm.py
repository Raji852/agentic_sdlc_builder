from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from pipeline.state import ROOT

load_dotenv(ROOT / ".env")

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


class LLMError(RuntimeError):
    pass


def agent_mode() -> str:
    """openai (default when key set) | mock (offline / tests)."""
    mode = os.getenv("AGENT_MODE", "").strip().lower()
    if mode in {"openai", "mock"}:
        return mode
    return "openai" if os.getenv("OPENAI_API_KEY") else "mock"


def chat_json(
    *,
    system: str,
    user: str,
    run_dir: Path | None = None,
    stage: str = "unknown",
    temperature: float = 0.2,
) -> dict[str, Any]:
    """Call OpenAI chat completions and parse a JSON object response."""
    mode = agent_mode()
    if mode == "mock":
        raise LLMError("AGENT_MODE=mock — caller should use deterministic fallback")

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise LLMError("OPENAI_API_KEY is missing. Set it in .env")

    model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise LLMError("openai package not installed. Run: pip install openai") from exc

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    content = response.choices[0].message.content or "{}"
    usage = {
        "prompt_tokens": getattr(response.usage, "prompt_tokens", None),
        "completion_tokens": getattr(response.usage, "completion_tokens", None),
        "total_tokens": getattr(response.usage, "total_tokens", None),
    }

    if run_dir is not None:
        _log_call(
            run_dir,
            stage=stage,
            model=model,
            system=system,
            user=user,
            content=content,
            usage=usage,
        )

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = _extract_json_object(content)
    if not isinstance(data, dict):
        raise LLMError(f"LLM returned non-object JSON for stage={stage}")
    data["_llm"] = {"model": model, "mode": "openai", "usage": usage, "stage": stage}
    return data


def chat_text(
    *,
    system: str,
    user: str,
    run_dir: Path | None = None,
    stage: str = "unknown",
    temperature: float = 0.3,
) -> str:
    mode = agent_mode()
    if mode == "mock":
        raise LLMError("AGENT_MODE=mock — caller should use deterministic fallback")

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise LLMError("OPENAI_API_KEY is missing. Set it in .env")

    model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    content = response.choices[0].message.content or ""
    usage = {
        "prompt_tokens": getattr(response.usage, "prompt_tokens", None),
        "completion_tokens": getattr(response.usage, "completion_tokens", None),
        "total_tokens": getattr(response.usage, "total_tokens", None),
    }
    if run_dir is not None:
        _log_call(
            run_dir,
            stage=stage,
            model=model,
            system=system,
            user=user,
            content=content,
            usage=usage,
        )
    return content


def _log_call(
    run_dir: Path,
    *,
    stage: str,
    model: str,
    system: str,
    user: str,
    content: str,
    usage: dict[str, Any],
) -> None:
    path = run_dir / "llm_calls.jsonl"
    record = {
        "stage": stage,
        "model": model,
        "usage": usage,
        "system_chars": len(system),
        "user": user[:4000],
        "response_preview": content[:4000],
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _extract_json_object(text: str) -> dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise LLMError("Could not parse JSON from LLM response")
    return json.loads(match.group(0))
