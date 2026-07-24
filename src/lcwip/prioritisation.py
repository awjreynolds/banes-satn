"""Transparent, council-directed LCWIP prioritisation and phasing."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import date
from enum import StrEnum
from itertools import pairwise
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from lcwip.interventions import (
    InterventionPlanningManifest,
    InterventionStatus,
    validate_intervention_bundle,
)

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    ),
]
Sha256 = Annotated[
    str,
    StringConstraints(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    ),
]


class PriorityContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        allow_inf_nan=False,
    )
    schema_version: Literal["1.0"] = "1.0"


class CriterionView(StrEnum):
    EFFECTIVENESS_BENEFIT = "effectiveness-benefit"
    POLICY_EQUALITY = "policy-equality"
    DELIVERABILITY_COST = "deliverability-cost"


class TransformKind(StrEnum):
    LINEAR_HIGHER_BETTER = "linear-higher-better"
    LINEAR_LOWER_BETTER = "linear-lower-better"
    THRESHOLD = "threshold"


class MissingDataRule(StrEnum):
    REVIEW_REQUIRED = "review-required"
    EXCLUDE_FROM_SCENARIO = "exclude-from-scenario"


class ProgrammeDecisionKind(StrEnum):
    RECOMMEND = "recommend"
    AUTHORISE = "authorise"


class CriteriaDirective(PriorityContract):
    directive_id: Identifier
    authority_name: NonBlank
    approved_on: date
    rationale: NonBlank
    evidence_uri: NonBlank


class MeasureDefinition(PriorityContract):
    measure_id: Identifier
    view: CriterionView
    transform: TransformKind
    minimum: float
    maximum: float
    base_weight: float = Field(gt=0)
    missing_data: MissingDataRule
    methodology: NonBlank

    @model_validator(mode="after")
    def bounds_and_forbidden_sources(self) -> Self:
        if self.maximum <= self.minimum:
            raise ValueError("measure maximum must exceed minimum")
        forbidden = f"{self.measure_id} {self.methodology}".lower()
        if "satn" in forbidden or "assembly order" in forbidden or "traffic light" in forbidden:
            raise ValueError(
                "SATN criteria states and assembly order are not priority measures"
            )
        return self


class HorizonDefinition(PriorityContract):
    phase: Literal["short", "medium", "long"]
    start_year: int = Field(ge=2000, le=2100)
    end_year: int = Field(ge=2000, le=2100)
    maximum_upper_cost: int = Field(gt=0)
    rationale: NonBlank

    @model_validator(mode="after")
    def ordered_years(self) -> Self:
        if self.end_year < self.start_year:
            raise ValueError("programme horizon end must not precede start")
        return self


class ApprovedCriteria(PriorityContract):
    criteria_id: Identifier
    version: NonBlank
    directive: CriteriaDirective
    measures: tuple[MeasureDefinition, ...] = Field(min_length=1)
    horizons: tuple[HorizonDefinition, ...] = Field(min_length=3, max_length=3)

    @field_validator("measures")
    @classmethod
    def complete_views(
        cls, value: tuple[MeasureDefinition, ...]
    ) -> tuple[MeasureDefinition, ...]:
        ids = tuple(item.measure_id for item in value)
        if len(ids) != len(set(ids)):
            raise ValueError("priority measure IDs must be unique")
        if {item.view for item in value} != set(CriterionView):
            raise ValueError("approved criteria must expose all three analytical views")
        return tuple(sorted(value, key=lambda item: item.measure_id))

    @field_validator("horizons")
    @classmethod
    def complete_horizons(
        cls, value: tuple[HorizonDefinition, ...]
    ) -> tuple[HorizonDefinition, ...]:
        order = {"short": 0, "medium": 1, "long": 2}
        if {item.phase for item in value} != set(order):
            raise ValueError("horizons must define short, medium and long phases")
        result = tuple(sorted(value, key=lambda item: order[item.phase]))
        if any(
            left.end_year >= right.start_year
            for left, right in pairwise(result)
        ):
            raise ValueError("programme horizons must not overlap")
        return result

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self)


class MeasureObservation(PriorityContract):
    observation_id: Identifier
    intervention_id: Identifier
    measure_id: Identifier
    value: float
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1)
    source_kind: Literal["observed", "inferred", "modelled"]
    methodology_version: NonBlank

    @field_validator("evidence_ids")
    @classmethod
    def unique_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique(value, "measure evidence IDs")


class ScenarioDefinition(PriorityContract):
    scenario_id: Identifier
    name: NonBlank
    directive_id: Identifier
    weight_overrides: dict[Identifier, float]
    quick_win_max_upper_cost: int = Field(gt=0)
    rules: tuple[NonBlank, ...] = Field(min_length=1)

    @field_validator("weight_overrides")
    @classmethod
    def positive_weights(cls, value: dict[str, float]) -> dict[str, float]:
        if any(weight <= 0 for weight in value.values()):
            raise ValueError("scenario weights must be positive")
        return dict(sorted(value.items()))


class SensitivityCase(PriorityContract):
    case_id: Identifier
    base_scenario_id: Identifier
    directive_id: Identifier
    weight_overrides: dict[Identifier, float]
    observation_overrides: dict[NonBlank, float]
    rationale: NonBlank


class ProgrammeDecision(PriorityContract):
    decision_id: Identifier
    kind: ProgrammeDecisionKind
    scenario_id: Identifier
    authority_name: NonBlank
    decided_on: date
    rationale: NonBlank
    evidence_uri: NonBlank


class MeasureResult(PriorityContract):
    measure_id: Identifier
    view: CriterionView
    raw_value: float
    transform: TransformKind
    transformed_value: float = Field(ge=0, le=1)
    weight: float = Field(gt=0)
    weighted_contribution: float = Field(ge=0)
    evidence_ids: tuple[Identifier, ...]
    source_kind: Literal["observed", "inferred", "modelled"]
    missing_data_treatment: MissingDataRule


class ViewResult(PriorityContract):
    view: CriterionView
    score: float = Field(ge=0, le=1)
    measure_ids: tuple[Identifier, ...]


class ProgrammeItemResult(PriorityContract):
    intervention_id: Identifier
    status: InterventionStatus
    total_score: float | None = Field(default=None, ge=0, le=1)
    rank: int | None = Field(default=None, ge=1)
    tied_with_intervention_ids: tuple[Identifier, ...]
    phase: Literal["short", "medium", "long"] | None
    phase_index: int | None = Field(default=None, ge=0, le=2)
    phase_rationale: NonBlank
    measure_results: tuple[MeasureResult, ...]
    view_results: tuple[ViewResult, ...]
    missing_measure_ids: tuple[Identifier, ...]
    dependencies: tuple[Identifier, ...]
    mutually_exclusive_options: tuple[Identifier, ...]
    quick_win: bool
    enabling_work: bool
    cost_confidence: NonBlank | None
    upper_cost: int | None
    risk_topics: tuple[NonBlank, ...]
    unresolved_evidence_request_ids: tuple[Identifier, ...]


class AnalyticalScenario(PriorityContract):
    scenario_id: Identifier
    name: NonBlank
    scenario_fingerprint: Sha256
    items: tuple[ProgrammeItemResult, ...]


class SensitivityResult(PriorityContract):
    case_id: Identifier
    base_scenario_id: Identifier
    rank_changes: dict[Identifier, int | None]
    phase_changes: dict[Identifier, NonBlank]
    unstable_intervention_ids: tuple[Identifier, ...]


class PriorityEvidenceRequest(PriorityContract):
    request_id: Identifier
    intervention_id: Identifier
    measure_id: Identifier
    purpose: NonBlank


class SelectedProgramme(PriorityContract):
    scenario: AnalyticalScenario
    decision: ProgrammeDecision
    status: Literal["recommended", "authorised"]

    @model_validator(mode="after")
    def decision_matches_status(self) -> Self:
        expected = (
            ProgrammeDecisionKind.RECOMMEND
            if self.status == "recommended"
            else ProgrammeDecisionKind.AUTHORISE
        )
        if self.decision.kind is not expected:
            raise ValueError("programme decision kind does not match selected status")
        if self.decision.scenario_id != self.scenario.scenario_id:
            raise ValueError("programme decision must select its embedded scenario")
        return self


class PrioritisationArtifact(PriorityContract):
    path: NonBlank
    sha256: Sha256

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("prioritisation artifact path must remain inside bundle")
        return value


class PrioritisationManifest(PriorityContract):
    analysis_id: Identifier
    criteria: ApprovedCriteria
    criteria_fingerprint: Sha256
    intervention_analysis_id: Identifier
    intervention_fingerprint: Sha256
    input_fingerprint: Sha256
    observations: tuple[MeasureObservation, ...]
    scenario_definitions: tuple[ScenarioDefinition, ...]
    sensitivity_cases: tuple[SensitivityCase, ...]
    scenarios: tuple[AnalyticalScenario, ...]
    sensitivity_results: tuple[SensitivityResult, ...]
    policy_trade_offs: tuple[NonBlank, ...]
    evidence_requests: tuple[PriorityEvidenceRequest, ...]
    recommended_programme: SelectedProgramme | None
    authorised_programme: SelectedProgramme | None
    artifacts: tuple[PrioritisationArtifact, ...]
    analysis_fingerprint: Sha256

    @model_validator(mode="after")
    def integrity(self) -> Self:
        if self.criteria_fingerprint != self.criteria.fingerprint:
            raise ValueError("criteria fingerprint does not match")
        ids = tuple(item.scenario_id for item in self.scenarios)
        if len(ids) != len(set(ids)):
            raise ValueError("analytical scenario IDs must be unique")
        if {item.scenario_id for item in self.scenario_definitions} != set(ids):
            raise ValueError("scenario definitions must match analytical scenarios")
        definitions = {
            item.scenario_id: item for item in self.scenario_definitions
        }
        measure_ids = {item.measure_id for item in self.criteria.measures}
        item_id_sets = []
        for scenario in self.scenarios:
            expected_scenario_fingerprint = _fingerprint(
                {
                    "scenario": definitions[scenario.scenario_id],
                    "items": scenario.items,
                }
            )
            if scenario.scenario_fingerprint != expected_scenario_fingerprint:
                raise ValueError("analytical scenario fingerprint does not match")
            item_ids = tuple(item.intervention_id for item in scenario.items)
            if len(item_ids) != len(set(item_ids)):
                raise ValueError("programme scenario intervention IDs must be unique")
            item_id_sets.append(set(item_ids))
            by_id = {item.intervention_id: item for item in scenario.items}
            for item in scenario.items:
                result_ids = {result.measure_id for result in item.measure_results}
                if set(item.missing_measure_ids) != measure_ids - result_ids:
                    raise ValueError("programme item missing measures do not reconcile")
                if item.missing_measure_ids:
                    if (
                        item.rank is not None
                        or item.phase is not None
                        or item.total_score is not None
                    ):
                        raise ValueError("missing evidence cannot receive rank or phase")
                elif item.rank is None or item.total_score is None:
                    raise ValueError("complete programme item must retain its rank")
                for peer_id in item.tied_with_intervention_ids:
                    peer = by_id.get(peer_id)
                    if (
                        peer is None
                        or item.intervention_id
                        not in peer.tied_with_intervention_ids
                        or peer.rank != item.rank
                        or peer.total_score != item.total_score
                    ):
                        raise ValueError("programme ties must be symmetric and exact")
        if item_id_sets and any(
            item_ids != item_id_sets[0] for item_ids in item_id_sets[1:]
        ):
            raise ValueError("analytical scenarios must compare the same interventions")
        case_ids = {item.case_id for item in self.sensitivity_cases}
        if {item.case_id for item in self.sensitivity_results} != case_ids:
            raise ValueError("sensitivity results must match configured cases")
        observation_keys = {
            (item.intervention_id, item.measure_id) for item in self.observations
        }
        if len(observation_keys) != len(self.observations):
            raise ValueError("measure observations must be unique by intervention")
        intervention_ids = item_id_sets[0] if item_id_sets else set()
        expected_requests = {
            (intervention_id, measure_id)
            for intervention_id in intervention_ids
            for measure_id in measure_ids
            if (intervention_id, measure_id) not in observation_keys
        }
        if {
            (item.intervention_id, item.measure_id)
            for item in self.evidence_requests
        } != expected_requests:
            raise ValueError("priority evidence requests do not match missing measures")
        artifact_paths = tuple(item.path for item in self.artifacts)
        if len(artifact_paths) != len(set(artifact_paths)) or set(
            artifact_paths
        ) != set(ARTIFACTS):
            raise ValueError("prioritisation artifact set is incomplete")
        if self.authorised_programme is not None:
            if self.recommended_programme is None:
                raise ValueError("authorised programme requires recommendation")
            if (
                self.authorised_programme.scenario.scenario_id
                != self.recommended_programme.scenario.scenario_id
            ):
                raise ValueError("authorisation must follow the recommended scenario")
        expected = _fingerprint(
            self.model_dump(mode="json", exclude={"analysis_fingerprint"})
        )
        if self.analysis_fingerprint != expected:
            raise ValueError("prioritisation analysis fingerprint does not match")
        return self


ARTIFACTS = ("analytical-scenarios.json", "programme-table.json", "sensitivity.json")


def build_prioritisation(
    *,
    criteria: ApprovedCriteria,
    intervention_bundle: Path,
    output_dir: Path,
    analysis_id: str,
    observations: tuple[MeasureObservation, ...],
    scenarios: tuple[ScenarioDefinition, ...],
    sensitivity_cases: tuple[SensitivityCase, ...],
    recommendation_decision: ProgrammeDecision | None = None,
    authorization_decision: ProgrammeDecision | None = None,
) -> Path:
    """Build deterministic analytical scenarios; only humans select programmes."""
    criteria = ApprovedCriteria.model_validate(criteria.model_dump())
    source = validate_intervention_bundle(intervention_bundle)
    observations = _canonical(observations, "observation_id", MeasureObservation)
    scenarios = _canonical(scenarios, "scenario_id", ScenarioDefinition)
    sensitivity_cases = _canonical(sensitivity_cases, "case_id", SensitivityCase)
    _validate_inputs(criteria, source, observations, scenarios, sensitivity_cases)
    evidence_requests = _missing_requests(criteria, source, observations)
    analytical = tuple(
        _score_scenario(criteria, source, observations, scenario)
        for scenario in scenarios
    )
    by_scenario = {item.scenario_id: item for item in analytical}
    sensitivity_results = tuple(
        _run_sensitivity(criteria, source, observations, by_scenario, case)
        for case in sensitivity_cases
    )
    top_ids = {
        next((item.intervention_id for item in scenario.items if item.rank == 1), None)
        for scenario in analytical
    }
    top_ids.discard(None)
    trade_offs = (
        (
            "Council-approved scenarios produce conflicting leading interventions; "
            "the policy trade-off remains explicit."
        ,)
        if len(top_ids) > 1
        else ()
    )
    recommended = _selected_programme(
        recommendation_decision,
        ProgrammeDecisionKind.RECOMMEND,
        "recommended",
        by_scenario,
    )
    if authorization_decision is not None and recommended is None:
        raise ValueError("programme authorization requires a recommendation")
    authorised = _selected_programme(
        authorization_decision,
        ProgrammeDecisionKind.AUTHORISE,
        "authorised",
        by_scenario,
    )
    if authorised is not None and (
        recommended is None
        or authorised.scenario.scenario_id != recommended.scenario.scenario_id
    ):
        raise ValueError("authorization must select the recommended scenario")
    if (
        recommended is not None
        and recommended.decision.decided_on < criteria.directive.approved_on
    ):
        raise ValueError("programme recommendation cannot predate criteria approval")
    if (
        authorised is not None
        and recommended is not None
        and authorised.decision.decided_on < recommended.decision.decided_on
    ):
        raise ValueError("programme authorization cannot predate recommendation")
    input_fingerprint = _fingerprint(
        {
            "analysis_id": analysis_id,
            "criteria": criteria,
            "intervention_fingerprint": source.analysis_fingerprint,
            "observations": observations,
            "scenarios": scenarios,
            "sensitivity_cases": sensitivity_cases,
            "recommendation_decision": recommendation_decision,
            "authorization_decision": authorization_decision,
        }
    )
    destination = output_dir / analysis_id
    if destination.exists():
        existing = validate_prioritisation_bundle(destination)
        if existing.input_fingerprint != input_fingerprint:
            raise ValueError("prioritisation bundle is immutable and inputs changed")
        return destination
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{analysis_id}-", dir=output_dir))
    try:
        _write(
            temporary / "analytical-scenarios.json",
            {
                "observations": observations,
                "scenario_definitions": scenarios,
                "scenarios": analytical,
            },
        )
        _write(
            temporary / "programme-table.json",
            {
                "recommended_programme": recommended,
                "authorised_programme": authorised,
                "evidence_requests": evidence_requests,
            },
        )
        _write(
            temporary / "sensitivity.json",
            {
                "sensitivity_results": sensitivity_results,
                "policy_trade_offs": trade_offs,
            },
        )
        artifacts = tuple(
            PrioritisationArtifact(
                path=path,
                sha256=hashlib.sha256((temporary / path).read_bytes()).hexdigest(),
            )
            for path in ARTIFACTS
        )
        payload = {
            "schema_version": "1.0",
            "analysis_id": analysis_id,
            "criteria": criteria,
            "criteria_fingerprint": criteria.fingerprint,
            "intervention_analysis_id": source.analysis_id,
            "intervention_fingerprint": source.analysis_fingerprint,
            "input_fingerprint": input_fingerprint,
            "observations": observations,
            "scenario_definitions": scenarios,
            "sensitivity_cases": sensitivity_cases,
            "scenarios": analytical,
            "sensitivity_results": sensitivity_results,
            "policy_trade_offs": trade_offs,
            "evidence_requests": evidence_requests,
            "recommended_programme": recommended,
            "authorised_programme": authorised,
            "artifacts": artifacts,
        }
        manifest = PrioritisationManifest(
            **payload, analysis_fingerprint=_fingerprint(payload)
        )
        _write(temporary / "prioritisation-manifest.json", manifest)
        validate_prioritisation_bundle(temporary)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return destination


def validate_prioritisation_bundle(path: Path) -> PrioritisationManifest:
    path = Path(path)
    try:
        manifest = PrioritisationManifest.model_validate_json(
            (path / "prioritisation-manifest.json").read_text()
        )
    except (OSError, ValueError) as error:
        raise ValueError(f"invalid prioritisation bundle: {error}") from error
    expected_files = {"prioritisation-manifest.json"}
    for artifact in manifest.artifacts:
        expected_files.add(artifact.path)
        artifact_path = path / artifact.path
        if not artifact_path.is_file():
            raise ValueError(f"invalid prioritisation bundle: missing {artifact.path}")
        if hashlib.sha256(artifact_path.read_bytes()).hexdigest() != artifact.sha256:
            raise ValueError(f"invalid prioritisation bundle: {artifact.path} content hash")
    actual = {
        item.relative_to(path).as_posix() for item in path.rglob("*") if item.is_file()
    }
    if actual != expected_files:
        raise ValueError("invalid prioritisation bundle: file set mismatch")
    expected = {
        "analytical-scenarios.json": {
            "observations": manifest.observations,
            "scenario_definitions": manifest.scenario_definitions,
            "scenarios": manifest.scenarios,
        },
        "programme-table.json": {
            "recommended_programme": manifest.recommended_programme,
            "authorised_programme": manifest.authorised_programme,
            "evidence_requests": manifest.evidence_requests,
        },
        "sensitivity.json": {
            "sensitivity_results": manifest.sensitivity_results,
            "policy_trade_offs": manifest.policy_trade_offs,
        },
    }
    for filename, payload in expected.items():
        if json.loads((path / filename).read_text()) != _json(payload):
            raise ValueError(f"invalid prioritisation bundle: {filename} mismatch")
    return manifest


def _validate_inputs(
    criteria: ApprovedCriteria,
    source: InterventionPlanningManifest,
    observations: tuple[MeasureObservation, ...],
    scenarios: tuple[ScenarioDefinition, ...],
    cases: tuple[SensitivityCase, ...],
) -> None:
    concept_ids = {item.intervention_id for item in source.concepts}
    measure_ids = {item.measure_id for item in criteria.measures}
    allowed_evidence = {
        evidence_id
        for deficiency in source.deficiencies
        for evidence_id in deficiency.evidence_ids
    } | {
        evidence_id
        for concept in source.concepts
        for evidence_id in concept.evidence_ids
    }
    keys = set()
    for item in observations:
        if item.intervention_id not in concept_ids or item.measure_id not in measure_ids:
            raise ValueError("measure observation must resolve to concept and criterion")
        if not set(item.evidence_ids).issubset(allowed_evidence):
            raise ValueError("measure observation evidence is not governed by source")
        key = (item.intervention_id, item.measure_id)
        if key in keys:
            raise ValueError("one measure observation is allowed per concept and measure")
        keys.add(key)
        definition = next(x for x in criteria.measures if x.measure_id == item.measure_id)
        if not definition.minimum <= item.value <= definition.maximum:
            raise ValueError("measure observation falls outside configured bounds")
    scenario_ids = {item.scenario_id for item in scenarios}
    for scenario in scenarios:
        if scenario.directive_id != criteria.directive.directive_id:
            raise ValueError("scenario weights are not bound to the council directive")
        if set(scenario.weight_overrides) != measure_ids:
            raise ValueError("scenario must explicitly weight every approved measure")
    for case in cases:
        if case.directive_id != criteria.directive.directive_id:
            raise ValueError("sensitivity rules are not bound to the council directive")
        if case.base_scenario_id not in scenario_ids:
            raise ValueError("sensitivity base scenario must resolve")
        if not set(case.weight_overrides).issubset(measure_ids):
            raise ValueError("sensitivity weights must resolve")


def _missing_requests(
    criteria: ApprovedCriteria,
    source: InterventionPlanningManifest,
    observations: tuple[MeasureObservation, ...],
) -> tuple[PriorityEvidenceRequest, ...]:
    present = {(item.intervention_id, item.measure_id) for item in observations}
    return tuple(
        PriorityEvidenceRequest(
            request_id=f"request-{concept.intervention_id}-{measure.measure_id}",
            intervention_id=concept.intervention_id,
            measure_id=measure.measure_id,
            purpose=(
                f"Resolve missing {measure.measure_id} evidence; it is not scored "
                "as zero or average."
            ),
        )
        for concept in source.concepts
        for measure in criteria.measures
        if (concept.intervention_id, measure.measure_id) not in present
    )


def _score_scenario(
    criteria: ApprovedCriteria,
    source: InterventionPlanningManifest,
    observations: tuple[MeasureObservation, ...],
    scenario: ScenarioDefinition,
) -> AnalyticalScenario:
    return _score_with_values(criteria, source, observations, scenario, {})


def _score_with_values(
    criteria: ApprovedCriteria,
    source: InterventionPlanningManifest,
    observations: tuple[MeasureObservation, ...],
    scenario: ScenarioDefinition,
    value_overrides: dict[str, float],
) -> AnalyticalScenario:
    observations_by_key = {
        (item.intervention_id, item.measure_id): item for item in observations
    }
    costs = {item.intervention_id: item for item in source.costs}
    requests_by_intervention = {
        concept.intervention_id: tuple(
            request.request_id
            for request in source.evidence_requests
            if request.intervention_id == concept.intervention_id
        )
        for concept in source.concepts
    }
    enabling = {
        dependency
        for concept in source.concepts
        for dependency in concept.depends_on_intervention_ids
    }
    raw_items = []
    for concept in source.concepts:
        results = []
        missing = []
        for definition in criteria.measures:
            observation = observations_by_key.get(
                (concept.intervention_id, definition.measure_id)
            )
            if observation is None:
                missing.append(definition.measure_id)
                continue
            raw = value_overrides.get(
                f"{concept.intervention_id}:{definition.measure_id}",
                observation.value,
            )
            normalized = (raw - definition.minimum) / (
                definition.maximum - definition.minimum
            )
            if definition.transform is TransformKind.LINEAR_LOWER_BETTER:
                normalized = 1 - normalized
            elif definition.transform is TransformKind.THRESHOLD:
                normalized = float(raw >= definition.maximum)
            weight = scenario.weight_overrides.get(
                definition.measure_id, definition.base_weight
            )
            results.append(
                MeasureResult(
                    measure_id=definition.measure_id,
                    view=definition.view,
                    raw_value=raw,
                    transform=definition.transform,
                    transformed_value=round(normalized, 8),
                    weight=weight,
                    weighted_contribution=round(normalized * weight, 8),
                    evidence_ids=observation.evidence_ids,
                    source_kind=observation.source_kind,
                    missing_data_treatment=definition.missing_data,
                )
            )
        views = tuple(
            ViewResult(
                view=view,
                score=round(
                    sum(x.weighted_contribution for x in results if x.view is view)
                    / sum(x.weight for x in results if x.view is view),
                    8,
                ),
                measure_ids=tuple(x.measure_id for x in results if x.view is view),
            )
            for view in CriterionView
            if any(x.view is view for x in results)
        )
        total = (
            None
            if missing
            else round(
                sum(x.weighted_contribution for x in results)
                / sum(x.weight for x in results),
                8,
            )
        )
        cost = costs.get(concept.intervention_id)
        risks = tuple(
            item.topic.value
            for item in source.constraints
            if item.intervention_id == concept.intervention_id
            and item.state.value in {"known-constraint", "unknown"}
        )
        raw_items.append(
            {
                "concept": concept,
                "total": total,
                "measures": tuple(results),
                "views": views,
                "missing": tuple(sorted(missing)),
                "cost": cost,
                "risks": risks,
            }
        )
    ranked = sorted(
        (item for item in raw_items if item["total"] is not None),
        key=lambda item: (-item["total"], item["concept"].intervention_id),
    )
    rank_by_id: dict[str, int] = {}
    previous_score: float | None = None
    previous_rank = 0
    for index, item in enumerate(ranked):
        if previous_score is None or item["total"] != previous_score:
            previous_rank = index + 1
            previous_score = item["total"]
        rank_by_id[item["concept"].intervention_id] = previous_rank
    ties_by_id = {
        item["concept"].intervention_id: tuple(
            sorted(
                peer["concept"].intervention_id
                for peer in ranked
                if peer["total"] == item["total"]
                and peer["concept"].intervention_id
                != item["concept"].intervention_id
            )
        )
        for item in ranked
    }
    schedule_order = _dependency_order(
        tuple(item["concept"] for item in ranked)
    )
    phase_by_id = _schedule(schedule_order, costs, criteria.horizons)
    items = tuple(
        ProgrammeItemResult(
            intervention_id=item["concept"].intervention_id,
            status=item["concept"].status,
            total_score=item["total"],
            rank=rank_by_id.get(item["concept"].intervention_id),
            tied_with_intervention_ids=ties_by_id.get(
                item["concept"].intervention_id, ()
            ),
            phase=(
                criteria.horizons[phase_by_id[item["concept"].intervention_id]].phase
                if item["concept"].intervention_id in phase_by_id
                else None
            ),
            phase_index=phase_by_id.get(item["concept"].intervention_id),
            phase_rationale=(
                "Scheduled by transparent rank, cost envelope and hard dependencies."
                if item["concept"].intervention_id in phase_by_id
                else (
                    "Not phased because required measure evidence is missing."
                    if item["missing"]
                    else (
                        "Not phased because of capacity, unresolved dependency, "
                        "or a higher-ranked mutually exclusive option."
                    )
                )
            ),
            measure_results=item["measures"],
            view_results=item["views"],
            missing_measure_ids=item["missing"],
            dependencies=item["concept"].depends_on_intervention_ids,
            mutually_exclusive_options=item[
                "concept"
            ].mutually_exclusive_intervention_ids,
            quick_win=(
                item["cost"] is not None
                and item["cost"].upper_bound <= scenario.quick_win_max_upper_cost
            ),
            enabling_work=item["concept"].intervention_id in enabling,
            cost_confidence=(
                item["cost"].confidence.value if item["cost"] is not None else None
            ),
            upper_cost=(
                item["cost"].upper_bound if item["cost"] is not None else None
            ),
            risk_topics=item["risks"],
            unresolved_evidence_request_ids=requests_by_intervention[
                item["concept"].intervention_id
            ],
        )
        for item in sorted(
            raw_items,
            key=lambda item: (
                rank_by_id.get(item["concept"].intervention_id, 10**9),
                item["concept"].intervention_id,
            ),
        )
    )
    payload = {"scenario": scenario, "items": items}
    return AnalyticalScenario(
        scenario_id=scenario.scenario_id,
        name=scenario.name,
        scenario_fingerprint=_fingerprint(payload),
        items=items,
    )


def _dependency_order(concepts: tuple[Any, ...]) -> tuple[Any, ...]:
    by_id = {item.intervention_id: item for item in concepts}
    ordered = []
    visited = set()

    def visit(item: Any) -> None:
        if item.intervention_id in visited:
            return
        for dependency in item.depends_on_intervention_ids:
            if dependency in by_id:
                visit(by_id[dependency])
        visited.add(item.intervention_id)
        ordered.append(item)

    for concept in concepts:
        visit(concept)
    return tuple(ordered)


def _schedule(
    concepts: tuple[Any, ...],
    costs: dict[str, Any],
    horizons: tuple[HorizonDefinition, ...],
) -> dict[str, int]:
    spent = [0 for _ in horizons]
    assigned = {}
    for concept in concepts:
        cost = costs.get(concept.intervention_id)
        if cost is None:
            continue
        if any(
            peer in assigned
            for peer in concept.mutually_exclusive_intervention_ids
        ):
            continue
        if any(
            dependency not in assigned
            for dependency in concept.depends_on_intervention_ids
        ):
            continue
        minimum_phase = max(
            (
                assigned[item] + 1
                for item in concept.depends_on_intervention_ids
                if item in assigned
            ),
            default=0,
        )
        for index in range(minimum_phase, len(horizons)):
            if spent[index] + cost.upper_bound <= horizons[index].maximum_upper_cost:
                assigned[concept.intervention_id] = index
                spent[index] += cost.upper_bound
                break
    return assigned


def _run_sensitivity(
    criteria: ApprovedCriteria,
    source: InterventionPlanningManifest,
    observations: tuple[MeasureObservation, ...],
    base_scenarios: dict[str, AnalyticalScenario],
    case: SensitivityCase,
) -> SensitivityResult:
    base = base_scenarios[case.base_scenario_id]
    base_definition = next(
        item
        for item in base_scenarios.values()
        if item.scenario_id == case.base_scenario_id
    )
    # Recreate the approved scenario from its decomposed weights.
    weights = {
        result.measure_id: result.weight
        for item in base.items
        for result in item.measure_results
    }
    weights.update(case.weight_overrides)
    scenario = ScenarioDefinition(
        scenario_id=f"sensitivity-{case.case_id}",
        name=case.rationale,
        directive_id=case.directive_id,
        weight_overrides=weights,
        quick_win_max_upper_cost=max(
            horizon.maximum_upper_cost for horizon in criteria.horizons
        ),
        rules=("Sensitivity only; not a council-selected programme.",),
    )
    changed = _score_with_values(
        criteria, source, observations, scenario, case.observation_overrides
    )
    base_items = {item.intervention_id: item for item in base_definition.items}
    changed_items = {item.intervention_id: item for item in changed.items}
    rank_changes = {
        item_id: (
            None
            if base_items[item_id].rank is None or changed_items[item_id].rank is None
            else changed_items[item_id].rank - base_items[item_id].rank
        )
        for item_id in base_items
    }
    phase_changes = {
        item_id: (
            f"{base_items[item_id].phase or 'unphased'}->"
            f"{changed_items[item_id].phase or 'unphased'}"
        )
        for item_id in base_items
    }
    unstable = tuple(
        sorted(
            item_id
            for item_id in base_items
            if rank_changes[item_id] not in {0, None}
            or base_items[item_id].phase != changed_items[item_id].phase
        )
    )
    return SensitivityResult(
        case_id=case.case_id,
        base_scenario_id=case.base_scenario_id,
        rank_changes=rank_changes,
        phase_changes=phase_changes,
        unstable_intervention_ids=unstable,
    )


def _selected_programme(
    decision: ProgrammeDecision | None,
    expected_kind: ProgrammeDecisionKind,
    status: Literal["recommended", "authorised"],
    scenarios: dict[str, AnalyticalScenario],
) -> SelectedProgramme | None:
    if decision is None:
        return None
    if decision.kind is not expected_kind:
        raise ValueError(f"{status} programme decision has the wrong kind")
    if decision.scenario_id not in scenarios:
        raise ValueError(f"{status} programme scenario must resolve")
    return SelectedProgramme(
        scenario=scenarios[decision.scenario_id],
        decision=decision,
        status=status,
    )


def _canonical(records: tuple[Any, ...], field: str, model: type[Any]) -> tuple[Any, ...]:
    validated = tuple(model.model_validate(item) for item in records)
    ids = tuple(getattr(item, field) for item in validated)
    if len(ids) != len(set(ids)):
        raise ValueError(f"{field} values must be unique")
    return tuple(sorted(validated, key=lambda item: getattr(item, field)))


def _unique(value: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(value) != len(set(value)):
        raise ValueError(f"{label} must be unique")
    return tuple(sorted(value))


def _json(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return [_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, StrEnum):
        return value.value
    return value


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(_json(value), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(_json(value), indent=2, sort_keys=True) + "\n")
