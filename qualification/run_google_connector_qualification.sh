#!/bin/sh
set -eu

: "${PORT:?PORT is required}"

python -m qualification.google_connector_preflight

exec uvicorn server.cloud_app:app --host 0.0.0.0 --port "$PORT"
