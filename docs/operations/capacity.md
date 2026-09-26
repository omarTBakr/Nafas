# Capacity

## Measured, 2026-09-26

`scripts/load_test.py` against the gateway, identity, scheduling and
conversation, each its own process as deployed, on one 4-vCPU machine that
also ran Postgres, Temporal and the load generator itself. Each simulated
patient signs up, then loops through the doctor list, a week of free slots,
their appointments and their notices with 0.5 to 2 s between screens. That
is about 2.5 requests a second per user; a real patient does a small
fraction of that.

| Users | Requests/s | Errors | p95 doctors | p95 slots | p95 my appointments | p95 sign-up | Objectives |
|---|---|---|---|---|---|---|---|
| 50 | 131 | 0 | 107 ms | 243 ms | 187 ms | 1.0 s | all met |
| 100 | 149 | 0 | 319 ms | 1.01 s | 896 ms | 1.5 s | slots 13 ms over |

At 100 simulated users the machine is out of CPU; 130 to 150 requests a
second is what one replica of each service holds on shared hardware.

## What the load test found, and what changed

1. **The database pool churned.** SQLAlchemy's default keeps 5 connections
   and closes each of its 10 overflow connections after one use; under load
   every checkout past five opened a new connection, paying a TLS handshake
   and a SCRAM exchange (4096 hash iterations) each time. Identity spent most
   of its CPU there. The pool is now 20 kept and 10 overflow per process
   (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`): throughput doubled and p95s fell four-
   to fivefold at 50 users.
2. **Password hashing ran on the event loop.** argon2 spends ~50 ms of CPU by
   design; inline, every sign-up and login stalled every other request in the
   identity process. It runs in a thread now (argon2-cffi releases the GIL).
   Sign-up's median fell from 2.6 s to 1.0 s under the same load.
3. **Identity was asked about every request.** The gateway confirmed the
   session's account with identity on each call. It now remembers a confirmed
   account for 30 s (`SESSION_CHECK_SECONDS`): a disabled account keeps
   working for up to that long, which is the trade.

## Planning

- **Connections.** Each process holds up to `DB_POOL_SIZE + DB_MAX_OVERFLOW`
  (30) connections. Seven services at one replica each is 210 at the peak,
  over Postgres's default `max_connections` of 100: raise it to 300, or put
  PgBouncer (transaction mode) in front before adding replicas. The
  row-level security settings are transaction-local (`set_config(..., true)`),
  so transaction pooling is safe.
- **Scaling out.** Every API is stateless: sessions are signed cookies, rate
  limits are shared in Postgres (`RATE_LIMITS_SHARED`), the audit log is one
  table. Add replicas of the gateway, identity and scheduling first; the
  load test shows identity and the gateway saturating before scheduling.
- **Workers.** Each service's Temporal worker polls its own queue
  (`TaskQueue`), so more replicas of a service are also more workers for its
  workflows. Transcription and drafting are bound by the stt GPU and by
  Claude, not by the worker.
- **GPU.** One 8 GB card holds stt, the dialect-router and tts v2 (PLAN.md
  §6c). A 20-minute visit is 20 one-minute parts, transcribed one after
  another. The stt service's speed on the card is **not yet measured** (it
  needs the GPU: `make check-stt` reports the real-time factor and what it
  means for a 20-minute visit), so whether one visit drafts
  inside the 5-minute objective, and how many clinics can record at once
  before the card queues, is the first number to take on real hardware.

- **Model spend.** `nafas_llm_tokens_total` by model is on the dashboard;
  the classifiers (Haiku) run on every patient message, the chat model on
  each answer, the summary model (Opus) once per visit.

## Re-running

```
make up                      # or run the services as processes
uv run python -m scripts.load_test --users 50 --seconds 60
```

The gateway must trust the load generator's `X-Forwarded-For`
(`FORWARDED_ALLOW_IPS`), so each simulated patient has its own address and
the per-address sign-up limit sees many people rather than one. In staging
that is the load generator's address; never `*` in production.
