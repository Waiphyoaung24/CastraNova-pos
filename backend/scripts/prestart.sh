#! /usr/bin/env bash

set -e
set -x

# Ensure the least-privilege app role exists before anything connects as it
# (runs on the admin connection; the db service is already `service_healthy`).
python app/ensure_app_role.py

# Let the DB start — probes with the runtime (app-role) engine, which now exists
python app/backend_pre_start.py

# Run migrations
alembic upgrade head

# Create initial data in DB
python app/initial_data.py
