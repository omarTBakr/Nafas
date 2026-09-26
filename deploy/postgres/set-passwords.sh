#!/bin/sh
# Gives each service's database login its own password from the environment,
# replacing the laptop password roles.sql sets. Run once per environment, and
# again whenever a password is rotated (then restart that service):
#
#   docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file /etc/nafas/prod.env \
#     exec -T -e EDGE_DB_PASSWORD -e IDENTITY_DB_PASSWORD ... postgres sh < deploy/postgres/set-passwords.sh
#
# Each variable is required; nothing is changed unless all are set.
set -eu
: "${EDGE_DB_PASSWORD:?}" "${IDENTITY_DB_PASSWORD:?}" "${SCHEDULING_DB_PASSWORD:?}" "${CONVERSATION_DB_PASSWORD:?}"
: "${CLINICAL_DB_PASSWORD:?}" "${CONSULTATION_DB_PASSWORD:?}"

psql -v ON_ERROR_STOP=1 -U nafas -d nafas \
  -v edge="$EDGE_DB_PASSWORD" -v identity="$IDENTITY_DB_PASSWORD" -v scheduling="$SCHEDULING_DB_PASSWORD" \
  -v conversation="$CONVERSATION_DB_PASSWORD" -v clinical="$CLINICAL_DB_PASSWORD" -v consultation="$CONSULTATION_DB_PASSWORD" <<'SQL'
ALTER ROLE nafas_edge_svc PASSWORD :'edge';
ALTER ROLE nafas_identity_svc PASSWORD :'identity';
ALTER ROLE nafas_scheduling_svc PASSWORD :'scheduling';
ALTER ROLE nafas_conversation_svc PASSWORD :'conversation';
ALTER ROLE nafas_clinical_svc PASSWORD :'clinical';
ALTER ROLE nafas_consultation_svc PASSWORD :'consultation';
-- the test suite's login has no place outside a laptop
ALTER ROLE nafas_service NOLOGIN;
SQL
echo "service passwords set; nafas_service can no longer log in"
