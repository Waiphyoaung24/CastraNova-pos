#! /usr/bin/env bash

set -e
set -x

# Let the DB start
python app/backend_pre_start.py

# Ensure the least-privilege app role exists before migrations grant to it
python app/ensure_app_role.py

# Run migrations
alembic upgrade head

# Create initial data in DB
python app/initial_data.py
