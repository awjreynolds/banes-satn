"""Provider-neutral agent gate with a deterministic offline runtime."""

from __future__ import annotations

from typing import Protocol

from satn.models import AgentRecord


class AgentRuntime(Protocol):
    def review(self, connection_id: str, facts: dict[str, object]) -> AgentRecord: ...


class FakeAgentRuntime:
    """Reproducible red-team runtime used by tests and unconfigured POC runs."""

    def review(self, connection_id: str, facts: dict[str, object]) -> AgentRecord:
        checks_passed = bool(facts.get("checks_passed"))
        decision = "accept" if checks_passed else "gap"
        return AgentRecord(
            connection_id=connection_id,
            runtime="fake",
            model="deterministic-rules-v1",
            proposal="Use the direct source-network path between the nominated communities.",
            critique=(
                "No deterministic objection found."
                if checks_passed
                else "Deterministic checks found an unresolved route defect."
            ),
            revision="Retain the path." if checks_passed else "Publish as a Network Gap.",
            decision=decision,
        )


def runtime_for(provider: str) -> AgentRuntime:
    if provider == "fake":
        return FakeAgentRuntime()
    raise ValueError(f"agent provider {provider!r} is not configured")

