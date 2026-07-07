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
    from .validator import load_mesh

    try:
        mesh = load_mesh(stl)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        raise SystemExit(1) from exc
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


@cli.command()
@click.argument("mesh", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--min-wall", type=float, default=None,
              help="Minimal printable wall thickness in mm, e.g. 1.6 for FDM 0.4 nozzle.")
@click.option("--expect-bbox", default=None,
              help='Expected bounding box "XxYxZ" in mm (order-insensitive), e.g. "60x40x8".')
@click.option("--bbox-tol", type=float, default=0.5, help="Per-axis bbox tolerance, mm.")
@click.option("--wall-samples", type=int, default=300,
              help="Surface sample count for the wall thickness check.")
def validate(
    mesh: Path,
    min_wall: float | None,
    expect_bbox: str | None,
    bbox_tol: float,
    wall_samples: int,
) -> None:
    """Printability gate: watertight, volume, bbox vs spec, min wall thickness."""
    from .validator import parse_bbox, validate_mesh

    try:
        expected = parse_bbox(expect_bbox) if expect_bbox else None
        report = validate_mesh(
            mesh,
            min_wall=min_wall,
            expect_bbox=expected,
            bbox_tol=bbox_tol,
            wall_samples=wall_samples,
        )
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]{exc}[/]")
        raise SystemExit(1) from exc

    console.print(f"[bold]{report.path}[/]")
    for check in report.checks:
        mark, color = ("✓", "green") if check.ok else ("✗", "red")
        console.print(f"  [{color}]{mark}[/] {check.name:<10} {check.detail}")
    if report.ok:
        console.print("[bold green]✓ printable[/]")
    else:
        console.print("[bold red]✗ validation failed — fix the model before slicing/upload[/]")
        raise SystemExit(1)


_MESH_SUFFIXES = {".stl", ".3mf", ".obj", ".ply"}


def _gate_mesh_attachments(attach: tuple[Path, ...]) -> None:
    """Run the printability gate on mesh attachments before they leave the machine."""
    meshes = [p for p in attach if p.suffix.lower() in _MESH_SUFFIXES]
    if not meshes:
        return
    try:
        import trimesh  # noqa: F401 — availability probe for the optional gate
    except ImportError:
        console.print("[yellow]validate extra not installed — skipping printability gate[/]")
        return
    from .validator import validate_mesh
    for path in meshes:
        try:
            report = validate_mesh(path)
        except RuntimeError as exc:
            console.print(f"[red]✗ {exc}[/]")
            raise SystemExit(1) from exc
        if not report.ok:
            failed = ", ".join(check.name for check in report.checks if not check.ok)
            console.print(
                f"[red]✗ {path} fails the printability gate ({failed}). "
                f"Fix the model or pass --no-validate to upload anyway.[/]"
            )
            raise SystemExit(1)
        console.print(f"[dim]✓ gate: {path.name} printable[/]")


@cli.command()
@click.option("--task", "-t", required=True, help="What to do in the browser, in plain text.")
@click.option("--url", default=None, help="Start URL for the web application.")
@click.option("--attach", "-a", multiple=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="File the agent is allowed to upload (repeatable), e.g. out/out.stl.")
@click.option("--headed", is_flag=True, help="Show the browser window (default: headless).")
@click.option("--no-validate", is_flag=True,
              help="Skip the printability gate on mesh attachments before upload.")
@click.option("--model", default=None, help="Model alias: opus / sonnet / haiku, or full id.")
def web(
    task: str,
    url: str | None,
    attach: tuple[Path, ...],
    headed: bool,
    no_validate: bool,
    model: str | None,
) -> None:
    """Drive a web app with the CAD artifacts: upload, set parameters, run."""
    from .browser import PlaywrightSession
    from .web_agent import WebStep, run_web_task

    settings = load_settings()
    if model:
        settings.model = model
    if not settings.anthropic_api_key:
        console.print("[red]ANTHROPIC_API_KEY is not set.[/]")
        raise SystemExit(1)

    if not no_validate:
        _gate_mesh_attachments(attach)

    headless = settings.web_headless and not headed
    console.print(
        f"[bold cyan]Buxter web[/] model=[green]{settings.model}[/] "
        f"headless={headless} attachments={[p.name for p in attach]}"
    )

    def show(step: WebStep) -> None:
        console.print(f"[yellow]→ {step.tool}[/] {step.input} [dim]{step.result[:120]}[/]")

    try:
        session = PlaywrightSession(
            headless=headless,
            step_timeout_ms=settings.web_step_timeout_ms,
            chromium_path=settings.web_chromium_path,
        )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        raise SystemExit(1) from exc
    try:
        report = run_web_task(
            task,
            settings=settings,
            session=session,
            attachments=attach,
            start_url=url,
            on_step=show,
        )
    finally:
        session.close()

    color = "green" if report.success else "red"
    mark = "✓" if report.success else "✗"
    console.print(f"[bold {color}]{mark} {report.summary}[/]")
    if not report.success:
        raise SystemExit(1)


if __name__ == "__main__":
    cli()
