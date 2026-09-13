#!/usr/bin/env bash
# Activate screen2 first, or provide its interpreter through SCREEN_PYTHON.
set -euo pipefail
SCREEN_REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
SCREEN_PYTHON=${SCREEN_PYTHON:-python}
SCREEN_CONFIG=${SCREEN_CONFIG:-$SCREEN_REPO/.local/config.json}
SCREEN_COMMAND=${1:-}
SCREEN_ARGS=()
if [[ "$SCREEN_COMMAND" == run || "$SCREEN_COMMAND" == doctor ]]; then
  shift
  SCREEN_ARGS+=(--config "$SCREEN_CONFIG")
  if [[ "$SCREEN_COMMAND" == run && -n ${SCREEN_APBS_ROOT:-} ]]; then
    SCREEN_ARGS+=(--apbs-bin "$SCREEN_APBS_ROOT/bin/apbs"
                  --multivalue-bin "$SCREEN_APBS_ROOT/bin/multivalue")
  fi
  exec "$SCREEN_PYTHON" -u -m protein_screen "$SCREEN_COMMAND" "${SCREEN_ARGS[@]}" "$@"
fi
exec "$SCREEN_PYTHON" -u -m protein_screen "$@"
