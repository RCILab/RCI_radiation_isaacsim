#!/usr/bin/env bash
set -euo pipefail
THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${THIS_DIR}/run_python.sh"
exec "${PY}" scripts/demo/run_demo_world.py "$@"
