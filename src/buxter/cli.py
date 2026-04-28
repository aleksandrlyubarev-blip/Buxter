from pathlib import Path

import click
from rich.console import Console

from .config import load_settings
from .exporter import ExportError, validate_artifacts
from .logging_setup import configure, get_logger
from .runner import run_freecad_script
from .vision import generate_script

console = Console()
log = get_logger("buxter")


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
def draw(photo: Path | None, description: str, output: Path | None, model: str | None) -> None:
    """Generate STL + STEP from a description (and optional photo)."""
    settings = load_settings()
    if model:
        settings.model = model
    out_dir = (output or settings.output_dir).resolve()

    console.print(f"[bold cyan]Buxter[/] model=[green]{settings.model}[/] out={out_dir}")
    if photo:
        console.print(f"photo = {photo}")

    console.print("[yellow]→ requesting FreeCAD script from Claude…[/]")
    result = generate_script(description, photo, settings=settings)
    console.print(f"[green]✓[/] received {len(result.script)} chars of Python")

    console.print("[yellow]→ running freecadcmd…[/]")
    run = run_freecad_script(
        result.script,
        out_dir,
        timeout=settings.run_timeout,
        freecad_cmd=settings.freecad_cmd,
    )
    if not run.ok:
        console.print(f"[red]✗ freecadcmd exit={run.returncode}[/]")
        console.print(f"stderr (last 2000 chars):\n{run.stderr[-2000:]}")
        console.print(f"See {run.script_path} and {out_dir / 'run.log'} for full context.")
        raise SystemExit(1)

    try:
        artifacts = validate_artifacts(run.stl_path, run.step_path)
    except ExportError as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise SystemExit(1) from exc

    console.print(f"[bold green]✓ STL:[/]  {artifacts.stl}  ({artifacts.stl.stat().st_size} bytes)")
    if artifacts.step:
        console.print(f"[bold green]✓ STEP:[/] {artifacts.step}")
    console.print(f"[dim]Script saved to {run.script_path}[/]")


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
def retry(output: Path, description: str, photo: Path | None, model: str | None) -> None:
    """Regenerate a model using the prior script as context."""
    settings = load_settings()
    if model:
        settings.model = model

    prior_script_path = output / "_gen.py"
    run_log_path = output / "run.log"
    if not prior_script_path.exists():
        console.print(f"[red]No prior script at {prior_script_path}. Run `buxter draw` first.[/]")
        raise SystemExit(1)

    prior_script = prior_script_path.read_text(encoding="utf-8")
    stderr = run_log_path.read_text(encoding="utf-8") if run_log_path.exists() else None

    console.print(f"[yellow]→ retrying with revised description…[/]")
    result = generate_script(
        description,
        photo,
        settings=settings,
        prior_script=prior_script,
        stderr=stderr,
    )
    run = run_freecad_script(
        result.script,
        output,
        timeout=settings.run_timeout,
        freecad_cmd=settings.freecad_cmd,
    )
    if not run.ok:
        console.print(f"[red]✗ freecadcmd exit={run.returncode}[/]")
        console.print(f"stderr (last 2000 chars):\n{run.stderr[-2000:]}")
        raise SystemExit(1)

    artifacts = validate_artifacts(run.stl_path, run.step_path)
    console.print(f"[bold green]✓ STL:[/] {artifacts.stl}")
    if artifacts.step:
        console.print(f"[bold green]✓ STEP:[/] {artifacts.step}")


if __name__ == "__main__":
    cli()
