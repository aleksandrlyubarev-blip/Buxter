from pathlib import Path

import click
from rich.console import Console

from .backends import BackendName, get_backend
from .config import load_settings
from .exporter import ExportError, validate_artifacts
from .logging_setup import configure, get_logger
from .vision import generate_script

console = Console()
log = get_logger("buxter")

_BACKEND_CHOICE = click.Choice(["freecad", "fusion"], case_sensitive=False)


@click.group()
@click.version_option()
def cli() -> None:
    """Buxter CAD Agent — photo + description → 3D-printable STL/STEP."""
    configure()


@cli.command()
@click.option("--photo", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--description", "-d", required=True, help="Design description in plain text.")
@click.option("--output", "-o", type=click.Path(file_okay=False, path_type=Path),
              default=None, help="Output directory (default: $BUXTER_OUTPUT_DIR or ./out).")
@click.option("--model", default=None, help="Model alias: opus / sonnet / haiku, or full id.")
@click.option("--backend", type=_BACKEND_CHOICE, default=None,
              help="Modeling backend (default: $BUXTER_BACKEND or freecad).")
def draw(
    photo: Path | None,
    description: str,
    output: Path | None,
    model: str | None,
    backend: str | None,
) -> None:
    """Generate STL + STEP from a description (and optional photo)."""
    settings = load_settings()
    if model:
        settings.model = model
    if backend:
        settings.backend = backend.lower()  # type: ignore[assignment]
    out_dir = (output or settings.output_dir).resolve()
    backend_impl = get_backend(settings.backend)

    console.print(
        f"[bold cyan]Buxter[/] backend=[magenta]{backend_impl.name}[/] "
        f"model=[green]{settings.model}[/] out={out_dir}"
    )
    if photo:
        console.print(f"photo = {photo}")

    console.print(f"[yellow]→ requesting {backend_impl.name} script from Claude…[/]")
    result = generate_script(description, photo, settings=settings, backend=backend_impl.name)
    console.print(f"[green]✓[/] received {len(result.script)} chars of Python")

    console.print(f"[yellow]→ running {backend_impl.name} backend…[/]")
    artifacts = backend_impl.run(result.script, out_dir, settings)
    if artifacts.note:
        console.print(f"[dim]{artifacts.note}[/]")
    if not artifacts.ok:
        console.print(f"[red]✗ {backend_impl.name} exit={artifacts.returncode}[/]")
        console.print(f"stderr (last 2000 chars):\n{artifacts.stderr[-2000:]}")
        console.print(f"See {artifacts.script_path} and {out_dir / 'run.log'} for full context.")
        raise SystemExit(1)

    if artifacts.backend == "fusion" and artifacts.note:
        # Dryrun: skip artifact validation, just confirm the emitted script.
        console.print(f"[bold green]✓ Script:[/] {artifacts.script_path}")
        return

    try:
        validated = validate_artifacts(artifacts.stl_path, artifacts.step_path or artifacts.stl_path)
    except ExportError as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise SystemExit(1) from exc

    console.print(f"[bold green]✓ STL:[/]  {validated.stl}  ({validated.stl.stat().st_size} bytes)")
    if validated.step:
        console.print(f"[bold green]✓ STEP:[/] {validated.step}")
    if artifacts.extra_path:
        console.print(f"[bold green]✓ F3D:[/]  {artifacts.extra_path}")
    console.print(f"[dim]Script saved to {artifacts.script_path}[/]")


@cli.command()
@click.argument("stl", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def inspect(stl: Path) -> None:
    """Print bounding box, volume and triangle count of an STL file."""
    try:
        import trimesh
    except ImportError as exc:
        console.print("[red]trimesh is not installed. pip install buxter[dev][/]")
        raise SystemExit(1) from exc

    mesh = trimesh.load(stl, force="mesh")
    bbox = mesh.bounding_box.extents
    console.print(f"[bold]{stl}[/]")
    console.print(f"  triangles : {len(mesh.faces)}")
    console.print(f"  bbox (mm) : {bbox[0]:.2f} x {bbox[1]:.2f} x {bbox[2]:.2f}")
    console.print(f"  volume    : {mesh.volume:.2f} mm³")
    console.print(f"  watertight: {mesh.is_watertight}")


@cli.command()
@click.argument("output", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--description", "-d", required=True, help="Revision instructions.")
@click.option("--photo", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None, help="Override photo (default: keep using none).")
@click.option("--model", default=None)
@click.option("--backend", type=_BACKEND_CHOICE, default=None,
              help="Override backend (default: detect from prior script filename).")
def retry(
    output: Path,
    description: str,
    photo: Path | None,
    model: str | None,
    backend: str | None,
) -> None:
    """Regenerate a model using the prior script as context."""
    settings = load_settings()
    if model:
        settings.model = model

    fusion_script = output / "_gen_fusion.py"
    freecad_script = output / "_gen.py"
    if backend:
        backend_name: BackendName = backend.lower()  # type: ignore[assignment]
    elif fusion_script.exists() and not freecad_script.exists():
        backend_name = "fusion"
    elif freecad_script.exists():
        backend_name = "freecad"
    else:
        backend_name = settings.backend
    settings.backend = backend_name
    backend_impl = get_backend(backend_name)

    prior_script_path = fusion_script if backend_name == "fusion" else freecad_script
    run_log_path = output / "run.log"
    if not prior_script_path.exists():
        console.print(f"[red]No prior script at {prior_script_path}. Run `buxter draw` first.[/]")
        raise SystemExit(1)

    prior_script = prior_script_path.read_text(encoding="utf-8")
    stderr = run_log_path.read_text(encoding="utf-8") if run_log_path.exists() else None

    console.print(f"[yellow]→ retrying ({backend_name}) with revised description…[/]")
    result = generate_script(
        description,
        photo,
        settings=settings,
        prior_script=prior_script,
        stderr=stderr,
        backend=backend_name,
    )
    artifacts = backend_impl.run(result.script, output, settings)
    if artifacts.note:
        console.print(f"[dim]{artifacts.note}[/]")
    if not artifacts.ok:
        console.print(f"[red]✗ {backend_name} exit={artifacts.returncode}[/]")
        console.print(f"stderr (last 2000 chars):\n{artifacts.stderr[-2000:]}")
        raise SystemExit(1)

    if backend_name == "fusion" and artifacts.note:
        console.print(f"[bold green]✓ Script:[/] {artifacts.script_path}")
        return

    validated = validate_artifacts(artifacts.stl_path, artifacts.step_path or artifacts.stl_path)
    console.print(f"[bold green]✓ STL:[/] {validated.stl}")
    if validated.step:
        console.print(f"[bold green]✓ STEP:[/] {validated.step}")
    if artifacts.extra_path:
        console.print(f"[bold green]✓ F3D:[/]  {artifacts.extra_path}")


if __name__ == "__main__":
    cli()
