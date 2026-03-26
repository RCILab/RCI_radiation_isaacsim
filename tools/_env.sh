#!/usr/bin/env bash
set -euo pipefail

THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_ROOT="$(cd "${THIS_DIR}/.." && pwd)"
export RADIATION_WS="${WS_ROOT}"

CONDA_ROOT="${CONDA_ROOT:-$HOME/miniconda3}"

if [ -f "${CONDA_ROOT}/etc/profile.d/conda.sh" ]; then
  # shellcheck disable=SC1090
  source "${CONDA_ROOT}/etc/profile.d/conda.sh"
else
  echo "[ERROR] conda.sh not found: ${CONDA_ROOT}/etc/profile.d/conda.sh"
  exit 1
fi

if [ -n "${CONDA_ENV:-}" ]; then
  SELECTED_ENV="${CONDA_ENV}"
else
  SELECTED_ENV=""
  for candidate in radiation_isaacsim radiation_isaaclab; do
    if [ -d "${CONDA_ROOT}/envs/${candidate}" ]; then
      SELECTED_ENV="${candidate}"
      break
    fi
  done
fi

if [ -z "${SELECTED_ENV}" ]; then
  echo "[ERROR] no suitable conda env found under ${CONDA_ROOT}/envs"
  echo "        tried: radiation_isaacsim, radiation_isaaclab"
  exit 1
fi

conda activate "${SELECTED_ENV}"
cd "${WS_ROOT}"
