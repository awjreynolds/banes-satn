from __future__ import annotations

import os

import pytest

from satn.agents import (
    AgentRole,
    CompilationGate,
    FakeAgentRuntime,
    PydanticAIRuntime,
)
from satn.models import AgentConfig, AgentRecord, DivergenceRecord, TrafficLight


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
        AgentConfig(
            review_statuses=tuple(TrafficLight),
            max_attempts=attempts,
            max_requests=12,
            max_tokens=100,
        ),
    )


def test_agent_review_policy_defaults_to_amber_and_red_and_is_canonical() -> None:
    assert AgentConfig().review_statuses == (TrafficLight.AMBER, TrafficLight.RED)
    assert AgentConfig(review_statuses=["grey", "green", "grey"]).review_statuses == (
        TrafficLight.GREEN,
        TrafficLight.GREY,
    )
    assert AgentConfig(enabled=False).review_statuses == ()
    assert AgentConfig(enabled="false").review_statuses == ()
    with pytest.raises(ValueError, match="enabled: false conflicts"):
        AgentConfig(enabled=False, review_statuses=["amber"])
    config = AgentConfig()
    config.review_statuses = ["grey", "green", "grey"]
    assert config.review_statuses == (TrafficLight.GREEN, TrafficLight.GREY)


def test_review_audit_records_reject_contradictory_execution_state() -> None:
    base_record = {
        "connection_id": "connection-a-b",
        "governing_status": TrafficLight.GREEN,
        "review_policy": (TrafficLight.AMBER,),
        "review_required": False,
        "runtime": "not-invoked",
        "model": "not-invoked",
        "proposal": "{}",
        "critique": "[]",
        "revision": "{}",
        "decision": "accept",
    }
    with pytest.raises(ValueError, match="membership in policy"):
        AgentRecord(**{**base_record, "review_required": True})
    with pytest.raises(ValueError, match="skipped review must have no runtime"):
        AgentRecord(**{**base_record, "runtime": "fake"})
    with pytest.raises(ValueError, match="required review must record"):
        AgentRecord(
            **{
                **base_record,
                "governing_status": TrafficLight.AMBER,
                "review_required": True,
                "runtime": "fake",
            }
        )
    with pytest.raises(ValueError, match="required divergence review"):
        DivergenceRecord(
            connection_id="connection-a-b",
            governing_status=TrafficLight.AMBER,
            review_policy=(TrafficLight.AMBER,),
            review_required=True,
            status="deviation",
            overlap_ratio=0.5,
            explanation="Review was incorrectly omitted.",
        )
    with pytest.raises(ValueError, match="skipped divergence review"):
        DivergenceRecord(
            connection_id="connection-a-b",
            governing_status=TrafficLight.GREEN,
            review_policy=(TrafficLight.AMBER,),
            review_required=False,
            status="match",
            overlap_ratio=1,
            explanation="Deterministic match.",
            resolution_attempts=[{"attempt": 1}],
        )


@pytest.mark.parametrize("status", tuple(TrafficLight))
def test_selected_status_reaches_bounded_agent_review(status: TrafficLight) -> None:
    config = AgentConfig(
        review_statuses=(status,),
        max_attempts=1,
        max_requests=4,
        max_tokens=100,
    )

    outcome = CompilationGate(FakeAgentRuntime(), config).evaluate(
        "connection-a-b",
        facts(direct=status.value),
        "direct",
        ["direct"],
    )

    assert outcome.record.governing_status == status
    assert outcome.record.review_policy == (status,)
    assert outcome.record.review_required is True
    assert outcome.record.usage == {"requests": 4, "tokens": 4}


@pytest.mark.parametrize(
    ("status", "decision"),
    [
        (TrafficLight.GREEN, "accept"),
        (TrafficLight.AMBER, "accept"),
        (TrafficLight.RED, "gap"),
        (TrafficLight.GREY, "accept"),
    ],
)
def test_unselected_status_is_deterministic_and_never_needs_a_runtime(
    status: TrafficLight,
    decision: str,
) -> None:
    outcome = CompilationGate(None, AgentConfig(review_statuses=())).evaluate(
        "connection-a-b",
        facts(direct=status.value),
        "direct",
        ["direct"],
    )

    assert outcome.record.decision == decision
    assert outcome.record.governing_status == status
    assert outcome.record.review_policy == ()
    assert outcome.record.review_required is False
    assert outcome.record.runtime == "not-invoked"
    assert outcome.record.usage == {"requests": 0, "tokens": 0}


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

    outcome = gate(runtime).evaluate("connection-a-b", facts(), "direct", ["direct", "low-traffic"])

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

    outcome = gate(runtime).evaluate("connection-a-b", facts(), "direct", ["direct", "low-traffic"])

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

    outcome = gate(runtime).evaluate("connection-a-b", facts(), "direct", ["direct", "low-traffic"])

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


def test_reviewed_red_candidate_can_be_repaired_to_a_green_alternative() -> None:
    outcome = CompilationGate(
        FakeAgentRuntime(),
        AgentConfig(review_statuses=(TrafficLight.RED,)),
    ).evaluate(
        "connection-a-b",
        facts(direct="red", low_traffic="green"),
        "direct",
        ["direct", "low-traffic"],
    )

    assert outcome.record.governing_status == TrafficLight.RED
    assert outcome.record.review_required is True
    assert outcome.record.decision == "accept"
    assert outcome.selected_role == "low-traffic"
    assert len(outcome.record.attempts) == 2


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
