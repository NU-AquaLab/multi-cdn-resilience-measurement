#!/usr/bin/env bash
# Run one workflow with host configuration and data mounted into the container.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/docker_common.sh"

usage() {
    cat <<'HELP'
Usage: scripts/run_docker.sh COMMAND [--build] [--dry-run]

Commands: collect-vod, collect-live, fallback-live, fallback-vod, fallback-iterative

--build      Rebuild the image before running (missing images build automatically).
--dry-run    Print Docker commands without running Docker or creating directories.

Settings:
  ENV_FILE       Configuration file (default: repository .env).
  DOCKER_IMAGE   Image name (default: measure-tiktok:latest).
  VPN_CONTAINER  Optional existing VPN container whose network should be used.
  CONTAINER_NAME Optional measurement container name.
  LOG_LEVEL      DEBUG, INFO, WARNING, or ERROR (default: INFO).

Cookie/output/category paths come from .env, with exported variables taking
precedence. Credentials are read by Docker from the env file or environment.
collect-vod requires interactive input and a local X11 display.
HELP
}

[[ $# -gt 0 ]] || { usage >&2; exit 2; }
case "$1" in -h|--help) usage; exit 0 ;; esac
workflow=$1
shift
valid_workflow "$workflow" || fail "Unknown workflow: $workflow"
rebuild=0
dry_run=0
for arg in "$@"; do
    case "$arg" in
        --build) rebuild=1 ;;
        --dry-run) dry_run=1 ;;
        -h|--help) usage; exit 0 ;;
        *) fail "Unknown option: $arg" ;;
    esac
done
resolve_env_file
image=${DOCKER_IMAGE:-measure-tiktok:latest}
results_value=$(setting OUTPUT_DIR results)
[[ -n "$results_value" ]] || fail 'OUTPUT_DIR must not be empty'
results_dir=$(absolute_path "$results_value" "$ENV_DIR")
args=(docker run --rm --init --shm-size=1g
    --name "${CONTAINER_NAME:-measure-tiktok-$workflow-$$}"
    --env-file "$ENV_FILE")

# Pass exported settings by name so secrets never appear in command output.
for key in DB_NAME DB_USER DB_PASSWORD DB_HOST DB_PORT TIKTOK_SESSION_ID VPN_PROVIDER LIVE_FALLBACK_WRITE_DB CAPTURE_INTERFACE INFRA_DB_HOST; do
    if [[ ${!key+x} ]]; then args+=(--env "$key"); fi
done
args+=(--env OUTPUT_DIR=/work/results --env CHROME_BINARY=/usr/bin/chromium
    --mount "type=bind,source=$results_dir,target=/work/results")
if [[ -n ${VPN_CONTAINER:-} ]]; then
    args+=(--network "container:$VPN_CONTAINER")
else
    args+=(--add-host host.docker.internal:host-gateway)
fi
case "$workflow" in
    fallback-*) args+=(--cap-add=NET_ADMIN --env MEASUREMENT_OS=linux) ;;
esac

cookie_dir=''
case "$workflow" in
    collect-vod|collect-live|fallback-vod|fallback-iterative)
        cookie_value=$(setting TIKTOK_COOKIE_FILE tiktok_cookies.pkl)
        [[ -n "$cookie_value" ]] || fail 'TIKTOK_COOKIE_FILE must not be empty'
        cookie_file=$(absolute_path "$cookie_value" "$ENV_DIR")
        if [[ "$workflow" == collect-vod ]]; then
            cookie_dir=$(dirname -- "$cookie_file")
            [[ ! -e "$cookie_file" || -f "$cookie_file" ]] || fail "Cookie path is not a file: $cookie_file"
            args+=(--env TIKTOK_COOKIE_FILE=/work/cookies/tiktok_cookies.pkl
                --mount "type=bind,source=$cookie_file,target=/work/cookies/tiktok_cookies.pkl")
        else
            [[ -f "$cookie_file" ]] || fail "Cookie file not found: $cookie_file"
            args+=(--env TIKTOK_COOKIE_FILE=/work/cookies/tiktok_cookies.pkl
                --mount "type=bind,source=$cookie_file,target=/work/cookies/tiktok_cookies.pkl,readonly")
        fi
        ;;
esac
categories=$(setting LIVE_CATEGORIES_FILE '')
if [[ -n "$categories" && "$workflow" == fallback-live ]]; then
    categories=$(absolute_path "$categories" "$ENV_DIR")
    [[ -f "$categories" ]] || fail "Category file not found: $categories"
    args+=(--env LIVE_CATEGORIES_FILE=/work/categories.json
        --mount "type=bind,source=$categories,target=/work/categories.json,readonly")
fi

if [[ "$workflow" == collect-vod ]]; then
    [[ $(setting HEADLESS 0) == 0 ]] || fail 'collect-vod needs HEADLESS=0 for manual login'
    x11_dir=${X11_SOCKET_DIR:-/tmp/.X11-unix}
    if (( ! dry_run )); then
        [[ -t 0 ]] || fail 'collect-vod requires an interactive terminal for login'
        [[ -n ${DISPLAY:-} && -d "$x11_dir" ]] || fail 'collect-vod needs DISPLAY and a local X11 socket. Use the local CLI on hosts without X11.'
    fi
    args+=(-i --env HEADLESS=0 --env "DISPLAY=${DISPLAY:-:0}"
        --mount "type=bind,source=$x11_dir,target=/tmp/.X11-unix,readonly")
    if [[ -t 0 && -t 1 ]]; then args+=(-t); fi
    if [[ -n ${XAUTHORITY:-} ]]; then
        [[ -f "$XAUTHORITY" ]] || fail "XAUTHORITY file not found: $XAUTHORITY"
        auth_file=$(absolute_path "$XAUTHORITY" "$PWD")
        args+=(--env XAUTHORITY=/tmp/measurement.xauthority
            --mount "type=bind,source=$auth_file,target=/tmp/measurement.xauthority,readonly")
    fi
fi
args+=("$image" --log-level "${LOG_LEVEL:-INFO}" "$workflow")

if (( dry_run )); then
    if (( rebuild )); then "$REPO_ROOT/scripts/build_docker.sh" --dry-run; fi
    print_command "${args[@]}"
    exit 0
fi
require_command docker
if (( rebuild )) || ! docker image inspect "$image" >/dev/null 2>&1; then
    "$REPO_ROOT/scripts/build_docker.sh"
fi
mkdir -p -- "$results_dir"
if [[ -n "$cookie_dir" ]]; then
    mkdir -p -- "$cookie_dir"
    if [[ ! -e "$cookie_file" ]]; then
        (umask 077; set -C; : > "$cookie_file")
    fi
fi
exec "${args[@]}"
