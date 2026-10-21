#!/usr/bin/env bash
# Shared path and configuration helpers. This file is sourced, not executed.

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

# Docker env files are data, never shell scripts: do not source or eval them.
env_file_value() {
    local file=$1 key=$2 fallback=${3-} line found=0 value=''
    while IFS= read -r line || [[ -n "$line" ]]; do
        line=${line%$'\r'}
        if [[ "$line" == "$key="* ]]; then
            value=${line#*=}
            found=1
        fi
    done < "$file"
    if (( found )); then
        printf '%s' "$value"
    else
        printf '%s' "$fallback"
    fi
}

setting() {
    local key=$1 fallback=${2-}
    if [[ ${!key+x} ]]; then
        printf '%s' "${!key}"
    else
        env_file_value "$ENV_FILE" "$key" "$fallback"
    fi
}

absolute_path() {
    local value=$1 base=$2
    case "$value" in
        /*) printf '%s' "$value" ;;
        *) printf '%s/%s' "$base" "$value" ;;
    esac
}

resolve_env_file() {
    ENV_FILE=${ENV_FILE:-"$REPO_ROOT/.env"}
    [[ -f "$ENV_FILE" ]] || fail "Configuration not found: $ENV_FILE. Copy .env.example to .env first."
    ENV_FILE=$(cd -- "$(dirname -- "$ENV_FILE")" && printf '%s/%s' "$PWD" "$(basename -- "$ENV_FILE")")
    # Consumed by the launchers that source this helper.
    # shellcheck disable=SC2034
    ENV_DIR=$(dirname -- "$ENV_FILE")
}

print_command() {
    printf '%q ' "$@"
    printf '\n'
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

valid_workflow() {
    case "$1" in
        collect-vod|collect-live|fallback-live|fallback-vod|fallback-iterative) return 0 ;;
        *) return 1 ;;
    esac
}
