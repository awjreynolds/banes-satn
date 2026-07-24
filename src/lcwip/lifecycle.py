"""Human-gated LCWIP release lifecycle transitions."""

from __future__ import annotations

from lcwip.models import (
    PERMITTED_LIFECYCLE_TRANSITIONS,
    ExternalDecisionRecord,
    LifecycleState,
    LifecycleTransition,
    PlanRelease,
    TransitionGate,
)


def transition_release(
    release: PlanRelease,
    target: LifecycleState,
    *,
    gate: TransitionGate | None = None,
    external_decision: ExternalDecisionRecord | None = None,
) -> PlanRelease:
    """Return a new release state only after the required named human gate."""
    if target not in PERMITTED_LIFECYCLE_TRANSITIONS[release.lifecycle_state]:
        raise ValueError(
            f"transition from {release.lifecycle_state.value} to {target.value} is not permitted"
        )
    if gate is None:
        raise ValueError("a named human transition gate is required")
    gate = TransitionGate.model_validate(gate)
    if target is LifecycleState.ADOPTED:
        if external_decision is not None:
            external_decision = ExternalDecisionRecord.model_validate(external_decision)
        if external_decision is None:
            raise ValueError("adoption requires an independently verified external decision record")
    elif external_decision is not None:
        raise ValueError("external decision records are only permitted for adoption")
    retained_external_decision = (
        external_decision if target is LifecycleState.ADOPTED else release.external_decision
    )
    return PlanRelease.model_validate(
        release.model_dump()
        | {
            "lifecycle_state": target,
            "claims": (target.value,),
            "transition_history": (
                *release.transition_history,
                LifecycleTransition(from_state=release.lifecycle_state, to_state=target, gate=gate),
            ),
            "external_decision": retained_external_decision,
        }
    )
