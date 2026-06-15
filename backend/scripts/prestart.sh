#! /usr/bin/env bash

set -e
set -x

# Ensure the least-privilege app role exists (admin/superuser connection) FIRST.
# On a fresh database the role does not exist yet, and backend_pre_start.py (and
# the app engine) authenticate as POSTGRES_APP_USER — so the role must be created
# before anything connects as it. Idempotent: creates the role or refreshes its
# password. The DB is already accepting connections (compose gates prestart on db
# `service_healthy`).
python app/ensure_app_role.py

# Let the DB start / confirm the app role can connect
python app/backend_pre_start.py

# Run migrations
alembic upgrade head

# Create initial data in DB
python app/initial_data.py
