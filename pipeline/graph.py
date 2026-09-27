from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NodeSpec:
    name: str
    depends_on: list[str] = field(default_factory=list)
    requires_approval: str | None = None
    parallel_group: str | None = None
    max_retries: int = 2


# Agentic SDLC dependency graph — agents execute these stages to build the product.
SDLC_GRAPH: dict[str, NodeSpec] = {
    "GatherRequirements": NodeSpec(name="GatherRequirements"),
    "Clarify": NodeSpec(name="Clarify", depends_on=["GatherRequirements"], requires_approval="scope_approval"),
    "Decompose": NodeSpec(name="Decompose", depends_on=["Clarify"]),
    "Design": NodeSpec(name="Design", depends_on=["Decompose"], requires_approval="design_approval"),
    "Implement": NodeSpec(name="Implement", depends_on=["Design"], max_retries=2),
    "Test": NodeSpec(name="Test", depends_on=["Implement"], max_retries=2),
    "Document": NodeSpec(name="Document", depends_on=["Implement"], parallel_group="post_impl"),
    "SecurityReview": NodeSpec(name="SecurityReview", depends_on=["Test"], parallel_group="post_impl"),
    "ReleaseReady": NodeSpec(
        name="ReleaseReady",
        depends_on=["Document", "SecurityReview"],
        requires_approval="release_approval",
    ),
}


def ordered_nodes() -> list[str]:
    remaining = set(SDLC_GRAPH)
    out: list[str] = []
    while remaining:
        ready = sorted(n for n in remaining if all(d not in remaining for d in SDLC_GRAPH[n].depends_on))
        if not ready:
            raise RuntimeError("Cycle in SDLC graph")
        out.extend(ready)
        remaining -= set(ready)
    return out