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

_BACKEND_CHOICE = click.Choice(["freecad", "fusion", "build123d"], case_sensitive=False)


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
@click.option("--self-check", is_flag=True,
              help="Render the result and let a judge verify it against the "
                   "description, regenerating on failure (max 2 rounds).")
def draw(
    photo: Path | None,
    description: str,
    output: Path | None,
    model: str | None,
    backend: str | None,
    self_check: bool,
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

    if self_check:
        artifacts = _self_check_loop(
            description, artifacts, backend_impl, out_dir, settings
        )

    console.print(f"[bold green]✓ STL:[/]  {artifacts.stl_path}  ({artifacts.stl_path.stat().st_size} bytes)")
    if artifacts.step_path:
        console.print(f"[bold green]✓ STEP:[/] {artifacts.step_path}")
    if artifacts.extra_path:
        console.print(f"[bold green]✓ F3D:[/]  {artifacts.extra_path}")
    console.print(f"[dim]Script saved to {artifacts.script_path}[/]")


def _print_verify_report(report) -> None:
    for item in report.questions:
        mark, color = ("✓", "green") if item.answer == "yes" else ("✗", "red")
        console.print(f"  [{color}]{mark}[/] {item.question} — {item.answer}"
                      + (f" [dim]({item.note})[/]" if item.note else ""))


def _self_check_loop(description, artifacts, backend_impl, out_dir, settings):
    """CADCodeVerify loop: judge the render, regenerate on failure, max 2 rounds."""
    from .verify_agent import MAX_SELF_CHECK_ROUNDS, verify_model

    for round_no in range(1, MAX_SELF_CHECK_ROUNDS + 1):
        console.print(f"[yellow]→ self-check round {round_no}: rendering + judging…[/]")
        report = verify_model(artifacts.stl_path, description, settings=settings)
        _print_verify_report(report)
        if report.passed:
            console.print("[bold green]✓ self-check passed[/]")
            return artifacts
        if round_no == MAX_SELF_CHECK_ROUNDS or not report.revision:
            console.print("[red]✗ self-check failed; keeping last artifacts.[/]")
            console.print(f"[dim]suggested revision: {report.revision or '(none)'}[/]")
            return artifacts

        console.print(f"[yellow]→ regenerating with revision:[/] {report.revision}")
        prior_script = artifacts.script_path.read_text(encoding="utf-8")
        result = generate_script(
            report.revision,
            settings=settings,
            prior_script=prior_script,
            backend=backend_impl.name,
        )
        candidate = backend_impl.run(result.script, out_dir, settings)
        if not candidate.ok:
            console.print("[red]✗ regeneration failed to build; keeping previous model.[/]")
            return artifacts
        artifacts = candidate
    return artifacts


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

    script_by_backend: dict[str, Path] = {
        "fusion": output / "_gen_fusion.py",
        "build123d": output / "_gen_b123d.py",
        "freecad": output / "_gen.py",
    }
    if backend:
        backend_name: BackendName = backend.lower()  # type: ignore[assignment]
    else:
        detected = [name for name, path in script_by_backend.items() if path.exists()]
        backend_name = detected[0] if len(detected) == 1 else settings.backend
    settings.backend = backend_name
    backend_impl = get_backend(backend_name)

    prior_script_path = script_by_backend[backend_name]
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


@cli.command()
@click.argument("mesh", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--description", "-d", required=True,
              help="The original design intent to judge the geometry against.")
@click.option("--model", default=None, help="Model alias: opus / sonnet / haiku, or full id.")
def verify(mesh: Path, description: str, model: str | None) -> None:
    """Vision self-check: render the mesh and judge it against the description."""
    from .verify_agent import verify_model

    settings = load_settings()
    if model:
        settings.model = model

    console.print(f"[yellow]→ rendering {mesh.name} and judging against the description…[/]")
    try:
        report = verify_model(mesh, description, settings=settings)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]{exc}[/]")
        raise SystemExit(1) from exc

    console.print(f"[bold]{mesh}[/]")
    console.print(f"[dim]{report.metrics}[/]")
    _print_verify_report(report)
    if report.passed:
        console.print("[bold green]✓ geometry matches the description[/]")
    else:
        console.print("[bold red]✗ geometry does not match the description[/]")
        if report.revision:
            console.print(f"[yellow]suggested revision:[/] {report.revision}")
        raise SystemExit(1)


@cli.command()
@click.argument("mesh_a", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("mesh_b", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--samples", type=int, default=2000, help="Surface sample count per direction.")
def diff(mesh_a: Path, mesh_b: Path, samples: int) -> None:
    """Quantify how two meshes differ (sampled symmetric Hausdorff distance)."""
    from .meshtools import diff_meshes

    try:
        report = diff_meshes(mesh_a, mesh_b, samples=samples)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        raise SystemExit(1) from exc

    console.print(f"[bold]{mesh_a.name} vs {mesh_b.name}[/]")
    console.print(f"  hausdorff    : {report.hausdorff:.3f} mm")
    console.print(f"  mean A→B     : {report.mean_a_to_b:.3f} mm")
    console.print(f"  mean B→A     : {report.mean_b_to_a:.3f} mm")
    console.print(f"  volume delta : {report.volume_delta:.2f} mm³")
    console.print(
        f"  bbox A       : {report.bbox_a[0]:.2f}×{report.bbox_a[1]:.2f}×{report.bbox_a[2]:.2f} mm"
    )
    console.print(
        f"  bbox B       : {report.bbox_b[0]:.2f}×{report.bbox_b[1]:.2f}×{report.bbox_b[2]:.2f} mm"
    )


@cli.command()
@click.argument("mesh_a", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("mesh_b", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--clearance", type=float, default=0.3,
              help="Required minimum gap between the parts, mm (default 0.3).")
@click.option("--samples", type=int, default=2000, help="Surface sample count per direction.")
def fit(mesh_a: Path, mesh_b: Path, clearance: float, samples: int) -> None:
    """Assembly check: interference and minimum clearance between two parts."""
    from .meshtools import check_fit

    try:
        report = check_fit(mesh_a, mesh_b, clearance=clearance, samples=samples)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        raise SystemExit(1) from exc

    console.print(f"[bold]{mesh_a.name} + {mesh_b.name}[/]")
    if report.interference_volume > 0:
        console.print(f"  [red]✗ interference: {report.interference_volume:.2f} mm³ overlap[/]")
    else:
        console.print("  [green]✓ no interference[/]")
        mark, color = ("✓", "green") if report.min_gap >= clearance else ("✗", "red")
        console.print(
            f"  [{color}]{mark}[/] min gap {report.min_gap:.3f} mm "
            f"(required ≥ {clearance:g} mm)"
        )
    if report.ok:
        console.print("[bold green]✓ parts fit[/]")
    else:
        console.print("[bold red]✗ fit check failed[/]")
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
