-- Database roles, idempotent. Postgres runs this on a fresh volume (mounted
-- into /docker-entrypoint-initdb.d); `make db-roles` applies it to an existing
-- one; the test suite applies it to its own server.
--
--   nafas          owner and superuser: migrations only
--   nafas_app      NOLOGIN group: the privileges services need, granted by
--                  each service's migration
--   nafas_service  the test suite's login; not an owner and not a
--                  superuser, so row-level security actually applies to it
--   nafas_<service>_access   NOLOGIN: one service's tables and nothing else
--                            (the gateway's schema is called edge)
--   nafas_<service>_svc      what that service logs in as: nafas_app (so the
--                            row-level security policies apply to it) plus its
--                            own _access group, and no other service's
--
-- The password is for a laptop. Production creates nafas_service with a
-- secret from the secret store and never runs this file.

DO $$
DECLARE
    service text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nafas_app') THEN
        CREATE ROLE nafas_app NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nafas_service') THEN
        CREATE ROLE nafas_service LOGIN PASSWORD 'nafas' IN ROLE nafas_app;
    END IF;

    -- one database login per service, holding only that service's schema
    FOREACH service IN ARRAY ARRAY['identity', 'scheduling', 'conversation', 'clinical', 'consultation', 'edge'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nafas_' || service || '_access') THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN', 'nafas_' || service || '_access');
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nafas_' || service || '_svc') THEN
            EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L IN ROLE nafas_app, %I',
                'nafas_' || service || '_svc', 'nafas', 'nafas_' || service || '_access');
        END IF;
        -- the test suite's login sets up every service's rows
        EXECUTE format('GRANT %I TO nafas_service', 'nafas_' || service || '_access');
    END LOOP;
END
$$;
