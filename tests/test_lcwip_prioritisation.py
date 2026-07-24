from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_lcwip_intervention_packages import build_fixture as build_interventions
from typer.testing import CliRunner

from lcwip.cli import app
from lcwip.prioritisation import (
    ApprovedCriteria,
    CriteriaDirective,
    CriterionView,
    HorizonDefinition,
    MeasureDefinition,
    MeasureObservation,
    MissingDataRule,
    ProgrammeDecision,
    ProgrammeDecisionKind,
    ScenarioDefinition,
    SensitivityCase,
    TransformKind,
    build_prioritisation,
    validate_prioritisation_bundle,
)


def directive() -> CriteriaDirective:
    return CriteriaDirective(
        directive_id="cabinet-prioritisation-criteria",
        authority_name="B&NES Cabinet",
        approved_on=date(2026, 2, 1),
        rationale="Council-approved analytical criteria for scenario comparison.",
        evidence_uri="https://example.test/council/directive",
    )


def criteria() -> ApprovedCriteria:
    return ApprovedCriteria(
        criteria_id="banes-prioritisation-criteria",
        version="1.0",
        directive=directive(),
        measures=(
            MeasureDefinition(
                measure_id="effectiveness",
                view=CriterionView.EFFECTIVENESS_BENEFIT,
                transform=TransformKind.LINEAR_HIGHER_BETTER,
                minimum=0,
                maximum=100,
                base_weight=1,
                missing_data=MissingDataRule.REVIEW_REQUIRED,
                methodology="Governed strategic effectiveness assessment.",
            ),
            MeasureDefinition(
                measure_id="equality",
                view=CriterionView.POLICY_EQUALITY,
                transform=TransformKind.LINEAR_HIGHER_BETTER,
                minimum=0,
                maximum=100,
                base_weight=1,
                missing_data=MissingDataRule.REVIEW_REQUIRED,
                methodology="Governed equality contribution assessment.",
            ),
            MeasureDefinition(
                measure_id="deliverability",
                view=CriterionView.DELIVERABILITY_COST,
                transform=TransformKind.LINEAR_HIGHER_BETTER,
                minimum=0,
                maximum=100,
                base_weight=1,
                missing_data=MissingDataRule.REVIEW_REQUIRED,
                methodology="Governed deliverability and cost assessment.",
            ),
        ),
        horizons=(
            HorizonDefinition(
                phase="short",
                start_year=2026,
                end_year=2028,
                maximum_upper_cost=500_000,
                rationale="Early enabling and lower-cost concepts.",
            ),
            HorizonDefinition(
                phase="medium",
                start_year=2029,
                end_year=2032,
                maximum_upper_cost=750_000,
                rationale="Developed concepts after enabling work.",
            ),
            HorizonDefinition(
                phase="long",
                start_year=2033,
                end_year=2035,
                maximum_upper_cost=1_000_000,
                rationale="Longer-term or dependency-constrained concepts.",
            ),
        ),
    )


def observations(*, omit: tuple[str, str] | None = None) -> tuple[MeasureObservation, ...]:
    values = {
        ("concept-crossing", "effectiveness"): 90,
        ("concept-crossing", "equality"): 30,
        ("concept-crossing", "deliverability"): 80,
        ("concept-footway", "effectiveness"): 60,
        ("concept-footway", "equality"): 95,
        ("concept-footway", "deliverability"): 55,
    }
    return tuple(
        MeasureObservation(
            observation_id=f"measure-{intervention_id}-{measure_id}",
            intervention_id=intervention_id,
            measure_id=measure_id,
            value=value,
            evidence_ids=(
                "cycling-deficiency-evidence"
                if intervention_id == "concept-crossing"
                else "walking-deficiency-evidence",
            ),
            source_kind="observed" if measure_id != "effectiveness" else "modelled",
            methodology_version="fixture-1.0",
        )
        for (intervention_id, measure_id), value in sorted(values.items())
        if (intervention_id, measure_id) != omit
    )


def scenarios() -> tuple[ScenarioDefinition, ...]:
    return (
        ScenarioDefinition(
            scenario_id="effectiveness-led",
            name="Effectiveness-led analytical scenario",
            directive_id="cabinet-prioritisation-criteria",
            weight_overrides={
                "effectiveness": 3,
                "equality": 1,
                "deliverability": 1,
            },
            quick_win_max_upper_cost=500_000,
            rules=("Respect dependencies.", "Do not infer missing measures."),
        ),
        ScenarioDefinition(
            scenario_id="equality-led",
            name="Equality-led analytical scenario",
            directive_id="cabinet-prioritisation-criteria",
            weight_overrides={
                "effectiveness": 1,
                "equality": 4,
                "deliverability": 1,
            },
            quick_win_max_upper_cost=500_000,
            rules=("Respect dependencies.", "Do not infer missing measures."),
        ),
    )


def sensitivities() -> tuple[SensitivityCase, ...]:
    return (
        SensitivityCase(
            case_id="balanced-weights",
            base_scenario_id="effectiveness-led",
            directive_id="cabinet-prioritisation-criteria",
            weight_overrides={
                "effectiveness": 1,
                "equality": 1,
                "deliverability": 1,
            },
            observation_overrides={},
            rationale="Plausible equal-weight sensitivity.",
        ),
        SensitivityCase(
            case_id="lower-crossing-effect",
            base_scenario_id="effectiveness-led",
            directive_id="cabinet-prioritisation-criteria",
            weight_overrides={},
            observation_overrides={"concept-crossing:effectiveness": 55},
            rationale="Tests model-input uncertainty.",
        ),
    )


def test_scenarios_are_deterministic_decomposed_and_surface_policy_conflict(
    tmp_path: Path,
) -> None:
    intervention_bundle = build_interventions(tmp_path / "interventions")
    first = build_prioritisation(
        criteria=criteria(),
        intervention_bundle=intervention_bundle,
        output_dir=tmp_path / "first",
        analysis_id="banes-prioritisation",
        observations=observations(),
        scenarios=scenarios(),
        sensitivity_cases=sensitivities(),
    )
    second = build_prioritisation(
        criteria=criteria(),
        intervention_bundle=intervention_bundle,
        output_dir=tmp_path / "second",
        analysis_id="banes-prioritisation",
        observations=observations(),
        scenarios=scenarios(),
        sensitivity_cases=sensitivities(),
    )
    one = validate_prioritisation_bundle(first)
    two = validate_prioritisation_bundle(second)
    assert one.analysis_fingerprint == two.analysis_fingerprint
    effectiveness = next(
        item for item in one.scenarios if item.scenario_id == "effectiveness-led"
    )
    equality = next(item for item in one.scenarios if item.scenario_id == "equality-led")
    assert effectiveness.items[0].intervention_id == "concept-crossing"
    assert equality.items[0].intervention_id == "concept-footway"
    assert one.policy_trade_offs
    assert all(
        item.measure_results and item.view_results
        for scenario in one.scenarios
        for item in scenario.items
    )
    cli = CliRunner().invoke(app, ["prioritisation", "validate", str(first)])
    assert cli.exit_code == 0, cli.output
    assert one.analysis_fingerprint in cli.output


def test_missing_evidence_never_becomes_zero_or_average(tmp_path: Path) -> None:
    bundle = build_interventions(tmp_path / "interventions")
    output = build_prioritisation(
        criteria=criteria(),
        intervention_bundle=bundle,
        output_dir=tmp_path / "output",
        analysis_id="missing-data",
        observations=observations(omit=("concept-footway", "equality")),
        scenarios=scenarios(),
        sensitivity_cases=(),
    )
    manifest = validate_prioritisation_bundle(output)
    footway = next(
        item
        for item in manifest.scenarios[0].items
        if item.intervention_id == "concept-footway"
    )
    assert footway.rank is None
    assert footway.phase is None
    assert footway.missing_measure_ids == ("equality",)
    assert any(
        request.intervention_id == "concept-footway"
        and request.measure_id == "equality"
        for request in manifest.evidence_requests
    )


def test_sensitivity_reports_rank_and_phase_stability(tmp_path: Path) -> None:
    bundle = build_interventions(tmp_path / "interventions")
    output = build_prioritisation(
        criteria=criteria(),
        intervention_bundle=bundle,
        output_dir=tmp_path / "output",
        analysis_id="sensitivity",
        observations=observations(),
        scenarios=scenarios(),
        sensitivity_cases=sensitivities(),
    )
    manifest = validate_prioritisation_bundle(output)
    assert {item.case_id for item in manifest.sensitivity_results} == {
        "balanced-weights",
        "lower-crossing-effect",
    }
    assert all(item.rank_changes for item in manifest.sensitivity_results)
    assert all(item.phase_changes is not None for item in manifest.sensitivity_results)


def test_dependencies_force_enabling_work_before_dependent_concepts(
    tmp_path: Path,
) -> None:
    bundle = build_interventions(tmp_path / "interventions")
    manifest = validate_prioritisation_bundle(
        build_prioritisation(
            criteria=criteria(),
            intervention_bundle=bundle,
            output_dir=tmp_path / "output",
            analysis_id="dependency-scheduling",
            observations=observations(),
            scenarios=(scenarios()[1],),
            sensitivity_cases=(),
        )
    )
    items = {item.intervention_id: item for item in manifest.scenarios[0].items}
    assert items["concept-crossing"].enabling_work
    assert items["concept-crossing"].phase_index <= items["concept-footway"].phase_index


def test_dominance_and_ties_are_explicit_and_deterministic(tmp_path: Path) -> None:
    bundle = build_interventions(tmp_path / "interventions")
    tie_observations = tuple(
        item.model_copy(update={"value": 50}) for item in observations()
    )
    tied = validate_prioritisation_bundle(
        build_prioritisation(
            criteria=criteria(),
            intervention_bundle=bundle,
            output_dir=tmp_path / "tied",
            analysis_id="tied-scenario",
            observations=tie_observations,
            scenarios=(scenarios()[0],),
            sensitivity_cases=(),
        )
    ).scenarios[0]
    assert [item.intervention_id for item in tied.items] == [
        "concept-crossing",
        "concept-footway",
    ]
    assert tied.items[0].total_score == tied.items[1].total_score
    assert tied.items[0].rank == tied.items[1].rank == 1
    assert tied.items[0].tied_with_intervention_ids == ("concept-footway",)
    assert tied.items[1].tied_with_intervention_ids == ("concept-crossing",)

    dominant_observations = tuple(
        item.model_copy(
            update={
                "value": 80 if item.intervention_id == "concept-crossing" else 40
            }
        )
        for item in observations()
    )
    dominant = validate_prioritisation_bundle(
        build_prioritisation(
            criteria=criteria(),
            intervention_bundle=bundle,
            output_dir=tmp_path / "dominant",
            analysis_id="dominant-scenario",
            observations=dominant_observations,
            scenarios=(scenarios()[0],),
            sensitivity_cases=(),
        )
    ).scenarios[0]
    assert dominant.items[0].intervention_id == "concept-crossing"
    assert dominant.items[0].total_score > dominant.items[1].total_score


def test_satn_validity_and_assembly_order_are_rejected_as_priority_measures() -> None:
    with pytest.raises(ValidationError, match="SATN"):
        MeasureDefinition(
            measure_id="satn-traffic-light",
            view=CriterionView.DELIVERABILITY_COST,
            transform=TransformKind.LINEAR_HIGHER_BETTER,
            minimum=0,
            maximum=100,
            base_weight=1,
            missing_data=MissingDataRule.REVIEW_REQUIRED,
            methodology="SATN assembly order",
        )


def test_recommended_and_authorised_programmes_require_separate_human_decisions(
    tmp_path: Path,
) -> None:
    bundle = build_interventions(tmp_path / "interventions")
    recommendation = ProgrammeDecision(
        decision_id="recommend-equality-scenario",
        kind=ProgrammeDecisionKind.RECOMMEND,
        scenario_id="equality-led",
        authority_name="B&NES programme board",
        decided_on=date(2026, 3, 1),
        rationale="Recommend for consultation; no funding commitment.",
        evidence_uri="https://example.test/programme/recommendation",
    )
    recommended = validate_prioritisation_bundle(
        build_prioritisation(
            criteria=criteria(),
            intervention_bundle=bundle,
            output_dir=tmp_path / "recommended",
            analysis_id="human-selection",
            observations=observations(),
            scenarios=scenarios(),
            sensitivity_cases=(),
            recommendation_decision=recommendation,
        )
    )
    assert recommended.recommended_programme is not None
    assert recommended.authorised_programme is None

    with pytest.raises(ValueError, match="recommendation"):
        build_prioritisation(
            criteria=criteria(),
            intervention_bundle=bundle,
            output_dir=tmp_path / "invalid",
            analysis_id="invalid-authorization",
            observations=observations(),
            scenarios=scenarios(),
            sensitivity_cases=(),
            authorization_decision=ProgrammeDecision(
                decision_id="authorize-without-recommendation",
                kind=ProgrammeDecisionKind.AUTHORISE,
                scenario_id="equality-led",
                authority_name="B&NES Cabinet",
                decided_on=date(2026, 4, 1),
                rationale="Invalid fixture.",
                evidence_uri="https://example.test/programme/authorization",
            ),
        )

    authorised = validate_prioritisation_bundle(
        build_prioritisation(
            criteria=criteria(),
            intervention_bundle=bundle,
            output_dir=tmp_path / "authorised",
            analysis_id="authorised-selection",
            observations=observations(),
            scenarios=scenarios(),
            sensitivity_cases=(),
            recommendation_decision=recommendation,
            authorization_decision=ProgrammeDecision(
                decision_id="authorize-equality-scenario",
                kind=ProgrammeDecisionKind.AUTHORISE,
                scenario_id="equality-led",
                authority_name="B&NES Cabinet",
                decided_on=date(2026, 4, 1),
                rationale="Authorise the selected ten-year programme scenario.",
                evidence_uri="https://example.test/programme/authorization",
            ),
        )
    )
    assert authorised.recommended_programme is not None
    assert authorised.authorised_programme is not None
    assert authorised.authorised_programme.status == "authorised"
