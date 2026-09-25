-- Database roles, idempotent. Postgres runs this on a fresh volume (mounted
-- into /docker-entrypoint-initdb.d); `make db-roles` applies it to an existing
-- one; the test suite applies it to its own server.
--
--   nafas          owner and superuser: migrations only
--   nafas_app      NOLOGIN group: the privileges services need, granted by
--                  each service's migration
--   nafas_service  what services log in as; not an owner and not a
--                  superuser, so row-level security actually applies to it
--
-- The password is for a laptop. Production creates nafas_service with a
-- secret from the secret store and never runs this file.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nafas_app') THEN
        CREATE ROLE nafas_app NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nafas_service') THEN
        CREATE ROLE nafas_service LOGIN PASSWORD 'nafas' IN ROLE nafas_app;
    END IF;
END
$$;
