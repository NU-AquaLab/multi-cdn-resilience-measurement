#!/usr/bin/env bash
# Run one measurement per country through a dedicated Gluetun VPN container.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/docker_common.sh"

usage() {
    cat <<'HELP'
Usage: scripts/run_vpn_measurements.sh COMMAND COUNTRIES_FILE [--build] [--dry-run]

Run one workflow sequentially for each country in a text file (one name per
line, with optional blank lines and # comments). Measurement failures stop
the batch. Only containers created by this invocation are cleaned up.

Settings:
  ENV_FILE          Measurement configuration (default: repository .env).
  VPN_ENV_FILE      Gluetun configuration (default: repository .env.vpn).
  VPN_IMAGE         Gluetun image (default: qmcgaw/gluetun:v3.38.0).
  VPN_READY_TIMEOUT Seconds to wait for a healthy VPN (default: 180).
  DOCKER_IMAGE      Measurement image (default: measure-tiktok:latest).

collect-vod still requires an interactive terminal and X11 display. Gluetun
credentials are supplied through VPN_ENV_FILE and are never embedded here.
HELP
}
case "${1-}" in -h|--help) usage; exit 0 ;; esac
[[ $# -ge 2 ]] || { usage >&2; exit 2; }
workflow=$1
countries_file=$2
shift 2
valid_workflow "$workflow" || fail "Unknown workflow: $workflow"
[[ -f "$countries_file" ]] || fail "Country list not found: $countries_file"
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
VPN_ENV_FILE=${VPN_ENV_FILE:-"$REPO_ROOT/.env.vpn"}
[[ -f "$VPN_ENV_FILE" ]] || fail "VPN configuration not found: $VPN_ENV_FILE. Copy .env.vpn.example first."
VPN_ENV_FILE=$(cd -- "$(dirname -- "$VPN_ENV_FILE")" && printf '%s/%s' "$PWD" "$(basename -- "$VPN_ENV_FILE")")
vpn_image=${VPN_IMAGE:-qmcgaw/gluetun:v3.38.0}
timeout=${VPN_READY_TIMEOUT:-180}
[[ "$timeout" =~ ^[1-9][0-9]*$ ]] || fail 'VPN_READY_TIMEOUT must be a positive integer'
provider=$(setting VPN_PROVIDER '')
if [[ -z "$provider" ]]; then provider=$(env_file_value "$VPN_ENV_FILE" VPN_SERVICE_PROVIDER ''); fi

countries=()
while IFS= read -r country || [[ -n "$country" ]]; do
    country=${country%$'\r'}
    country=${country#"${country%%[![:space:]]*}"}
    country=${country%"${country##*[![:space:]]}"}
    [[ -n "$country" && "$country" != \#* ]] || continue
    countries+=("$country")
done < "$countries_file"
(( ${#countries[@]} > 0 )) || fail 'Country list is empty'

vpn_name=''
measurement_name=''
vpn_owned=0
measurement_owned=0
child_pid=''
cleanup() {
    if (( measurement_owned )); then
        docker rm -f "$measurement_name" >/dev/null 2>&1 || true
        measurement_owned=0
    fi
    if [[ -n "$child_pid" ]]; then
        kill "$child_pid" 2>/dev/null || true
        wait "$child_pid" 2>/dev/null || true
        child_pid=''
    fi
    if (( vpn_owned )); then
        docker rm -f "$vpn_name" >/dev/null 2>&1 || true
        vpn_owned=0
    fi
}

if (( ! dry_run )); then
    require_command docker
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    if (( rebuild )) || ! docker image inspect "${DOCKER_IMAGE:-measure-tiktok:latest}" >/dev/null 2>&1; then
        "$REPO_ROOT/scripts/build_docker.sh"
    fi
elif (( rebuild )); then
    "$REPO_ROOT/scripts/build_docker.sh" --dry-run
fi

run_id="$$-$RANDOM"
index=0
for country in "${countries[@]}"; do
    index=$((index + 1))
    vpn_name="measure-tiktok-vpn-$run_id-$index"
    measurement_name="measure-tiktok-$workflow-$run_id-$index"
    vpn_args=(docker run --rm -d --cap-add=NET_ADMIN --device /dev/net/tun
        --name "$vpn_name" --add-host host.docker.internal:host-gateway
        --env-file "$VPN_ENV_FILE" --env "SERVER_COUNTRIES=$country" "$vpn_image")
    printf 'Measurement %d/%d: %s (%s)\n' "$index" "${#countries[@]}" "$workflow" "$country"
    if (( dry_run )); then
        print_command "${vpn_args[@]}"
        printf '# Wait for VPN health, then run:\n'
        ENV_FILE="$ENV_FILE" VPN_CONTAINER="$vpn_name" CONTAINER_NAME="$measurement_name" VPN_PROVIDER="$provider" \
            "$REPO_ROOT/scripts/run_docker.sh" "$workflow" --dry-run
        print_command docker rm -f "$vpn_name"
        continue
    fi
    # Never take ownership of a pre-existing container, even if names collide.
    for name in "$vpn_name" "$measurement_name"; do
        if docker container inspect "$name" >/dev/null 2>&1; then
            fail "Container name already exists: $name"
        fi
    done
    vpn_owned=1
    "${vpn_args[@]}" >/dev/null
    deadline=$((SECONDS + timeout))
    while :; do
        state=$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$vpn_name")
        case "$state" in
            'running healthy') break ;;
            'running starting') ;;
            *) fail "VPN is not healthy for $country (state: $state)" ;;
        esac
        (( SECONDS < deadline )) || fail "VPN did not become healthy within ${timeout}s for $country"
        sleep 2
    done
    measurement_owned=1
    # Explicit stdin forwarding keeps manual VOD login usable in a batch.
    ENV_FILE="$ENV_FILE" VPN_CONTAINER="$vpn_name" CONTAINER_NAME="$measurement_name" VPN_PROVIDER="$provider" \
        "$REPO_ROOT/scripts/run_docker.sh" "$workflow" <&0 &
    child_pid=$!
    status=0
    wait "$child_pid" || status=$?
    child_pid=''
    cleanup
    if (( status != 0 )); then exit "$status"; fi
done
