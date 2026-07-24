"""Command line access to stable LCWIP contract validation."""

import json
from importlib.resources import files
from pathlib import Path
from typing import Annotated

import typer
from jsonschema import Draft202012Validator, FormatChecker

from lcwip.demand import validate_demand_bundle
from lcwip.evidence import (
    EvidenceRegistryConfig,
    snapshot_evidence_registry,
    validate_evidence_snapshot,
)
from lcwip.governance import validate_governance_bundle
from lcwip.interventions import validate_intervention_bundle
from lcwip.models import GuidanceProfile
from lcwip.monitoring import validate_monitoring_release
from lcwip.prioritisation import validate_prioritisation_bundle
from lcwip.publication import validate_lcwip_publication
from lcwip.staged_agents import AgentDecisionLedger, StageDecisionEnvelope
from lcwip.walking import validate_walking_bundle

app = typer.Typer(no_args_is_help=True, help="Validate LCWIP public contracts.")
profile_app = typer.Typer(no_args_is_help=True, help="Validate Guidance Profiles.")
evidence_app = typer.Typer(no_args_is_help=True, help="Manage governed evidence snapshots.")
demand_app = typer.Typer(no_args_is_help=True, help="Validate cycling demand bundles.")
walking_app = typer.Typer(
    no_args_is_help=True,
    help="Validate walking and wheeling planning bundles.",
)
interventions_app = typer.Typer(
    no_args_is_help=True,
    help="Validate strategic intervention-package bundles.",
)
prioritisation_app = typer.Typer(
    no_args_is_help=True,
    help="Validate transparent prioritisation bundles.",
)
governance_app = typer.Typer(
    no_args_is_help=True,
    help="Validate human-authority, engagement, equality and policy records.",
)
agents_app = typer.Typer(
    no_args_is_help=True,
    help="Validate bounded staged-agent decision contracts.",
)
publication_app = typer.Typer(
    no_args_is_help=True,
    help="Validate atomic, cited LCWIP publication releases.",
)
monitoring_app = typer.Typer(
    no_args_is_help=True,
    help="Validate immutable LCWIP delivery-monitoring and review releases.",
)
app.add_typer(profile_app, name="profile")
app.add_typer(evidence_app, name="evidence")
app.add_typer(demand_app, name="demand")
app.add_typer(walking_app, name="walking")
app.add_typer(interventions_app, name="interventions")
app.add_typer(prioritisation_app, name="prioritisation")
app.add_typer(governance_app, name="governance")
app.add_typer(agents_app, name="agents")
app.add_typer(publication_app, name="publication")
app.add_typer(monitoring_app, name="monitoring")


@profile_app.command("validate")
def validate_profile(path: Annotated[Path, typer.Argument(exists=True, readable=True)]) -> None:
    """Validate a versioned machine-readable Guidance Profile."""
    payload = json.loads(path.read_text())
    schema = json.loads(
        files("lcwip.profiles").joinpath("guidance-profile-1.0.schema.json").read_text()
    )
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.absolute_path))
    if errors:
        error = errors[0]
        location = "/".join(str(part) for part in error.absolute_path) or "profile"
        raise typer.BadParameter(f"schema validation failed at {location}: {error.message}")
    profile = GuidanceProfile.model_validate(payload)
    typer.echo(f"valid {profile.profile_id} {profile.fingerprint}")


@evidence_app.command("snapshot")
def snapshot_evidence(
    config: Annotated[Path, typer.Argument(exists=True, readable=True)],
) -> None:
    """Create or validate an immutable governed evidence snapshot."""
    registry = EvidenceRegistryConfig.from_json(config)
    path = snapshot_evidence_registry(registry)
    manifest = validate_evidence_snapshot(path)
    typer.echo(f"snapshot {path} {manifest.snapshot_fingerprint}")


@evidence_app.command("validate")
def validate_evidence(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
) -> None:
    """Validate an evidence snapshot and its coverage reports."""
    manifest = validate_evidence_snapshot(path)
    typer.echo(f"valid {manifest.snapshot_id} {manifest.snapshot_fingerprint}")


@demand_app.command("validate")
def validate_demand(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
) -> None:
    """Validate a demand, desire-line and route-selection review bundle."""
    manifest = validate_demand_bundle(path)
    typer.echo(f"valid {manifest.analysis_id} {manifest.analysis_fingerprint}")


@walking_app.command("validate")
def validate_walking(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
) -> None:
    """Validate a walking/wheeling network-planning and audit bundle."""
    manifest = validate_walking_bundle(path)
    typer.echo(f"valid {manifest.analysis_id} {manifest.analysis_fingerprint}")


@interventions_app.command("validate")
def validate_interventions(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
) -> None:
    """Validate an infrastructure intervention-package bundle."""
    manifest = validate_intervention_bundle(path)
    typer.echo(f"valid {manifest.analysis_id} {manifest.analysis_fingerprint}")


@prioritisation_app.command("validate")
def validate_prioritisation(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
) -> None:
    """Validate analytical, recommended and authorised programme outputs."""
    manifest = validate_prioritisation_bundle(path)
    typer.echo(f"valid {manifest.analysis_id} {manifest.analysis_fingerprint}")


@governance_app.command("validate")
def validate_governance(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
) -> None:
    """Validate a human-gated LCWIP governance and engagement record."""
    manifest = validate_governance_bundle(path)
    typer.echo(f"valid {manifest.release_id} {manifest.analysis_fingerprint}")


@agents_app.command("validate-envelope")
def validate_agent_envelope(
    path: Annotated[Path, typer.Argument(exists=True, readable=True)],
) -> None:
    """Validate one fingerprinted LCWIP Stage Decision Envelope."""
    envelope = StageDecisionEnvelope.model_validate_json(path.read_text())
    typer.echo(f"valid {envelope.request_id} {envelope.dependency_fingerprint}")


@agents_app.command("validate-ledger")
def validate_agent_ledger(
    path: Annotated[Path, typer.Argument(exists=True, readable=True)],
) -> None:
    """Validate a data-only staged-agent replay ledger."""
    ledger = AgentDecisionLedger.model_validate_json(path.read_text())
    typer.echo(f"valid {len(ledger.responses)} staged-agent responses")


@publication_app.command("validate")
def validate_publication(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
) -> None:
    """Validate an archived LCWIP report and publication bundle."""
    manifest = validate_lcwip_publication(path)
    typer.echo(f"valid {manifest.release_id} {manifest.publication_fingerprint}")


@monitoring_app.command("validate")
def validate_monitoring(
    path: Annotated[Path, typer.Argument(exists=True, file_okay=False, readable=True)],
) -> None:
    """Validate delivery status, monitoring evidence and governed review tasks."""
    manifest = validate_monitoring_release(path)
    typer.echo(f"valid {manifest.cycle_id} {manifest.monitoring_fingerprint}")


if __name__ == "__main__":
    app()
