# Nafas — execution checklist

The order of work for [PLAN.md](PLAN.md). Each item is ticked in the same commit that completes it; every phase ends with a green `uv run pytest`.

**Phase 0: Foundations**
- [x] Write `docs/PLAN.md` and `docs/CHECKLIST.md`
- [x] `docker-compose.yml` with postgres+pgvector, Temporal plus UI, and an S3 store (SeaweedFS — MinIO images are no longer published)
- [x] Add dependencies (sqlalchemy, asyncpg, alembic, pgvector, anthropic, langsmith, aiogram, aioboto3, pyjwt, argon2-cffi) and extend `Settings` and `.env.example`
- [x] `utils/db` engine, session and RLS helper; Alembic initialized
- [x] Protocols and factories for llm, stt, embeddings, storage and channels, with fake implementations for tests
- [x] LangSmith tracing: every Claude call traced as an LLM run with usage, a no-op unless `LANGSMITH_TRACING=true`
- [ ] `@traceable` on each agent loop and pipeline step as they are written (phases 2–8)
- [x] Restructure into a uv workspace: `packages/core` (`nafas_core`) and `services/gateway`; tests per package; CI and pre-commit updated
- [x] `Makefile` running compose on the native Docker engine (the GPU is unreachable from Docker Desktop)
- [x] `dialect-router` GPU service (FastAPI + transformers, CUDA image, model baked in at a pinned revision, config on `/health`, Prometheus `/metrics`, low-confidence predictions logged for feedback) and the `interfaces/dialect` client, fake and factory
- [ ] STT vendor spike on Arabic dialect samples, with the decision recorded in PLAN.md

**Phase 1: Doctors, specializations and scheduling core** (creates the `identity` and `scheduling` services)
- [ ] Migrations: users, specializations, doctors, availability_rules, time_off, patients, patient_channels, doctor_patients, consents, appointments (with the exclusion constraint)
- [ ] Seed specializations (AR/EN scope descriptions) and a demo doctor
- [ ] `utils/scheduling.py`: slot generation, holds and confirm, timezone handling, natural-time parsing; unit tests including DST, overlap races and minute precision
- [ ] Doctor auth routes (login/logout/me) and admin-created doctor accounts

**Phase 2: Telegram and booking by text** (creates `channels` and `conversation`)
- [ ] Telegram adapter (webhook, secret-token check) and the `/telegram/webhook` route
- [ ] Patient onboarding: link the chat to a patient, capture name, phone and language, and record consent
- [ ] `PatientConversationWorkflow` (signal-with-start, continue_as_new)
- [ ] Intent classifier prompt and activity
- [ ] Booking tool loop and `BookingWorkflow` (hold → confirm → reminders → cancel/reschedule)
- [ ] Temporal time-skipping tests for hold expiry and reminders

**Phase 3: Voice**
- [ ] Download Telegram voice notes → STT → the same pipeline; store audio in S3 and the transcript on the message
- [ ] Arabic and English voice booking tested end to end
- [ ] `tts` GPU service: Lahgtna OmniVoice v3 pinned at its sha in a CUDA image, `/health` config, `/metrics`, and the `interfaces/tts` client and fake
- [ ] Reference voice: record one with the speaker's written consent, and store it with that consent
- [ ] Text normaliser before TTS: numbers, dates and times to Egyptian words; refuse text with Latin script or clinical content
- [ ] Voice replies for Egyptian patients (dialect-router `eg`, confident) on admin messages, always sent with the text

**Phase 4: Email channel**
- [ ] Email adapter (inbound-parse webhook, SMTP out, threading by Message-ID)
- [ ] `.ics` in the confirmation email

**Phase 5: Patient medical chat and escalation**
- [ ] Evaluate the dialect-router on our labelled AR samples; tag inbound messages with the dialect if it holds up
- [ ] Gates: emergency, scope, sensitivity and output guard (prompts plus `utils/safety.py`)
- [ ] Patient-visible RAG retrieval
- [ ] `EscalationWorkflow` and the escalations table
- [ ] Safety eval set (~150 AR/EN prompts covering in-scope, out-of-scope, sensitive and emergency) run in CI with threshold assertions

**Phase 6: Doctor dashboard** (fills `gateway`, creates `doctor_assistant`)
- [ ] `web/` scaffold with login
- [ ] Today and week schedule, and the next-patient card
- [ ] Patient list and timeline (history, documents, consultations)
- [ ] Escalations inbox with a reply that relays to the patient
- [ ] Doctor chat (SSE streaming, patient-scoped RAG and tools)

**Phase 7: Documents and RAG** (creates `clinical_records`)
- [ ] Upload route (presigned PUT) → `DocumentIngestionWorkflow`
- [ ] PDF text, OCR and image vision description; chunk, embed, hybrid search
- [ ] Visibility toggle per document

**Phase 8: In-person session recording** (creates `consultation`)
- [ ] Browser recorder with chunked upload and a recording-consent checkbox
- [ ] `ConsultationWorkflow`: diarized transcript → SOAP draft → doctor review/edit UI → approve → history and embeddings → optional patient summary

**Phase 9: Online sessions**
- [ ] LiveKit room per online appointment, with the link sent in the confirmation
- [ ] Egress recording to S3 that triggers `ConsultationWorkflow`

**Phase 10: Hardening and launch** (the production-readiness gates in PLAN.md §6b)
- [ ] Reproducible config: every model pinned (HF sha, Claude model ID plus prompt version on each trace), images pinned by digest, config reported on `/health`
- [ ] dev / staging / prod environments; eval gates in CI; staging replay; canary rollout with automatic rollback bounds; a promotion log
- [ ] Prometheus `/metrics` on every service, Grafana dashboards and alerts (system and behavioural), and drift alerts
- [ ] Feedback store and pipeline (summary edits, escalation answers, thumbs, low-confidence dialect items) into de-identified eval and training datasets
- [ ] Written SLOs per service, a capacity plan including GPU, load tests that prove them, and horizontal scaling per service and queue
- [ ] RLS policies verified by tests (doctor A cannot read doctor B's rows)
- [ ] Audit log, PHI log redaction, rate limiting on webhooks
- [ ] Observability (structured logs, Temporal UI, error tracking)
- [ ] Chosen low-hanging-fruit features
- [ ] Deployment (compose → VM or k8s), backups, runbook
