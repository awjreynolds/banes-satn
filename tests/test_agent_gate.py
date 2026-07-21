from __future__ import annotations

import os

import pytest

from satn.agents import (
    AgentRole,
    CompilationGate,
    FakeAgentRuntime,
    PydanticAIRuntime,
)
from satn.models import AgentConfig


def facts(*, direct: str = "green", low_traffic: str = "green") -> dict[str, object]:
    return {
        "from_place": "a",
        "to_place": "b",
        "evidence_ids": ["edge-1"],
        "checks_by_role": {
            "direct": {
                "endpoints": direct,
                "continuity": direct,
                "bidirectional": direct,
                "distance": "green",
            },
            "low-traffic": {
                "endpoints": low_traffic,
                "continuity": low_traffic,
                "bidirectional": low_traffic,
                "distance": "green",
            },
        },
    }


def gate(runtime: FakeAgentRuntime, *, attempts: int = 3) -> CompilationGate:
    return CompilationGate(
        runtime,
        AgentConfig(max_attempts=attempts, max_requests=12, max_tokens=100),
    )


def test_success_records_all_typed_roles() -> None:
    outcome = gate(FakeAgentRuntime()).evaluate(
        "connection-a-b", facts(), "direct", ["direct", "low-traffic"]
    )

    assert outcome.record.decision == "accept"
    assert outcome.selected_role == "direct"
    assert outcome.record.usage == {"requests": 4, "tokens": 4}
    assert set(outcome.record.attempts[0]) >= {
        "proposal",
        "critique",
        "red_team",
        "synthesis",
        "deterministic_findings",
    }


def test_schema_rejection_retries_then_accepts() -> None:
    runtime = FakeAgentRuntime(
        {
            AgentRole.PROPOSER: [
                {"invalid": "record"},
                {
                    "selected_role": "direct",
                    "rationale": "Valid retry",
                    "evidence_ids": ["edge-1"],
                },
            ]
        }
    )

    outcome = gate(runtime).evaluate(
        "connection-a-b", facts(), "direct", ["direct", "low-traffic"]
    )

    assert outcome.record.decision == "accept"
    assert len(outcome.record.attempts) == 2
    assert outcome.record.attempts[0]["findings"][0]["code"] == "agent-schema-error"


def test_structured_revision_changes_alignment_before_acceptance() -> None:
    runtime = FakeAgentRuntime(
        {
            AgentRole.SYNTHESISER: [
                {
                    "decision": "revise",
                    "selected_role": "low-traffic",
                    "rationale": "Challenge the direct option.",
                },
                {
                    "decision": "accept",
                    "selected_role": "low-traffic",
                    "rationale": "Revision clears review.",
                },
            ]
        }
    )

    outcome = gate(runtime).evaluate(
        "connection-a-b", facts(), "direct", ["direct", "low-traffic"]
    )

    assert outcome.record.decision == "accept"
    assert outcome.selected_role == "low-traffic"
    assert len(outcome.record.attempts) == 2


def test_no_progress_revision_terminates_as_gap() -> None:
    repeated = {
        "decision": "revise",
        "selected_role": "direct",
        "rationale": "Repeat the same option.",
    }
    runtime = FakeAgentRuntime({AgentRole.SYNTHESISER: [repeated, repeated]})

    outcome = gate(runtime).evaluate(
        "connection-a-b", facts(), "direct", ["direct", "low-traffic"]
    )

    assert outcome.record.decision == "gap"
    assert len(outcome.record.attempts) == 2
    assert "no-progress" in outcome.record.outcome_reason


def test_unresolved_mandatory_failure_cannot_be_overridden() -> None:
    outcome = gate(FakeAgentRuntime()).evaluate(
        "connection-a-b",
        facts(direct="red", low_traffic="red"),
        "direct",
        ["direct"],
    )

    assert outcome.record.decision == "gap"
    assert outcome.record.attempts[0]["deterministic_findings"]
    assert outcome.record.attempts[0]["synthesis"]["decision"] == "gap"


@pytest.mark.live_agent
def test_live_provider_contract() -> None:
    model = os.getenv("SATN_TEST_AGENT_MODEL")
    if not model:
        pytest.skip("SATN_TEST_AGENT_MODEL is not configured")
    agent_config = AgentConfig(
        provider="pydantic-ai",
        model=model,
        max_attempts=1,
        max_requests=4,
        max_tokens=1000,
    )
    outcome = CompilationGate(PydanticAIRuntime(agent_config), agent_config).evaluate(
        "connection-a-b", facts(), "direct", ["direct"]
    )
    assert outcome.record.runtime == "pydantic-ai"
    assert outcome.record.attempts
