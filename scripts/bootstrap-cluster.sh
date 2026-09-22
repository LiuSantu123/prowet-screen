#!/usr/bin/env bash
# Download this file first, inspect it, then run. Never overwrites an existing path.
set -euo pipefail
SCREEN_DEST=${1:-prowet}
if (( $# )); then shift; fi
if [[ -e "$SCREEN_DEST" ]]; then
  echo "Destination already exists: $SCREEN_DEST. To resume, run: bash $SCREEN_DEST/install.sh [options]" >&2
  exit 1
fi
command -v git >/dev/null || { echo 'Install git using your cluster package manager first.' >&2; exit 1; }
git clone --branch main --single-branch https://github.com/LiuSantu123/prowet-screen.git "$SCREEN_DEST"
exec bash "$SCREEN_DEST/install.sh" "$@"
