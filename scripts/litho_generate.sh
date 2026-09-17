#!/usr/bin/env bash
set -euo pipefail
set +x
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$repo_dir/litho/run.py" --repo "$repo_dir" "$@"
