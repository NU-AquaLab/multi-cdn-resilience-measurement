#!/usr/bin/env bash
# Build the shared measurement image from any working directory.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/docker_common.sh"

case "${1-}" in
    -h|--help)
        printf 'Usage: %s [--dry-run]\nImage: DOCKER_IMAGE (default: measure-tiktok:latest)\n' "$0"
        exit 0
        ;;
    --dry-run) dry_run=1 ;;
    '') dry_run=0 ;;
    *) fail "Unknown option: $1" ;;
esac
(( $# <= 1 )) || fail 'Too many arguments'
command_args=(docker build -f "$REPO_ROOT/docker/Dockerfile" -t "${DOCKER_IMAGE:-measure-tiktok:latest}" "$REPO_ROOT")
if (( dry_run )); then
    print_command "${command_args[@]}"
else
    require_command docker
    exec "${command_args[@]}"
fi
