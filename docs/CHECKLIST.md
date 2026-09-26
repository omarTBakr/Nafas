# Nafas — execution checklist

The order of work for [PLAN.md](PLAN.md), kept current as work happens: an item is marked **(in progress)** when work on it starts and ticked the moment it is done. Every phase ends with a green `make test`.

**Phase 0: Foundations**
- [x] Write `docs/PLAN.md` and `docs/CHECKLIST.md`
- [x] `docker-compose.yml` with postgres+pgvector, Temporal plus UI, and an S3 store (SeaweedFS — MinIO images are no longer published)
- [x] Add dependencies (sqlalchemy, asyncpg, alembic, pgvector, anthropic, langsmith, aiogram, aioboto3, pyjwt, argon2-cffi) and extend `Settings` and `.env.example`
- [x] `utils/db` engine, session and RLS helper; Alembic initialized
- [x] Protocols and factories for llm, stt, embeddings, storage and channels, with fake implementations for tests
- [x] LangSmith tracing: every Claude call traced as an LLM run with usage, a no-op unless `LANGSMITH_TRACING=true`
- [ ] `@traceable` on each agent loop and pipeline step as they are written (phases 3–7)
- [x] Restructure into a uv workspace: `packages/core` (`nafas_core`) and `services/gateway`; tests per package; CI and pre-commit updated
- [x] `Makefile` running compose on the native Docker engine (the GPU is unreachable from Docker Desktop)
- [x] `dialect-router` GPU service (FastAPI + transformers, CUDA image, model baked in at a pinned revision, config on `/health`, Prometheus `/metrics`, low-confidence predictions logged for feedback) and the `interfaces/dialect` client, fake and factory
- [x] STT choice recorded in PLAN.md: self-hosted `whisper-large-v3-turbo-arabic-dialectal-v2` (13 dialects, published per-dialect WER); validation on our own samples moves to Phase 3

**Phase 1: Doctors, specializations and scheduling core** (creates the `identity` and `scheduling` services)
- [x] Database roles: services connect as `nafas_service` (not the owner), so row-level security applies; `nafas_current_doctor()` for policies
- [x] `identity` service: migration for users, specializations, doctors, patients, patient_channels, doctor_patients, consents with RLS; isolation tests
- [x] `scheduling` service: migration for booking_settings, availability_rules, time_off, appointments (exclusion constraint, whole-minute check), with RLS
- [x] Seed specializations (AR/EN names, scope descriptions, always-escalate topics); doctors created by `nafas_identity.cli create-doctor`
- [x] Scheduling logic: slot generation, minute-exact checks with reasons, suggestions, hold/confirm/cancel, lapsed holds, `TimeExpression` resolution (the LLM extracts, code resolves); tests for DST, a real concurrent race, and minute precision
- [x] `nafas_scheduling.cli set-hours` / `time-off` for admins
- [x] Doctor auth: gateway `/api/auth/login|logout|me` (signed httpOnly session, account re-checked every request) over identity's internal API; admin-created accounts only

**Phase 2: The web app, and booking in the UI** (patient portal, doctor schedule; decided 2026-09-26: web only, no bots for now)
- [x] Patient accounts: a `patient` role, self sign-up in identity, `patients.user_id`; patient-scoped RLS (`nafas_current_patient()`, `session_scope(patient_id=...)`), and a narrow security-definer lookup for login
- [x] Doctor directory: doctors with their specialization, from identity's internal API
- [x] Scheduling internal API: free slots, check an exact time (with the reason and nearest alternatives), hold, confirm, cancel, a patient's and a doctor's appointments; patient actions looked up in the patient's own scope
- [x] Care link (`doctor_patients`): identity's idempotent `POST /care-links`, called on every booking
- [x] Gateway: `/api/auth/register`, `/api/doctors`, `/api/doctors/{id}/slots|check`, `/api/appointments` (hold, confirm, cancel, mine), `/api/doctor/schedule`, with a role check on every route; refusals relayed with their reason; an end-to-end test over all three services
- [x] `web/`: one React + Vite + TypeScript app, Arabic (RTL) and English; login and sign-up; patient portal (doctors → day and slot picker or an exact minute → hold with countdown → confirm → my appointments); doctor portal (today and this week); clinic-time helpers tested across DST
- [x] `web` in compose (nginx on :8088, proxying `/api`), CI job (typecheck, tests, build), and an end-to-end booking run through the UI in a real browser

**Phase 3: Booking by AI chat in the UI, text and voice** (creates `conversation`)
- [ ] `conversation` service: conversations and messages tables; `PatientConversationWorkflow` per patient and doctor (update-with-start, continue_as_new)
- [ ] Intent classifier; the booking tool loop on Claude (extract a `TimeExpression`, then find, check, hold, confirm, cancel through scheduling)
- [ ] Chat panel in the patient portal with streamed replies; chat and slot picker share the same holds
- [ ] `BookingWorkflow`: hold expiry and in-app reminders (T-24h, T-1h); Temporal time-skipping tests
- [ ] Patient dialect and voice: `dialect` (13 Lahgtna codes) and `voice` (male/female) on the patient, chosen at sign-up or in a profile page; the dialect-router suggests a default from early messages
- [ ] `stt` GPU service: `whisper-large-v3-turbo-arabic-dialectal-v2` pinned in a CUDA image, `/health` config, `/metrics`, and the `interfaces/stt` client and fake
- [ ] Voice input: record in the browser → STT → the same pipeline; audio in S3, transcript on the message; check English voice notes and fall back to base turbo for English patients if the fine-tune lost English
- [ ] Validate STT on our own labelled samples per dialect against the published WER
- [ ] `tts` GPU service: Lahgtna OmniVoice v2 (13 dialects, built-in voices, `language` = the patient's dialect) pinned in a CUDA image, `/health` config, `/metrics`, and the `interfaces/tts` client and fake
- [ ] Egyptian: side-by-side listening test of v2 and `lahgtna-omnivoice-egyptian-v3` (its default voices); use v3 for Egyptian only if it wins
- [ ] Text normaliser before TTS: numbers, dates and times to words in the patient's dialect; refuse text with Latin script or clinical content
- [ ] Voice replies in the patient's chosen dialect and voice, on admin messages only, always shown with the text
- [ ] Before any commercial deployment: clear the licences of the voice models' training audio (v2 has none declared; v3's voices come from YouTube creators)

**Phase 4: Patient medical chat and escalation**
- [ ] Evaluate the dialect-router on our labelled AR samples; tag messages with the dialect if it holds up
- [ ] Gates: emergency, scope, sensitivity and output guard (prompts plus the conversation service's safety logic)
- [ ] Patient-visible RAG retrieval
- [ ] `EscalationWorkflow` and the escalations table; the doctor's answer appears in the patient's chat
- [ ] Safety eval set (~150 AR/EN prompts covering in-scope, out-of-scope, sensitive and emergency) run in CI with threshold assertions

**Phase 5: Doctor dashboard** (creates `doctor_assistant`)
- [ ] The next-patient card
- [ ] Patient list and timeline (history, documents, consultations)
- [ ] Escalations inbox with a reply that appears in the patient's chat
- [ ] Doctor chat (SSE streaming, patient-scoped RAG and tools)

**Phase 6: Documents and RAG** (creates `clinical_records`)
- [ ] Upload route (presigned PUT) → `DocumentIngestionWorkflow`
- [ ] PDF text, OCR and image vision description; chunk, embed, hybrid search
- [ ] Visibility toggle per document

**Phase 7: In-person session recording** (creates `consultation`)
- [ ] Browser recorder with chunked upload and a recording-consent checkbox
- [ ] `ConsultationWorkflow`: diarized transcript → SOAP draft → doctor review/edit UI → approve → history and embeddings → optional patient summary

**Phase 8: Online sessions**
- [ ] LiveKit room per online appointment, with the link sent in the confirmation
- [ ] Egress recording to S3 that triggers `ConsultationWorkflow`

**Phase 9: Hardening and launch** (the production-readiness gates in PLAN.md §6b)
- [ ] Reproducible config: every model pinned (HF sha, Claude model ID plus prompt version on each trace), images pinned by digest, config reported on `/health`
- [ ] dev / staging / prod environments; eval gates in CI; staging replay; canary rollout with automatic rollback bounds; a promotion log
- [ ] Prometheus `/metrics` on every service, Grafana dashboards and alerts (system and behavioural), and drift alerts
- [ ] Feedback store and pipeline (summary edits, escalation answers, thumbs, low-confidence dialect items) into de-identified eval and training datasets
- [ ] Written SLOs per service, a capacity plan including GPU, load tests that prove them, and horizontal scaling per service and queue
- [ ] RLS policies verified by tests (doctor A cannot read doctor B's rows)
- [ ] Audit log, PHI log redaction, rate limiting on login, sign-up and chat
- [ ] Observability (structured logs, Temporal UI, error tracking)
- [ ] Chosen low-hanging-fruit features
- [ ] Deployment (compose → VM or k8s), backups, runbook

**Later: messaging channels** (deferred 2026-09-26; everything is in the web app for now)
- [ ] Telegram bot (shared bot, per-doctor deep links), voice notes through the same STT pipeline
- [ ] Email booking (inbound parse, SMTP out, `.ics` invites)
- [ ] WhatsApp
