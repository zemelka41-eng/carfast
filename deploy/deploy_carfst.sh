#!/usr/bin/env bash
# Wrapper for the real deploy script.
# Source of truth is /home/carfst/app/bin/deploy_carfst.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

exec "${REPO_ROOT}/bin/deploy_carfst.sh" "$@"

