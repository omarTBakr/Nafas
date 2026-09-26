# Environments, deploys and promotion

## Environments

| | dev | staging | prod |
|---|---|---|---|
| Where | a laptop, `make up` | its own host, `docker-compose.prod.yml` | its own host, `docker-compose.prod.yml` |
| `ENVIRONMENT` | `dev` | `staging` | `prod` |
| Secrets | laptop defaults in `docker-compose.yml` | its own, from the secret store | its own, never shared with staging |
| Data | made up | made up, or production data de-identified by `scripts/export_feedback.py` | patients |
| Model | scripted in tests, a real key when set | the real key, its own workspace | the real key, its own workspace |
| Tracing | optional | self-hosted LangSmith only | self-hosted LangSmith only |

Staging and prod refuse to start on laptop defaults (`nafas_core.startup`):
default or short secrets, the laptop database password, insecure cookies, a
proxy list of `*`, per-process rate limits, an unversioned build, or cloud
tracing with prompts visible. A missing secret stops `docker compose up`
before anything starts (`${VAR:?}` in `docker-compose.prod.yml`).

## A first deploy

1. A host with Docker, a GPU for stt, tts and the dialect-router, and a TLS
   proxy in front of `web` (the only published port). The proxy's address is
   `FORWARDED_ALLOW_IPS`.
2. `/etc/nafas/<env>.env` from the secret store, with every variable
   `docker-compose.prod.yml` requires (`deploy/ci/placeholder.env` lists them),
   and the S3 identities file it names.
3. Images: `make images` on a clean checkout of the release commit tags every
   image with `IMAGE_TAG=<commit>` and bakes the commit into it.
4. `docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file /etc/nafas/<env>.env up -d postgres`,
   then the service passwords: `deploy/postgres/set-passwords.sh` (it also
   stops the test suite's login from logging in).
5. Migrations, as the one-off job: `... run --rm migrate`.
6. The bucket: `... run --rm gateway python -m scripts.init_storage` (or create it in the managed S3).
7. Everything else: `... up -d`, then `make release-check IMAGE_TAG=<commit> ENVIRONMENT=<env>`.
8. Doctors: `nafas_identity.cli` creates their accounts and `nafas_scheduling.cli` their hours.

## Promotion: a commit's way to production

A commit reaches prod only through staging, and only as the same images.

1. **CI is green** on the commit: tests, lint, web, the alert rules, the
   production compose file, the image build, and the safety eval against the
   real model (the `safety-eval` job, which needs `ANTHROPIC_API_KEY`).
2. **Staging deploy**: build (`make images`), migrate, `up -d`, and
   `make release-check` must pass: every service on the commit, in staging.
3. **Staging gates**:
   - `make load-test` against staging passes its SLOs (docs/operations/slo.md);
   - the safety eval passes against staging's own model configuration;
   - a person books, chats, records a visit and approves it in staging.
4. **Prod deploy**: the same `IMAGE_TAG`, never a rebuild; `make backup` first,
   then migrate, `up -d`, `make release-check`.
5. **Watch** the dashboard for an hour: error ratio, p95s, model errors, the
   behavioural panels. Any page-level alert in that hour means rolling back.
6. **Record it** in `docs/operations/promotions.md`: date, commit, who, the
   load-test and eval results, anything odd.

### Rolling back

`IMAGE_TAG=<previous commit> ... up -d`, then `make release-check` with that
tag. Images roll back; the schema does not. So every migration is additive
first (a new column is nullable or defaulted, nothing the previous release
reads is dropped or renamed), and removals ship a release later, once no
running code reads what they remove. A migration that cannot follow this is
called out in its commit and deployed with a fresh backup and a restore
drill beforehand.

### Canary

A single compose host has no traffic splitting, so there is no canary
between releases on it. What stands in for one: staging's gates on the same
images, the first hour's watch, and the rollback above. With more than one
host, put a new release behind the proxy for one host first and compare its
error ratio and p95 with the others' before moving the rest.
