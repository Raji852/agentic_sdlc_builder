from __future__ import annotations

from typing import Any


FORBIDDEN = ("exfiltrate secrets", "disable all security", "hardcode password")


def check_requirement(requirement: str) -> tuple[bool, str]:
    lowered = requirement.lower()
    for term in FORBIDDEN:
        if term in lowered:
            return False, f"Blocked by security policy: {term}"
    return True, "Requirement accepted"


def check_release(context: dict[str, Any]) -> tuple[bool, str]:
    if not context.get("test_report", {}).get("passed"):
        return False, "Tests have not passed"
    if context.get("security_report", {}).get("critical_findings", 1) > 0:
        return False, "Critical security findings remain"
    if not context.get("generated_files"):
        return False, "No code was generated"
    return True, "Release policies satisfied"