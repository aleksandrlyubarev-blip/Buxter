# Architecture documentation with Litho

## Install and generate

Requires Python 3.11+ (stdlib only), Git and Rust/Cargo for installation.
The executable is pinned to **deepwiki-rs 1.6.0**; flags and config were checked against its real `--help` and source.

```bash
cargo install deepwiki-rs --version 1.6.0 --locked
deepwiki-rs --version
deepwiki-rs --help
# Make LITHO_LLM_API_KEY available through your secret manager or shell environment.
bash scripts/litho_generate.sh --check
bash scripts/litho_generate.sh
```

If Cargo installation fails, use the same upstream source, not a substitute generator:

```bash
git clone --branch 1.6.0 --depth 1 https://github.com/sopaco/deepwiki-rs.git /tmp/deepwiki-rs-1.6.0
cargo install --path /tmp/deepwiki-rs-1.6.0 --locked
deepwiki-rs --help
```

The implementation environment had no `LITHO_LLM_API_KEY`; no LLM-generated output is claimed or seeded.
`--check` validates the input selection/config without an LLM call or placeholder output.
A normal run without the key exits successfully with `SKIP`; real generation errors exit nonzero.

## Provider configuration

| Environment variable | Behavior |
| --- | --- |
| `LITHO_LLM_API_KEY` | Required for generation; inherited by Litho, never passed in argv or stored in TOML. |
| `LITHO_LLM_API_BASE_URL` | Defaults to `https://api.anthropic.com`; a different endpoint uses the OpenAI-compatible adapter. |
| `LITHO_MODEL_EFFICIENT` | Anthropic default: `claude-haiku-4-5-20251001`. |
| `LITHO_MODEL_POWERFUL` | Anthropic default: `claude-sonnet-4-6`. |
| `LITHO_TARGET_LANGUAGE` | `en`; other values are rejected to preserve the English architecture contract. |

For a different OpenAI-compatible provider, set **both** model variables to IDs that provider supports; there is no universal provider-independent model ID.
Native Anthropic proxy URLs are not supported by this wrapper; use the official endpoint or an OpenAI-compatible gateway.
Remote URLs require HTTPS and must not contain credentials or query parameters.
Model availability is provider/account dependent; upgrade defaults only after checking the provider documentation.

## Input and cache boundary

The wrapper builds a temporary Git-tracked snapshot from `litho/inputs.txt` (product repositories) or the system canon plus collected child overviews (umbrella).
Only selected UTF-8 source/config files are copied; data, media, binaries, credentials, symlinks and untracked source are excluded or rejected.
Selected source with uncommitted changes is rejected: commit reviewed public source before generation.
The four `litho/context/*.md` files are injected through real `knowledge.local_docs` categories, and PRODUCT is prepended to the temporary README.
The live README and canon are never overwritten by Litho.
Preset file tools are disabled; the generator only analyzes the exported snapshot.
Only generated Markdown is copied back after successful generation; LLM failures leave existing docs untouched.
The temporary snapshot and `.litho` cache are removed on exit; persistent cache reuse is deliberately not enabled.
Only public/synthetic inputs are authorized. Input filtering is not a guarantee that arbitrary source comments contain no sensitive information.
Do not add customer SOPs, employer data, private datasets or production photographs to the manifest.

## CI and review

`.github/workflows/litho.yml` supports `workflow_dispatch` and path-filtered pushes to `main`.
A preflight checks only whether the key exists; missing keys produce a readable summary and skip the generation job, including on forks.
No `pull_request` or `pull_request_target` event is enabled. No commit-back is enabled: review downloaded artifacts before committing Markdown to `docs/litho/` on a branch.
Docs-only formatting changes do not trigger generation. Changes to the manual canon do trigger it.
The workflow receives `LITHO_LLM_API_KEY` and optional `LITHO_LLM_API_BASE_URL` from repository secrets; model IDs use repository variables.
Generated output is a draft, and a filename checklist is not a semantic C4 validation.

Before publishing generated Markdown, review these claims:

- Exactly five system containers; no unrelated media/call-center products.
- Neuron Vision: triage, solder, component, marking, chief; the separate ADK skeleton is not that pipeline.
- Copilot: missing evidence -> `needs_review`; actual enum is `pass / fail / needs_review`.
- Buxter: FreeCAD default, Fusion optional; explicit validate/printability gate, no automatic rework release.
- Romeo: orchestration + HITL, not a vision model.
- Camera -> capture/frame QA -> orchestration -> vision -> SOP/evidence gate -> human disposition -> verdict.
- Hardware, Flex line, Technion lab and national testbed are External target systems; drivers/deployments must not be invented.
- SHA-256 integrity and existing per-repo records are distinguished from the planned shared evidence pack.

Correct a false generated overview manually, strengthen PRODUCT, then regenerate when credentials are available.
Litho 1.6.0 has no verified overview-only flag; do not invent one. Full wrapper reruns update generated Markdown; inspect/remove stale generated files explicitly during review.

## Verified upstream references

- [Litho 1.6.0 CLI](https://github.com/sopaco/deepwiki-rs/blob/1.6.0/src/cli.rs)
- [Config schema and environment-key default](https://github.com/sopaco/deepwiki-rs/blob/1.6.0/src/config.rs)
- [Local knowledge integration](https://github.com/sopaco/deepwiki-rs/blob/1.6.0/litho-example.toml)
- [Anthropic model IDs](https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions)
- [GitHub Actions secret conditions](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)
