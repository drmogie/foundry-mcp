#!/bin/sh
# Turns Home Assistant add-on options into relay settings, then starts the relay.
set -e

OPT=/data/options.json

get() {
  jq -r --arg k "$1" 'if has($k) and .[$k] != null then .[$k] | tostring else empty end' "$OPT"
}

export APP_ENV=production
export DB_TYPE=sqlite
export PORT=3010
export DATA_DIR=/data
export STATIC_DIR=/app/static

LOG_LEVEL="$(get log_level)"
export LOG_LEVEL="${LOG_LEVEL:-info}"

DISABLE_REGISTRATION="$(get disable_registration)"
export DISABLE_REGISTRATION="${DISABLE_REGISTRATION:-false}"

PER_MINUTE_REQUEST_LIMIT="$(get per_minute_request_limit)"
export PER_MINUTE_REQUEST_LIMIT="${PER_MINUTE_REQUEST_LIMIT:-0}"

ADMIN_EMAIL="$(get admin_email)"
ADMIN_PASSWORD="$(get admin_password)"
if [ -n "$ADMIN_EMAIL" ] && [ -n "$ADMIN_PASSWORD" ]; then
  export ADMIN_EMAIL ADMIN_PASSWORD
fi

echo "Starting Foundry REST API Relay on port ${PORT} (log level: ${LOG_LEVEL})"
exec /app/relay
