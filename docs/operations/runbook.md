# Runbook

Where the alerts in `deploy/prometheus/alerts.yml` point, and what to do.
Commands are for the deploy host; `dc` is
`docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file /etc/nafas/prod.env`.

## A service is down

`ServiceDown`: Prometheus has not reached a service for 2 minutes.

1. `dc ps` and `dc logs --tail=200 <service>`. A service that will not start
   says why in its first lines: a start check (`will not start in prod: ...`)
   names the setting to fix.
2. `dc up -d <service>`; then `make release-check`.
3. Each API keeps answering while Temporal is away (the worker waits and
   joins when it returns), so a Temporal outage shows as workflows not
   advancing, not as a service down: check `dc logs temporal`.
4. Postgres down takes everything with it: `dc logs postgres`, disk space
   first (`df -h`), then restore from backup if the volume is lost.

## Errors

`HighErrorRate`: more than 2% of a service's requests fail.

1. The dashboard's error panel names the service; its logs (JSON, one line
   each) name the route and the exception. Patient data is redacted out of
   every log line before it is written.
2. A service failing because another is down fails in the caller too: look
   at the callee first (the gateway calls every service; conversation calls
   identity, scheduling and clinical-records).
3. After a deploy: roll back (docs/operations/deploy.md).

## The model is failing

`ModelErrors`: more than 5% of Claude calls fail.

Every safety gate fails closed, so patients are safe but their medical
questions go to their doctors instead of being answered, and chat replies
may fail. Check the provider's status page and the logs' status codes: 401
is the key (rotate `ANTHROPIC_API_KEY`), 429 is our rate limit (the
workspace's limits, or a runaway loop: the tokens panel shows which model),
5xx is the provider. Tell the clinics if it lasts: their inbox will fill.

## Behaviour drift

`GuardBlockingMore`, `GatesFailingClosed`, `VisitNotesMostlyRewritten`:
the models are behaving differently from when the evals passed.

1. What changed: a deploy (prompt versions are on `/health`), or the model
   behind an ID. The dashboard's model panel shows which model's calls moved.
2. Run the safety eval against production's configuration
   (`uv run pytest services/conversation/tests/test_safety_eval.py` with the key).
3. Read examples: `make export-feedback` (patients who opted in) shows
   thumbs-down replies and doctor edits, de-identified.
4. Roll back a prompt change; for a model change, pin the previous model ID
   in `LLM_*_MODEL` and redeploy.

## Emergency spike

`EmergencySpike`: more than 10 emergency escalations in an hour.

Either something real (a cluster of sick patients, a doctor's patients
after an event) or the keyword gate matching something harmless. The
escalations are in each doctor's inbox marked as emergencies. Read a few
(as the doctor, or in the audit trail); a false positive is fixed by
tightening the pattern in `services/conversation/nafas_conversation/logic/intent.py`
with a case added to `evals/safety.jsonl`, never by removing a pattern
without a clinician.

## Backups

- `make backup` daily at least, and before every prod deploy, with
  `AGE_RECIPIENT` set so the backup is encrypted; copy it off the host.
- `make restore-drill BACKUP=<dir>` monthly and before a risky migration: it
  restores into a scratch database, checks the migration head, the tables
  and the object checksums, and touches nothing live. (Decrypt an `.age`
  backup first with the private key, on a machine that is not the backup host.)
- A real restore: stop the services, `pg_restore --clean` into `nafas`, run
  `deploy/postgres/roles.sql` and `set-passwords.sh` if it is a new server,
  `scripts/backup_storage.py restore <dir>/objects`, start the services,
  `make release-check`.

## Rotating a secret

- `INTERNAL_API_TOKEN`, `METRICS_TOKEN`: change in the env file, `dc up -d`
  (every service reads it at start; for a moment callers and callees
  disagree and internal calls fail with 403 until all have restarted).
- `JWT_SECRET`: the same, and every session ends: everyone logs in again.
- A database password: `set-passwords.sh` with the new value, then restart
  that one service.
- `ANTHROPIC_API_KEY`: a new key in the console, the env file, `dc up -d`, then revoke the old one.

## Patient data seen where it should not be

Treat as an incident from the first minute: note the time, what was seen and
by whom. The audit log (`audit.audit_log`, readable only by the owner role)
records every read of clinical data with who, what and when; it answers
"who else saw this". Stop the leak (revoke a session by disabling the
account; roll back a release), then follow the clinic's breach procedure
and the applicable law's notification deadlines.
