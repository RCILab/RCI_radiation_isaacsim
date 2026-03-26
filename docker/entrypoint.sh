#!/usr/bin/env bash
set -euo pipefail

WS_DIR="${RADIATION_WS:-/workspace/radiation_isaacsim_ws}"
ISAACSIM_PY="/isaac-sim/python.sh"

if [ ! -x "${ISAACSIM_PY}" ]; then
  echo "[docker] Isaac Sim python not found: ${ISAACSIM_PY}" >&2
  exit 1
fi

cd "${WS_DIR}"

case "${1:-bash}" in
  bash)
    shift || true
    exec /bin/bash "$@"
    ;;
  python)
    shift || true
    exec "${ISAACSIM_PY}" "$@"
    ;;
  run-simulation)
    shift || true
    exec "${ISAACSIM_PY}" scripts/run_simulation.py "$@"
    ;;
  run-demo)
    shift || true
    exec "${ISAACSIM_PY}" scripts/demo/run_demo_world.py "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
