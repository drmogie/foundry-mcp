#!/bin/sh
# Turns Home Assistant add-on options into relay settings, then starts the relay.
set -e

OPT=/data/options.json

get() {
  jq -r --arg k "$1" 'if has($k) and .[$k] != null then .[$k] | tostring else empty end' "$OPT"
}

export DATA_DIR=/data
export PORT=3011
export LOG_LEVEL="$(get log_level)"
export LOG_LEVEL="${LOG_LEVEL:-info}"
export ADMIN_USERNAME="$(get admin_username)"
export ADMIN_PASSWORD="$(get admin_password)"

echo "Starting FGA Relay on port ${PORT} (log level: ${LOG_LEVEL})"
cd /app
exec python -m app
