"""Typed, provider-neutral and bounded agent compilation gate."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from satn.models import (
    AgentAttempt,
    AgentConfig,
    AgentRecord,
    AgentReviewDecision,
    TrafficLight,
)
from satn.models import (
    AgentCritique as RoleReview,
)
from satn.models import (
    AgentFinding as ChallengeFinding,
)
from satn.models import (
    AgentProposal as RouteProposal,
)
from satn.models import (
    AgentSynthesis as RouteSynthesis,
)


class AgentRole(StrEnum):
    PROPOSER = "proposer"
    EVIDENCE_CRITIC = "evidence-critic"
    NETWORK_RED_TEAM = "network-red-team"
    SYNTHESISER = "synthesiser"
    DIVERGENCE = "divergence"


class EvidenceFacts(BaseModel):
    model_config = ConfigDict(frozen=True)

    from_place: str
    to_place: str
    target_role: str | None = None
    selection_reason: str = ""
    evidence_ids: tuple[str, ...] = ()


class EvidencePacket(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str = "1"
    connection_id: str
    governing_status: TrafficLight
    current_role: str | None
    available_roles: tuple[str, ...]
    facts: EvidenceFacts
    deterministic_findings: tuple[ChallengeFinding, ...]
    prior_feedback: tuple[ChallengeFinding, ...] = ()
    attempt: int


class SynthesisInput(BaseModel):
    packet: EvidencePacket
    proposal: RouteProposal
    critique: RoleReview
    red_team: RoleReview


class DivergenceInput(BaseModel):
    connection_id: str
    status: str
    atm_feature_ids: list[str]
    overlap_ratio: float
    attempt: int = 1


class DivergenceAssessment(BaseModel):
    explanation: str
    resolution: str
    resolved: bool


@dataclass
class RuntimeReply:
    output: BaseModel
    tokens: int = 0


class AgentRuntime(ABC):
    """Provider-neutral adapter interface. Implementations never mutate compiled state."""

    name = "runtime"
    model = "unknown"

    @abstractmethod
    def run(
        self,
        role: AgentRole,
        payload: BaseModel,
        output_type: type[BaseModel],
    ) -> RuntimeReply:
        """Return a response validated against ``output_type``."""


class AgentRuntimeProvider:
    """Materialise one shared Agent Runtime only when a selected status needs it."""

    def __init__(self, factory: Callable[[], AgentRuntime]):
        self._factory = factory
        self._runtime: AgentRuntime | None = None
        self._lock = Lock()

    def get(self) -> AgentRuntime:
        if self._runtime is None:
            with self._lock:
                if self._runtime is None:
                    self._runtime = self._factory()
        return self._runtime


AgentRuntimeSource = AgentRuntime | AgentRuntimeProvider | None


def materialize_agent_runtime(source: AgentRuntimeSource) -> AgentRuntime:
    if isinstance(source, AgentRuntime):
        return source
    if isinstance(source, AgentRuntimeProvider):
        return source.get()
    raise RuntimeError("agent review is required, but no runtime exists")


class FakeAgentRuntime(AgentRuntime):
    """Deterministic adapter with optional scripted responses for contract tests."""

    name = "fake"
    model = "deterministic-roles-v1"

    def __init__(self, scripts: dict[AgentRole, list[object]] | None = None):
        self.scripts = defaultdict(list, scripts or {})

    def run(
        self,
        role: AgentRole,
        payload: BaseModel,
        output_type: type[BaseModel],
    ) -> RuntimeReply:
        if self.scripts[role]:
            scripted = self.scripts[role].pop(0)
            if isinstance(scripted, Exception):
                raise scripted
            return RuntimeReply(output_type.model_validate(scripted), tokens=1)
        output = self._default(role, payload)
        return RuntimeReply(output_type.model_validate(output), tokens=1)

    def _default(self, role: AgentRole, payload: BaseModel) -> dict[str, object]:
        if role == AgentRole.DIVERGENCE:
            divergence = DivergenceInput.model_validate(payload)
            return {
                "explanation": (
                    f"{divergence.status.title()} identified from the governed geometry comparison."
                ),
                "resolution": (
                    "No correction is required."
                    if divergence.status == "match"
                    else "Retain for red-team inspection; agreement is not assumed correct."
                ),
                "resolved": divergence.status == "match",
            }
        if role == AgentRole.PROPOSER:
            packet = EvidencePacket.model_validate(payload)
            return {
                "selected_role": packet.current_role,
                "rationale": "Use the best current OSM alignment under the governed rules.",
                "evidence_ids": ["osm-network", *packet.facts.evidence_ids],
            }
        if role in {AgentRole.EVIDENCE_CRITIC, AgentRole.NETWORK_RED_TEAM}:
            packet = EvidencePacket.model_validate(payload)
            findings = [finding.model_dump() for finding in packet.deterministic_findings]
            return {
                "summary": "Mandatory findings remain." if findings else "No blocking finding.",
                "findings": findings,
            }
        synthesis = SynthesisInput.model_validate(payload)
        findings = [*synthesis.critique.findings, *synthesis.red_team.findings]
        blocking = [finding for finding in findings if finding.severity == "blocking"]
        if not blocking:
            return {
                "decision": "accept",
                "selected_role": synthesis.proposal.selected_role,
                "rationale": "Proposal passes deterministic and adversarial review.",
            }
        alternatives = [
            role
            for role in synthesis.packet.available_roles
            if role != synthesis.packet.current_role
        ]
        return {
            "decision": "revise" if alternatives else "gap",
            "selected_role": alternatives[0] if alternatives else None,
            "rationale": (
                "Try an untested alignment." if alternatives else "No viable revision remains."
            ),
        }


class PydanticAIRuntime(AgentRuntime):
    """Pydantic AI adapter configured solely by model name and environment credentials."""

    name = "pydantic-ai"

    def __init__(self, config: AgentConfig):
        if not config.model:
            raise ValueError("a non-fake agent provider requires agent.model")
        self.model = config.model
        self.max_tokens = config.max_tokens

    def run(
        self,
        role: AgentRole,
        payload: BaseModel,
        output_type: type[BaseModel],
    ) -> RuntimeReply:
        from pydantic_ai import Agent
        from pydantic_ai.usage import UsageLimits

        agent = Agent(
            self.model,
            output_type=output_type,
            instructions=_ROLE_INSTRUCTIONS[role],
            model_settings={"max_tokens": self.max_tokens},
            retries=1,
        )
        result = agent.run_sync(
            payload.model_dump_json(),
            usage_limits=UsageLimits(total_tokens_limit=self.max_tokens, request_limit=2),
        )
        usage = result.usage()
        return RuntimeReply(result.output, tokens=int(usage.total_tokens or 0))


@dataclass
class GateOutcome:
    record: AgentRecord
    selected_role: str | None


class CompilationGate:
    def __init__(self, runtime: AgentRuntimeSource, config: AgentConfig):
        self.runtime_source = runtime
        self.config = config

    def evaluate(
        self,
        connection_id: str,
        facts: dict[str, Any],
        initial_role: str | None,
        available_roles: list[str],
        *,
        governing_criterion: str,
        governing_status: TrafficLight,
        deterministic_decision: Literal["accept", "gap"] = "accept",
    ) -> GateOutcome:
        review = self.config.review_decision(governing_status)
        deterministic_outcome = deterministic_decision
        if not review.review_required:
            if governing_status == TrafficLight.RED:
                deterministic_outcome = "gap"
            reason = (
                "Deterministic Red prevents this connection entering the network; "
                "agent review was skipped by policy."
                if governing_status == TrafficLight.RED
                else f"Deterministic {governing_status.value.title()} decision applied; "
                "agent review was skipped by policy."
            )
            return GateOutcome(
                AgentRecord(
                    connection_id=connection_id,
                    governing_criterion=governing_criterion,
                    **review.model_dump(),
                    runtime="not-invoked",
                    model="not-invoked",
                    decision=deterministic_outcome,
                    selected_role=initial_role,
                    outcome_reason=reason,
                    usage={"requests": 0, "tokens": 0},
                ),
                initial_role,
            )

        runtime = self._runtime()
        attempts: list[AgentAttempt] = []
        feedback: list[ChallengeFinding] = []
        current_role = initial_role
        requests = 0
        tokens = 0
        seen: set[str] = set()
        outcome_reason = "Compilation gate exhausted its bounded attempts."

        for attempt_number in range(1, self.config.max_attempts + 1):
            findings = _deterministic_findings(facts, current_role)
            packet = EvidencePacket(
                connection_id=connection_id,
                governing_status=governing_status,
                current_role=current_role,
                available_roles=tuple(available_roles),
                facts=EvidenceFacts.model_validate(
                    {
                        key: value
                        for key, value in facts.items()
                        if key not in {"checks_by_role", "governing_status"}
                    }
                ),
                deterministic_findings=tuple(findings),
                prior_feedback=tuple(feedback),
                attempt=attempt_number,
            )
            try:
                proposal, used = self._call(
                    AgentRole.PROPOSER, packet, RouteProposal, requests, tokens
                )
                requests += 1
                tokens += used
                proposed_role = proposal.selected_role
                if proposed_role not in available_roles:
                    packet = packet.model_copy(
                        update={
                            "deterministic_findings": (
                                *packet.deterministic_findings,
                                ChallengeFinding(
                                    code="unknown-alignment",
                                    severity="blocking",
                                    message="The proposal selected an unavailable alignment.",
                                ),
                            )
                        }
                    )
                else:
                    current_role = proposed_role
                    packet = packet.model_copy(
                        update={
                            "current_role": current_role,
                            "deterministic_findings": tuple(
                                _deterministic_findings(facts, current_role)
                            ),
                        }
                    )
                critique, used = self._call(
                    AgentRole.EVIDENCE_CRITIC, packet, RoleReview, requests, tokens
                )
                requests += 1
                tokens += used
                red_team, used = self._call(
                    AgentRole.NETWORK_RED_TEAM, packet, RoleReview, requests, tokens
                )
                requests += 1
                tokens += used
                synthesis_input = SynthesisInput(
                    packet=packet,
                    proposal=proposal,
                    critique=critique,
                    red_team=red_team,
                )
                synthesis, used = self._call(
                    AgentRole.SYNTHESISER,
                    synthesis_input,
                    RouteSynthesis,
                    requests,
                    tokens,
                )
                requests += 1
                tokens += used
            except (ValidationError, ValueError, RuntimeError) as error:
                requests += 1
                schema_finding = ChallengeFinding(
                    code="agent-schema-error",
                    severity="blocking",
                    message=str(error),
                )
                attempts.append(
                    AgentAttempt(
                        attempt=attempt_number,
                        selected_role=current_role,
                        findings=[schema_finding],
                        decision="retry",
                    )
                )
                fingerprint = json.dumps(
                    attempts[-1].model_dump(exclude={"attempt"}, mode="json"),
                    sort_keys=True,
                )
                if fingerprint in seen:
                    outcome_reason = "Agent output made no progress after schema rejection."
                    break
                seen.add(fingerprint)
                feedback = [schema_finding]
                continue

            all_findings = [*packet.deterministic_findings, *critique.findings, *red_team.findings]
            attempt = AgentAttempt(
                attempt=attempt_number,
                proposal=proposal,
                critique=critique,
                red_team=red_team,
                synthesis=synthesis,
                deterministic_findings=list(packet.deterministic_findings),
            )
            attempts.append(attempt)
            mandatory_pass = not any(finding.severity == "blocking" for finding in all_findings)
            if (
                synthesis.decision == "accept"
                and mandatory_pass
                and deterministic_outcome == "accept"
            ):
                return GateOutcome(
                    _record(
                        runtime,
                        connection_id,
                        governing_criterion,
                        "accept",
                        current_role,
                        "All mandatory checks and bounded agent reviews passed.",
                        attempts,
                        requests,
                        tokens,
                        review,
                    ),
                    current_role,
                )
            if synthesis.decision == "accept" and deterministic_outcome == "gap":
                outcome_reason = (
                    "Bounded review completed; the deterministic gap remains authoritative."
                )
                break
            fingerprint = json.dumps(
                attempt.model_dump(exclude={"attempt"}, mode="json"),
                sort_keys=True,
            )
            if fingerprint in seen:
                outcome_reason = "Compilation gate stopped after a no-progress revision."
                break
            seen.add(fingerprint)
            feedback = all_findings
            if synthesis.decision != "revise" or synthesis.selected_role not in available_roles:
                outcome_reason = synthesis.rationale
                break
            current_role = synthesis.selected_role

        return GateOutcome(
            _record(
                runtime,
                connection_id,
                governing_criterion,
                "gap",
                current_role,
                outcome_reason,
                attempts,
                requests,
                tokens,
                review,
            ),
            current_role,
        )

    def _call(
        self,
        role: AgentRole,
        payload: BaseModel,
        output_type: type[BaseModel],
        requests: int,
        tokens: int,
    ) -> tuple[Any, int]:
        if requests >= self.config.max_requests:
            raise RuntimeError("agent request limit exhausted")
        if tokens >= self.config.max_tokens:
            raise RuntimeError("agent token limit exhausted")
        reply = self._runtime().run(role, payload, output_type)
        if tokens + reply.tokens > self.config.max_tokens:
            raise RuntimeError("agent token limit exhausted")
        return reply.output, reply.tokens

    def _runtime(self) -> AgentRuntime:
        return materialize_agent_runtime(self.runtime_source)


def runtime_for(config: AgentConfig) -> AgentRuntime:
    if config.provider == "fake":
        return FakeAgentRuntime()
    return PydanticAIRuntime(config)


def _deterministic_findings(
    facts: dict[str, Any],
    role: str | None,
) -> list[ChallengeFinding]:
    checks = facts.get("checks_by_role", {}).get(role, {}) if role else {}
    return [
        ChallengeFinding(
            code=f"deterministic-{name}",
            severity="blocking" if status == "red" else "advisory",
            message=f"Deterministic criterion {name} is {status}.",
            evidence_ids=["osm-network"],
        )
        for name, status in checks.items()
        if status in {"red", "amber"}
    ]


def _record(
    runtime: AgentRuntime,
    connection_id: str,
    governing_criterion: str,
    decision: str,
    selected_role: str | None,
    reason: str,
    attempts: list[AgentAttempt],
    requests: int,
    tokens: int,
    review: AgentReviewDecision,
) -> AgentRecord:
    latest = attempts[-1] if attempts else None
    return AgentRecord(
        connection_id=connection_id,
        governing_criterion=governing_criterion,
        **review.model_dump(),
        runtime=runtime.name,
        model=runtime.model,
        proposal=latest.proposal if latest else None,
        critique=latest.critique if latest else None,
        revision=latest.synthesis if latest else None,
        decision=decision,
        selected_role=selected_role,
        outcome_reason=reason,
        attempts=attempts,
        usage={"requests": requests, "tokens": tokens},
    )


_ROLE_INSTRUCTIONS = {
    AgentRole.PROPOSER: (
        "Select and justify one available OSM alignment. Return only the typed output."
    ),
    AgentRole.EVIDENCE_CRITIC: "Challenge evidence sufficiency. Preserve deterministic findings.",
    AgentRole.NETWORK_RED_TEAM: "Try to falsify continuity, endpoint and network claims.",
    AgentRole.SYNTHESISER: (
        "Accept only when mandatory findings are clear; otherwise revise or gap."
    ),
    AgentRole.DIVERGENCE: (
        "Explain the ATM comparison status, challenge both sources and attempt a bounded "
        "resolution."
    ),
}
