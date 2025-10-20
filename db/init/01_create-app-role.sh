#!/usr/bin/env bash
set -euo pipefail

APP_ROLE_NAME="${APP_ROLE_NAME:-app}"
APP_ROLE_PASSWORD="${APP_ROLE_PASSWORD:-${POSTGRES_PASSWORD:-}}"
APP_DATABASE="${APP_DATABASE:-${POSTGRES_DB:-pickingdb}}"
APP_ROLE_SET_OWNER="${APP_ROLE_SET_OWNER:-true}"
DB_FOR_CONNECTION="${POSTGRES_DB:-postgres}"

if [[ -z "${APP_ROLE_PASSWORD}" ]]; then
  echo "[create-app-role] APP_ROLE_PASSWORD or PGPASSWORD must be provided" >&2
  exit 1
fi

unset PGHOST
unset PGPORT

escaped_app_role=$(printf "%s" "${APP_ROLE_NAME}" | sed "s/'/''/g")
escaped_app_password=$(printf "%s" "${APP_ROLE_PASSWORD}" | sed "s/'/''/g")
escaped_app_database=$(printf "%s" "${APP_DATABASE}" | sed "s/'/''/g")
escaped_set_owner=$(printf "%s" "${APP_ROLE_SET_OWNER}" | tr '[:upper:]' '[:lower:]')

PGPASSWORD="${POSTGRES_PASSWORD:-}" psql \
  --username "${POSTGRES_USER}" \
  --dbname "${DB_FOR_CONNECTION}" <<EOSQL
DO
\$do$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${escaped_app_role}') THEN
        EXECUTE format('CREATE ROLE %I WITH LOGIN PASSWORD %L', '${escaped_app_role}', '${escaped_app_password}');
    ELSE
        EXECUTE format('ALTER ROLE %I WITH LOGIN PASSWORD %L', '${escaped_app_role}', '${escaped_app_password}');
    END IF;

    IF '${escaped_set_owner}'::boolean THEN
        EXECUTE format('ALTER DATABASE %I OWNER TO %I', '${escaped_app_database}', '${escaped_app_role}');
    END IF;

    EXECUTE format('GRANT ALL PRIVILEGES ON DATABASE %I TO %I', '${escaped_app_database}', '${escaped_app_role}');
END
\$do$;
EOSQL

