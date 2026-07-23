from __future__ import annotations

import hashlib
import time

import pytest
from pydantic import BaseModel

from satn.agents import (
    AgentDecisionRequired,
    AgentDecisionResolver,
    AgentRole,
    AgentRuntime,
    AgentRuntimeProvider,
    CompilationGate,
    FakeAgentRuntime,
    RuntimeReply,
)
from satn.models import (
    AgentConfig,
    AgentDecisionLedger,
    AgentDecisionResponse,
    AgentRuntimeDecisionResponse,
    TrafficLight,
)


def _facts(status: str = "amber") -> dict[str, object]:
    return {
        "from_place": "a",
        "to_place": "b",
        "evidence_ids": ["edge-1"],
        "checks_by_role": {
            "direct": {
                "endpoints": status,
                "continuity": status,
                "bidirectional": status,
                "distance": "green",
            }
        },
    }


def _config(**updates: object) -> AgentConfig:
    values = {
        "response_mode": "direct-runtime",
        "review_statuses": (TrafficLight.AMBER,),
        "max_attempts": 1,
        "max_requests": 1,
        "max_tokens": 100,
        "deadline_seconds": 0.05,
    }
    values.update(updates)
    return AgentConfig(**values)


def _evaluate(runtime: AgentRuntime | AgentRuntimeProvider, config: AgentConfig | None = None):
    return CompilationGate(runtime, config or _config()).evaluate(
        "connection-a-b",
        _facts(),
        "direct",
        ["direct"],
        governing_criterion="continuity",
        governing_status=TrafficLight.AMBER,
    )


class _SleepingRuntime(AgentRuntime):
    name = "sleeping"
    model = "test"

    def run(
        self,
        role: AgentRole,
        payload: BaseModel,
        output_type: type[BaseModel],
    ) -> RuntimeReply:
        time.sleep(1)
        raise AssertionError("the deadline did not interrupt the runtime")


class _ExceptionSwallowingRuntime(AgentRuntime):
    name = "exception-swallowing"
    model = "test"

    def run(
        self,
        role: AgentRole,
        payload: BaseModel,
        output_type: type[BaseModel],
    ) -> RuntimeReply:
        try:
            time.sleep(1)
        except Exception:
            request_id = payload.model_dump()["request_id"]
            return RuntimeReply(
                output_type.model_validate(
                    {"request_id": request_id, "choice_id": "1"}
                ),
                tokens=1,
            )
        raise AssertionError("the deadline did not interrupt the runtime")


class _UnavailableRuntime(AgentRuntime):
    name = "unavailable"
    model = "test"

    def run(
        self,
        role: AgentRole,
        payload: BaseModel,
        output_type: type[BaseModel],
    ) -> RuntimeReply:
        raise RuntimeError("provider unavailable")


class _ChoiceRuntime(AgentRuntime):
    name = "choice"
    model = "test"

    def __init__(self, choice_id: str):
        self.choice_id = choice_id

    def run(
        self,
        role: AgentRole,
        payload: BaseModel,
        output_type: type[BaseModel],
    ) -> RuntimeReply:
        request_id = payload.model_dump()["request_id"]
        return RuntimeReply(
            output_type.model_validate(
                {"request_id": request_id, "choice_id": self.choice_id}
            ),
            tokens=1,
        )


def test_direct_runtime_output_is_only_request_and_choice_identifiers() -> None:
    response = AgentRuntimeDecisionResponse(request_id="request-1", choice_id="1")
    assert response.model_dump() == {"request_id": "request-1", "choice_id": "1"}
    with pytest.raises(ValueError, match="Extra inputs"):
        AgentRuntimeDecisionResponse(
            request_id="request-1",
            choice_id="1",
            action={"kind": "select-network-role"},
        )


def test_direct_runtime_selects_an_offered_choice_and_records_provenance() -> None:
    outcome = _evaluate(FakeAgentRuntime())

    assert outcome.record.decision == "accept"
    assert outcome.record.selected_choice_id == "1"
    assert outcome.record.mapped_action is not None
    assert outcome.record.mapped_action.kind == "select-network-role"
    assert outcome.record.responder_mode == "direct-runtime"
    assert outcome.record.runtime == "fake"
    assert outcome.record.model == "deterministic-choices-v1"
    assert outcome.record.usage == {"requests": 1, "tokens": 1}
    assert outcome.record.choice_validation == "accepted"
    assert outcome.record.attempts == []
    assert outcome.record.proposal is None


def test_direct_runtime_unknown_choice_returns_the_same_non_waiting_request() -> None:
    with pytest.raises(AgentDecisionRequired) as raised:
        _evaluate(_ChoiceRuntime("99"))

    assert raised.value.validation == "unknown-choice"
    assert [choice.choice_id for choice in raised.value.request.choices] == [
        "1",
        "2",
        "3",
        "terminate",
    ]
    assert raised.value.applied_records == []


def test_direct_runtime_request_mismatch_is_rejected() -> None:
    runtime = FakeAgentRuntime(
        {AgentRole.DECISION: [{"request_id": "another-request", "choice_id": "1"}]}
    )

    with pytest.raises(AgentDecisionRequired) as raised:
        _evaluate(runtime)

    assert raised.value.validation == "response-for-another-request"


def test_direct_runtime_malformed_output_returns_decision_required() -> None:
    runtime = FakeAgentRuntime({AgentRole.DECISION: [{"invalid": "record"}]})

    with pytest.raises(AgentDecisionRequired) as raised:
        _evaluate(runtime)

    assert raised.value.validation == "runtime-schema-failure"


def test_direct_runtime_unavailability_returns_decision_required() -> None:
    with pytest.raises(AgentDecisionRequired) as raised:
        _evaluate(_UnavailableRuntime())

    assert raised.value.validation == "runtime-unavailable"


def test_direct_runtime_deadline_interrupts_without_waiting() -> None:
    started = time.perf_counter()

    with pytest.raises(AgentDecisionRequired) as raised:
        _evaluate(_SleepingRuntime())

    assert time.perf_counter() - started < 0.5
    assert raised.value.validation == "runtime-timeout"


def test_direct_runtime_cannot_swallow_the_deadline_as_an_ordinary_exception() -> None:
    started = time.perf_counter()

    with pytest.raises(AgentDecisionRequired) as raised:
        _evaluate(_ExceptionSwallowingRuntime())

    assert time.perf_counter() - started < 0.5
    assert raised.value.validation == "runtime-timeout"


def test_direct_runtime_token_limit_returns_decision_required() -> None:
    runtime = FakeAgentRuntime(tokens_per_reply=101)

    with pytest.raises(AgentDecisionRequired) as raised:
        _evaluate(runtime)

    assert raised.value.validation == "runtime-token-limit"


def test_direct_runtime_malformed_usage_returns_decision_required() -> None:
    runtime = FakeAgentRuntime(tokens_per_reply="not-an-integer")

    with pytest.raises(AgentDecisionRequired) as raised:
        _evaluate(runtime)

    assert raised.value.validation == "runtime-schema-failure"


def test_direct_runtime_cannot_waive_a_mandatory_red_invariant() -> None:
    config = _config(review_statuses=(TrafficLight.RED,))
    with pytest.raises(AgentDecisionRequired) as raised:
        CompilationGate(FakeAgentRuntime(), config).evaluate(
            "connection-a-b",
            _facts("red"),
            "direct",
            ["direct"],
            governing_criterion="continuity",
            governing_status=TrafficLight.RED,
        )

    assert raised.value.validation == "mandatory-red"


def test_caller_ledger_uses_the_same_validation_without_invoking_direct_runtime() -> None:
    config = _config()
    with pytest.raises(AgentDecisionRequired) as first:
        CompilationGate(None, config).evaluate(
            "connection-a-b",
            _facts(),
            "direct",
            ["direct"],
            governing_criterion="continuity",
            governing_status=TrafficLight.AMBER,
        )
    request = first.value.request
    resolver = AgentDecisionResolver(
        AgentDecisionLedger(
            responses=(
                AgentDecisionResponse(
                    request_id=request.request_id,
                    dependency_fingerprint=request.dependency_fingerprint,
                    choice_id="1",
                ),
            )
        ),
        hashlib.sha256(config.model_dump_json().encode()).hexdigest(),
    )
    constructions = 0

    def factory() -> AgentRuntime:
        nonlocal constructions
        constructions += 1
        return FakeAgentRuntime()

    outcome = CompilationGate(
        AgentRuntimeProvider(factory),
        config,
        decision_resolver=resolver,
    ).evaluate(
        "connection-a-b",
        _facts(),
        "direct",
        ["direct"],
        governing_criterion="continuity",
        governing_status=TrafficLight.AMBER,
    )

    assert outcome.record.responder_mode == "caller"
    assert constructions == 0


def test_caller_mode_never_invokes_an_accidentally_supplied_runtime() -> None:
    constructions = 0

    def factory() -> AgentRuntime:
        nonlocal constructions
        constructions += 1
        return FakeAgentRuntime()

    with pytest.raises(AgentDecisionRequired) as raised:
        _evaluate(
            AgentRuntimeProvider(factory),
            _config(response_mode="caller"),
        )

    assert raised.value.validation == "response-required"
    assert constructions == 0


def test_unselected_status_does_not_construct_the_direct_runtime() -> None:
    constructions = 0

    def factory() -> AgentRuntime:
        nonlocal constructions
        constructions += 1
        return FakeAgentRuntime()

    outcome = CompilationGate(
        AgentRuntimeProvider(factory),
        _config(),
    ).evaluate(
        "connection-a-b",
        _facts("green"),
        "direct",
        ["direct"],
        governing_criterion="continuity",
        governing_status=TrafficLight.GREEN,
    )

    assert outcome.record.review_required is False
    assert constructions == 0
