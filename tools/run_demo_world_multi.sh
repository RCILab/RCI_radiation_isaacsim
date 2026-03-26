#!/usr/bin/env bash
set -euo pipefail

TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$(cd "${TOOLS_DIR}/.." && pwd)"

PY="${TOOLS_DIR}/run_python.sh"
LAUNCH_PY="${WS_DIR}/scripts/demo/run_demo_world.py"
MONITOR_PY="${WS_DIR}/scripts/monitor/radiation_monitor.py"
CFG_ROOT="extensions/radiation.simulator/config"
WORLD_NAME="demo_world"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-50050}"
COLS="${COLS:-104}"
ROWS="${ROWS:-29}"
PX_W="${PX_W:-950}"
PX_H="${PX_H:-560}"

[[ -f "${PY}" ]] || { echo "[ERR] missing: ${PY}"; exit 1; }
[[ -f "${LAUNCH_PY}" ]] || { echo "[ERR] missing: ${LAUNCH_PY}"; exit 1; }
[[ -f "${MONITOR_PY}" ]] || { echo "[ERR] missing: ${MONITOR_PY}"; exit 1; }

EMU="$(readlink -f "$(command -v x-terminal-emulator)")"
EMU_BASE="$(basename "${EMU}")"
PIDFILE="/tmp/radiation_demo_monitor_${USER}.pid"
WRAP="/tmp/radiation_demo_monitor_${USER}.sh"
MON_TERM_PID=""
LAUNCH_PID=""

cat > "${WRAP}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "${WS_DIR}"
printf '[8;${ROWS};${COLS}t'
("${PY}" "${MONITOR_PY}" --host "${HOST}" --port "${PORT}" --cfg-root "${CFG_ROOT}" --world "${WORLD_NAME}") &
echo \$! > "${PIDFILE}"
wait
EOF
chmod +x "${WRAP}"

cleanup() {
  if [[ -n "${LAUNCH_PID}" ]]; then
    kill "${LAUNCH_PID}" 2>/dev/null || true
  fi
  if [[ -f "${PIDFILE}" ]]; then
    MPID="$(cat "${PIDFILE}" 2>/dev/null || true)"
    if [[ -n "${MPID}" ]]; then
      kill "${MPID}" 2>/dev/null || true
    fi
    rm -f "${PIDFILE}" 2>/dev/null || true
  fi
  if [[ -n "${MON_TERM_PID}" ]]; then
    kill "${MON_TERM_PID}" 2>/dev/null || true
  fi
  rm -f "${WRAP}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM HUP

echo "[run] ws=${WS_DIR}"
echo "[run] x-terminal-emulator=${EMU} (${EMU_BASE})"
echo "[run] monitor udp://${HOST}:${PORT} world=${WORLD_NAME} cols=${COLS} rows=${ROWS}"

case "${EMU_BASE}" in
  terminator)
    "${EMU}" --geometry="${PX_W}x${PX_H}" -x bash "${WRAP}" &
    MON_TERM_PID=$!
    ;;
  gnome-terminal*|kgx)
    "${EMU}" --geometry="${COLS}x${ROWS}" -- bash "${WRAP}" &
    MON_TERM_PID=$!
    ;;
  xterm|uxterm|lxterm)
    "${EMU}" -geometry "${COLS}x${ROWS}" -e bash "${WRAP}" &
    MON_TERM_PID=$!
    ;;
  *)
    "${EMU}" -e bash "${WRAP}" &
    MON_TERM_PID=$!
    ;;
esac

cd "${WS_DIR}"
"${PY}" "${LAUNCH_PY}" "$@" &
LAUNCH_PID=$!
wait "${LAUNCH_PID}"
