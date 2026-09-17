"""Run pinned Litho on a bounded public-source snapshot, never the live workspace."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

VERSION = "1.6.0"
CANON = ("PRODUCT.md", "DOMAIN.md", "NON_GOALS.md", "HARDWARE_BOUNDARY.md")
EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".rs",
    ".sql",
    ".toml",
    ".json",
    ".yaml",
    ".yml",
    ".css",
    ".qss",
    ".html",
    ".txt",
}
BLOCKED = {
    ".git",
    ".litho",
    ".litho-cache",
    "node_modules",
    "data",
    "datasets",
    "roboqc_data",
    "video",
    "videos",
    "evidence",
    "samples",
    "fixtures",
    "private",
    "customer",
    "customer_data",
    "secrets",
    "__pycache__",
    "dist",
    "build",
    "target",
}


def command(*args: str, cwd: Path | None = None) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def safe_file(root: Path, path: Path) -> bytes:
    relative = path.relative_to(root)
    if any(part in {"..", "."} for part in relative.parts):
        raise ValueError("Invalid input path")
    if any(
        (root / Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts) + 1)
    ):
        raise ValueError(f"Symlink inputs are not allowed: {relative}")
    if path.stat().st_size > 524288:
        raise ValueError(f"Input exceeds 512 KiB: {relative}")
    data = path.read_bytes()
    data.decode("utf-8")
    if b"\x00" in data:
        raise ValueError(f"Binary input is not allowed: {relative}")
    return data


def select_inputs(repo: Path, system: bool) -> dict[str, bytes]:
    selected = {
        "litho/context/" + name: safe_file(repo, repo / "litho/context" / name) for name in CANON
    }
    # Make the canon the first README context seen by the preprocessing stage.
    selected["README.md"] = (
        selected["litho/context/PRODUCT.md"] + b"\n\n" + safe_file(repo, repo / "README.md")
    )
    if system:
        selected["docs/00-system-context.md"] = safe_file(repo, repo / "docs/00-system-context.md")
        for path in sorted((repo / "litho/.inputs").rglob("*.md")):
            selected[str(path.relative_to(repo))] = safe_file(repo, path)
    else:
        paths = [
            line
            for line in (repo / "litho/inputs.txt").read_text().splitlines()
            if line and not line.startswith("#")
        ]
        if any(Path(p).is_absolute() or ".." in Path(p).parts for p in paths):
            raise ValueError("Input manifest must contain repository-relative paths")
        if command("git", "diff", "HEAD", "--", *paths, cwd=repo):
            raise ValueError(
                "Selected source has uncommitted changes; "
                "commit reviewed public source before generation"
            )
        tracked = (
            subprocess.check_output(["git", "ls-files", "-z", "--", *paths], cwd=repo)
            .decode()
            .split("\0")
        )
        for name in tracked:
            path = Path(name)
            if not name or any(
                part.lower() in BLOCKED or part.startswith(".") for part in path.parts
            ):
                continue
            if path.suffix.lower() not in EXTENSIONS or fnmatch.fnmatch(path.name, "*lock*"):
                continue
            if any(word in path.name.lower() for word in ("credential", "secret", "token")):
                continue
            selected[name] = safe_file(repo, repo / path)
        if len(selected) <= len(CANON) + 1:
            raise ValueError("No public source selected; check litho/inputs.txt and the checkout")
    return selected


def provider_args() -> list[str]:
    base = os.environ.get("LITHO_LLM_API_BASE_URL") or "https://api.anthropic.com"
    parsed = urlsplit(base)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Use a base URL without embedded credentials, query or fragment")
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("Remote provider base URL must use HTTPS")
    anthropic = parsed.hostname == "api.anthropic.com"
    efficient = os.environ.get("LITHO_MODEL_EFFICIENT")
    powerful = os.environ.get("LITHO_MODEL_POWERFUL")
    if anthropic:
        efficient = efficient or "claude-haiku-4-5-20251001"
        powerful = powerful or "claude-sonnet-4-6"
    elif not efficient or not powerful:
        raise ValueError(
            "For an OpenAI-compatible endpoint set both "
            "LITHO_MODEL_EFFICIENT and LITHO_MODEL_POWERFUL"
        )
    return [
        "--llm-provider",
        "anthropic" if anthropic else "openai",
        "--llm-api-base-url",
        base,
        "--model-efficient",
        efficient,
        "--model-powerful",
        powerful,
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--system", action="store_true")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate inputs/config without LLM calls or generated output",
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    if not args.check and not os.environ.get("LITHO_LLM_API_KEY", "").strip():
        print("SKIP: LITHO_LLM_API_KEY is not set; no LLM calls or generated documentation.")
        return
    config_file = repo / ("litho/litho.toml" if args.system else "litho.toml")
    config_bytes = safe_file(repo, config_file)
    config = tomllib.loads(config_bytes.decode())
    if "llm" in config:
        raise ValueError("Keep [llm] absent: Litho reads the key through its environment default")
    selected = select_inputs(repo, args.system)
    if args.system and not args.check:
        for child in (
            "Romeo_PHD",
            "roboqc-agent-challenge",
            "inspection-copilot",
            "Buxter",
            "RomeoFlexVision",
        ):
            if f"litho/.inputs/{child}/GENERATION.md" not in selected:
                raise ValueError(
                    "System generation requires all five child overviews; "
                    "run litho/scripts/generate_all.sh"
                )
    source_sha = command("git", "rev-parse", "HEAD", cwd=repo)
    if args.check:
        print(
            f"CHECK OK: {config['project_name']}: {len(selected)} bounded text inputs; "
            f"source {source_sha}"
        )
        return
    binary = shutil.which("deepwiki-rs")
    if not binary:
        raise ValueError(
            f"Install: cargo install deepwiki-rs --version {VERSION} --locked "
            "(see litho/README.md for source fallback)"
        )
    version = command(binary, "--version")
    if version.split()[-1] != VERSION:
        raise ValueError(
            f"Expected Litho {VERSION}; got {version}. Recheck flags before upgrading."
        )
    provider = provider_args()
    language = os.environ.get("LITHO_TARGET_LANGUAGE") or "en"
    if language != "en":
        raise ValueError(
            "This system requires English architecture docs; set LITHO_TARGET_LANGUAGE=en"
        )
    target = repo / "docs/litho" / ("system" if args.system else "")
    # Check the complete output path before launching a paid generation.
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError("Output path must not contain symlinks")
    with tempfile.TemporaryDirectory(prefix="physical-ai-docs-") as temporary:
        work = Path(temporary)
        project = work / "source"
        generated = work / "generated"
        for name, data in selected.items():
            dest = project / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        (project / "litho.toml").write_bytes(config_bytes)
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        subprocess.run(["git", "-C", str(project), "add", "."], check=True)
        # Never put the key in TOML, process arguments, README or printed commands.
        # Config deliberately omits [llm], retaining LLMConfig::default() env lookup.
        subprocess.run(
            [binary, "sync-knowledge", "--config", "litho.toml", "--force"], cwd=project, check=True
        )
        subprocess.run(
            [
                binary,
                "-p",
                str(project),
                "-o",
                str(generated),
                "--config",
                "litho.toml",
                "--name",
                config["project_name"],
                "--target-language",
                language,
                "--disable-preset-tools",
                "--max-parallels",
                "2",
                "--max-tokens",
                "8192",
                *provider,
            ],
            cwd=project,
            check=True,
        )
        markdown = sorted(generated.rglob("*.md"))
        if not markdown or not any("overview" in p.name.lower() for p in markdown):
            raise ValueError("Litho did not produce an overview; previous docs are untouched")
        contents = {p.relative_to(generated): safe_file(generated, p) for p in markdown}
        key = os.environ["LITHO_LLM_API_KEY"].encode()
        if any(key in data for data in contents.values()):
            raise ValueError("Refusing generated content containing the API key")
        for relative in {*contents, Path("GENERATION.md")}:
            path = target / relative
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise ValueError("Existing generated path contains a symlink")
        for relative, data in contents.items():
            path = target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        digest = hashlib.sha256(
            config_bytes + b"".join(name.encode() + selected[name] for name in sorted(selected))
        ).hexdigest()
        (target / "GENERATION.md").write_text(
            f"# Generation provenance\n\nTool: {version}\n\nSource commit: {source_sha}\n\n"
            f"Input/config SHA-256: {digest}\n\n"
            "Status: generated; semantic review against litho/context is still required.\n"
        )
        for label, words in {
            "C4 Context": ("context", "overview"),
            "C4 Containers / architecture": ("architecture", "container"),
            "Workflow": ("workflow",),
            "C4 Components": ("module", "component"),
            "Boundaries": ("boundary", "interface"),
        }.items():
            found = any(any(word in str(p).lower() for word in words) for p in contents)
            print(
                f"[{'x' if found else ' '}] {label} files "
                f"{'present' if found else 'missing — review required'}"
            )
        print(
            f"Wrote {len(markdown)} Markdown files to {target}. "
            "Review claims before committing; inspect stale files from earlier runs."
        )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Litho documentation generation failed: {error}") from None
