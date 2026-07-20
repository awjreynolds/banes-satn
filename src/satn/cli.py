"""Command-line interface."""

from pathlib import Path

import typer

from satn.models import CouncilConfig
from satn.pipeline import compile as compile_satn
from satn.sources import snapshot as create_snapshot

app = typer.Typer(no_args_is_help=True, help="Compile strategic active travel networks.")


@app.command()
def snapshot(config: Path, replace: bool = typer.Option(False, "--replace")) -> None:
    """Create or validate an immutable source snapshot."""
    path = create_snapshot(CouncilConfig.from_yaml(config), replace=replace)
    typer.echo(path)


@app.command("compile")
def compile_command(config: Path) -> None:
    """Compile and atomically publish the current network."""
    result = compile_satn(config)
    typer.echo(f"{result.status}: {result.connections} connections, {result.gaps} gaps")
    typer.echo(result.output_dir)


if __name__ == "__main__":
    app()

