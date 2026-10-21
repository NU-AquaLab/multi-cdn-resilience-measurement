#!/usr/bin/env bash
# Run fallback-live using the shared measurement image.
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec "$SCRIPT_DIR/scripts/run_docker.sh" fallback-live "$@"
