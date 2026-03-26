#!/usr/bin/env bash
set -euo pipefail

TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$(cd "${TOOLS_DIR}/.." && pwd)"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-50050}"
COLS="${COLS:-104}"
ROWS="${ROWS:-29}"
PX_W="${PX_W:-950}"
PX_H="${PX_H:-560}"

EMU="$(readlink -f "$(command -v x-terminal-emulator)")"
EMU_BASE="$(basename "${EMU}")"
GNOME_TERM="$(command -v gnome-terminal || true)"
WRAP="/tmp/docker_run_demo_world_multi_${USER}.sh"
MON_TERM_PID=""
GUI_PID=""

cat > "${WRAP}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "${WS_DIR}"
printf '[8;${ROWS};${COLS}t'

echo "[docker-run] monitor terminal cwd=$(pwd)"
echo "[docker-run] checking docker socket access in this terminal..."

if docker info >/dev/null 2>&1; then
  echo "[docker-run] docker access ok in monitor terminal"
  exec docker compose run --rm --no-deps radiation-headless python scripts/monitor/radiation_monitor.py --host "${HOST}" --port "${PORT}" --cfg-root "extensions/radiation.simulator/config" --world "demo_world"
else
  echo "[docker-run] docker access denied in monitor terminal; falling back to sudo"
  exec sudo docker compose run --rm --no-deps radiation-headless python scripts/monitor/radiation_monitor.py --host "${HOST}" --port "${PORT}" --cfg-root "extensions/radiation.simulator/config" --world "demo_world"
fi
EOF
chmod +x "${WRAP}"

docker_compose() {
  if docker info >/dev/null 2>&1; then
    docker compose "$@"
  else
    sudo docker compose "$@"
  fi
}

cleanup() {
  if [[ -n "${GUI_PID}" ]]; then
    kill "${GUI_PID}" 2>/dev/null || true
  fi
  if [[ -n "${MON_TERM_PID}" ]]; then
    kill "${MON_TERM_PID}" 2>/dev/null || true
  fi
  rm -f "${WRAP}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM HUP

echo "[docker-run] ws=${WS_DIR}"
echo "[docker-run] x-terminal-emulator=${EMU} (${EMU_BASE})"
echo "[docker-run] monitor udp://${HOST}:${PORT} cols=${COLS} rows=${ROWS}"
echo "[docker-run] gui service=radiation-demo-gui"
echo "[docker-run] monitor command will self-check docker access inside the new terminal"
echo "[docker-run] forcing direct gnome-terminal launch when available"

launch_monitor_terminal() {
  if [[ -n "${GNOME_TERM}" ]]; then
    "${GNOME_TERM}" --geometry="${COLS}x${ROWS}" --title="Radiation Demo Monitor" -- bash -ic '"$1"; rc=$?; echo; echo "[docker-run] monitor exited with code ${rc}"; exec bash' _ "${WRAP}" &
    MON_TERM_PID=$!
    return
  fi

  case "${EMU_BASE}" in
    terminator)
      "${EMU}" --geometry="${PX_W}x${PX_H}" -x bash -ic '"$1"; rc=$?; echo; echo "[docker-run] monitor exited with code ${rc}"; exec bash' _ "${WRAP}" &
      MON_TERM_PID=$!
      ;;
    gnome-terminal*|kgx)
      "${EMU}" --geometry="${COLS}x${ROWS}" -- bash -ic '"$1"; rc=$?; echo; echo "[docker-run] monitor exited with code ${rc}"; exec bash' _ "${WRAP}" &
      MON_TERM_PID=$!
      ;;
    xterm|uxterm|lxterm)
      "${EMU}" -geometry "${COLS}x${ROWS}" -e bash -ic '"$1"; rc=$?; echo; echo "[docker-run] monitor exited with code ${rc}"; exec bash' _ "${WRAP}" &
      MON_TERM_PID=$!
      ;;
    *)
      "${EMU}" -e bash -ic '"$1"; rc=$?; echo; echo "[docker-run] monitor exited with code ${rc}"; exec bash' _ "${WRAP}" &
      MON_TERM_PID=$!
      ;;
  esac
}

launch_monitor_terminal

cd "${WS_DIR}"
xhost +local:root >/dev/null 2>&1 || true
docker_compose --profile gui up radiation-demo-gui "$@" &
GUI_PID=$!
wait "${GUI_PID}"
