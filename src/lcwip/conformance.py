"""Deterministic conformance evaluation through the public LCWIP seam."""

from __future__ import annotations

from collections.abc import Iterable

from lcwip.models import ConformanceResult, GuidanceProfile, PlanRelease, RequirementAssessment


def evaluate_conformance(
    profile: GuidanceProfile, assessments: Iterable[RequirementAssessment]
) -> ConformanceResult:
    """Evaluate one immutable profile without inferring missing evidence as compliance."""
    return ConformanceResult.from_evaluation(profile, assessments)


def evaluate_release_conformance(
    release: PlanRelease,
    profiles: Iterable[GuidanceProfile],
    assessments: Iterable[RequirementAssessment],
) -> ConformanceResult:
    """Evaluate a release only against the exact profile fingerprint it recorded.

    A newer profile can coexist in the registry, but cannot rewrite the
    historical basis of a release that was already published or superseded.
    """
    release = PlanRelease.model_validate(release.model_dump())
    matches = [profile for profile in profiles if profile.profile_id == release.profile_id]
    if len(matches) != 1:
        raise ValueError(
            f"release {release.release_id} requires exactly one matching Guidance Profile"
        )
    profile = matches[0]
    if profile.fingerprint != release.profile_fingerprint:
        raise ValueError(
            f"release {release.release_id} Guidance Profile fingerprint does not match"
        )
    return evaluate_conformance(profile, assessments)
