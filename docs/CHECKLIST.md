# Nafas — execution checklist

The order of work for [PLAN.md](PLAN.md), kept current as work happens: an item is marked **(in progress)** when work on it starts and ticked the moment it is done. Every phase ends with a green `make test`.

**Phase 0: Foundations**
- [x] Write `docs/PLAN.md` and `docs/CHECKLIST.md`
- [x] `docker-compose.yml` with postgres+pgvector, Temporal plus UI, and an S3 store (SeaweedFS — MinIO images are no longer published)
- [x] Add dependencies (sqlalchemy, asyncpg, alembic, pgvector, anthropic, langsmith, aiogram, aioboto3, pyjwt, argon2-cffi) and extend `Settings` and `.env.example`
- [x] `utils/db` engine, session and RLS helper; Alembic initialized
- [x] Protocols and factories for llm, stt, embeddings, storage and channels, with fake implementations for tests
- [x] LangSmith tracing: every Claude call traced as an LLM run with usage, a no-op unless `LANGSMITH_TRACING=true`
- [x] `@traceable` on each agent loop and pipeline step (`nafas_core.tracing.step`): a patient's message is one trace (turn, intent, medical, the three gates, context retrieval, the booking agent and its tools); the doctor assistant, record search and visit-note drafts too; clients never appear in a trace's inputs
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
- [x] `conversation` service: conversations and messages tables; `PatientConversationWorkflow` per patient and doctor (update-with-start, continue_as_new), its worker in compose
- [x] The booking tool loop on Claude: a versioned prompt; tools that only reach scheduling (`interpret_time` resolves and checks what the model extracted, then hold, confirm, cancel, my appointments), bound to one patient and doctor, times in clinic time; tested with a scripted model
- [x] Intent routing: an emergency keyword gate (AR/EN, code only) before a Haiku classifier; booking, admin and small talk to the agent, emergencies and medical questions to fixed replies until phase 4
- [x] Chat panel in the patient portal; chat and slot picker share the same holds (a hold made in chat is confirmed on its card, in the picker or under my appointments); in-app notifications page with an unread count; verified in a real browser against the real services with a scripted model
- [x] Replies arrive whole with a typing indicator (decided 2026-09-26: no token streaming for the patient chat; a reply is one workflow update and the agent calls tools before it answers, so streaming would need a side channel for little gain)
- [x] `BookingWorkflow`: hold expiry and in-app reminders (T-24h, T-1h), completion or a doctor's no-show, notices when a doctor cancels; tests on the time-skipping server, or in seconds on a real Temporal where it cannot be fetched
- [x] Patient dialect and voice: `dialect` (13 Lahgtna codes) and `voice` (male/female) on the patient, chosen at sign-up or on the profile page (`/api/me/profile`, patient scope)
- [x] The dialect-router suggests a default from a patient's first chat messages: confident readings are stored on each message, three or more mostly agreeing suggest a dialect on the profile page, which the patient may accept; it never overrides a choice
- [x] `stt` GPU service: `whisper-large-v3-turbo-arabic-dialectal-v2` pinned in a CUDA image with ffmpeg, `/health` config, `/metrics` (incl. realtime factor), and the `interfaces/stt` HTTP client; runs on the RTX 4060 at ~12× realtime, and the card's Egyptian and Iraqi samples (wav and browser webm/opus) come back within a word or two of their references
- [x] Voice input: record in the browser → S3 → STT → the same pipeline, transcript on the message, a voice note that says nothing asked again; played back from a short-lived link only its patient can open; verified in Chromium with its fake microphone against the real gateway and S3
- [ ] On the GPU: check English voice notes, and fall back to base turbo for English patients if the fine-tune lost English (the language hint already reaches the stt service)
- [ ] Validate STT on our own labelled samples per dialect against the published WER
- [x] `tts` GPU service: Lahgtna OmniVoice v2 (13 dialects, built-in voices, `language` = the patient's dialect) pinned in a CUDA image, Egyptian v3 behind a flag, `/health` config and per-dialect support, `/metrics`, and the `interfaces/tts` client and fake (written against omnivoice 0.2.1's `generate`; not yet run on the GPU)
- [ ] Egyptian: side-by-side listening test of v2 and `lahgtna-omnivoice-egyptian-v3` (its default voices); use v3 for Egyptian only if it wins
- [x] Text normaliser before TTS: numbers, dates and times to words in the patient's dialect; refuse text with Latin script or clinical content; a time without am/pm is not given a part of the day
- [x] Voice replies in the patient's chosen dialect and voice, on booking, admin and small-talk replies to a voice note only, never before the patient chooses a dialect, always shown with the text
- [ ] Before any commercial deployment: clear the licences of the voice models' training audio (v2 has none declared; v3's voices come from YouTube creators)
- [ ] On the GPU: confirm the Lahgtna fine-tune knows its dialect names (`GET /health` on the tts service lists each; the base OmniVoice drops unknown names to language-agnostic)
- [ ] Native speakers review the normaliser's number and time words per dialect (Egyptian and a near-formal set today; Maghrebi and Levantine counting not covered)

**Phase 3b: Before any patient's medical data** (moved up from Phase 9 on review, 2026-09-26)
- [x] Consent: data processing recorded at sign-up (platform-wide, the box is required), AI chat per doctor before the first message; chat and voice refused with `consent_required` without both; shown and revocable on the profile; each records the wording's version as its evidence
- [x] Rate limits on login (per address and per account), sign-up (per address), chat and voice notes (per patient), answered 429 with Retry-After; the client address comes from X-Forwarded-For, trusted only from FORWARDED_ALLOW_IPS
- [x] PHI kept out of logs: every record from every logger is cleaned as it is made, tracebacks included (SQL parameters, emails, phone numbers, Arabic text); ids, dates and times are kept
- [x] Append-only audit log of every clinical read, by a person or the model (`audit.audit_log`: services may insert, never read, change or delete); today a doctor reading patient names, a patient reading a thread, the model reading one to answer; later phases add their reads
- [x] Cross-doctor isolation sweep: every table under row-level security is checked, doctor B sees none of doctor A's rows and patient B none of another patient's, nothing is visible without a scope; the sweep fails on a table with no rows to check, or with no row-level security and no stated reason
- [x] Per-service database logins (found by the sweep: every service logged in as one role that could read `identity.users`): each service's schema is held by its own role, `nafas_app` keeps only what all share (the policies' role, the scope functions, appending to the audit log)
- [x] Email beside the in-app notices, for confirmations (with an .ics invite), reminders, lapsed holds and a doctor's cancellation, in the patient's language and clinic time, nothing clinical; patients can turn it off on the profile; off until SMTP_HOST is set, Mailpit on a laptop; the workflow step is `patched`, and a failed email never fails a booking
- [x] One-command scripts for the checks that need the GPU or a person: `make check-stt CLIPS=...` (WER per dialect beside the published figures, and the English fallback decision), `make check-tts` (dialect support and a sample each), `make listening-test` (a blind v2/v3 page with a separate key, then `score`), `make normaliser-sheet` (a CSV for native speakers); each run against the real services' code with fakes behind them

**Phase 4: Patient medical chat and escalation**
- [x] Evaluate the dialect-router on our labelled AR samples: `make check-dialects SAMPLES=...` (accuracy per dialect, confusions, what the low-confidence flag catches); messages are tagged only when it is confident, and the tag is never an input to safety
- [x] Gates: emergency, scope, sensitivity and output guard (versioned prompts, forced tool verdicts, every gate fails closed; a plain-code rule sends any dose or change of medicine to the doctor); only for patients under the doctor's care with a confirmed or past visit; verdicts stored on each reply
- [x] Patient-visible retrieval as a port: the patient's own visits with this doctor today; the patient-visible clinical record plugs in with Phase 6
- [x] `EscalationWorkflow` and the escalations table; the patient is told in fixed words, nudged after a day, the question expires after three; the doctor's answer appears in the patient's chat as theirs; emergencies open one too
- [x] Minimal escalations inbox for the doctor (open questions with the patient's name, emergencies marked, reply in place, a count in the top bar), tested end to end through the gateway
- [x] Safety eval set: 150 prompts (Egyptian, Gulf, Levantine, Maghrebi, formal Arabic and English; emergencies, diagnoses, medicines and doses, results, mental health, pregnancy and children, general, out of scope, not medical) with the outcome each must get. Its plain-code checks run in CI and found seven gaps in the keyword and medication rules, now fixed; the model run gates CI with thresholds (emergencies 100%, sensitive 98%) once `ANTHROPIC_API_KEY` is a repository secret

**Phase 5: Doctor dashboard** (creates `doctor_assistant`; built after Phase 6, on review)
- [x] The next-patient card: today's next confirmed visit (or one a few minutes late) with a brief: last visit, recent entries, questions waiting, documents on file
- [x] Patient list (under care only) and timeline: appointments, notes, documents and escalated questions from the services that hold them; notes with a sharing choice, uploads straight to storage, share and unshare, open a document; consultations join it with Phase 7
- [x] Escalations inbox, extended: filters (open, answered, expired), and answering from the patient's timeline
- [x] Doctor chat in the `doctor_assistant` service, streamed over SSE through the gateway: a colleague's prompt, read-only tools bound to the doctor and the patient the dashboard selected (timeline, record search, today's schedule, next patient); history kept by the browser, every read audited where it happens

**Phase 6: Documents and RAG** (creates `clinical_records`; built before Phase 5 on review, 2026-09-26: the timeline and doctor chat read it)
- [x] Upload route (presigned PUT) → `DocumentIngestionWorkflow`; only for patients under the doctor's care; a document that cannot be read is marked failed with the reason
- [x] PDF text, OCR (Tesseract, Arabic and English) for scanned pages and images, a Claude vision description labelled "AI description, not a read"; chunked at sentence ends with overlap, embedded, hybrid search (vectors and words, fused by reciprocal rank); the patient's assistant searches in the patient's scope, so only shared passages come back; every read audited
- [x] Embeddings: bge-m3 on the CPU by default in the `embeddings` service (decided 2026-09-26: the 8 GB GPU is spent on stt, the dialect-router and tts), behind the Protocol so a GPU or hosted model can replace it; not yet pinned to a commit (see Needs you)
- [x] Visibility per document and per history entry, carried to its passages in the same transaction

**Phase 7: In-person session recording** (creates `consultation`)
- [x] Diarization for v1: none. Timed transcript parts, the summary model tells speakers apart by content, the doctor approves every draft (PLAN.md §6c); a backend can be added behind the stt interface later
- [x] Consent to record, asked afresh for every recording and recorded by the patient's own doctor
- [x] Browser recorder: the doctor confirms consent, parts of 60 s each PUT straight to storage with their offset (retried), discard at any point before filing
- [x] `ConsultationWorkflow` on its own queue: transcript in visit time → Opus SOAP draft as a forced tool call (the model's doubts listed for the doctor) → review and edit page → approve → idempotent history entries, embedded, doctor-only → the patient's plain-language summary only if the doctor shares it; a discard deletes the audio, transcript and draft; silence or repeated failure marks it failed with the reason
- [x] Recorded visits on the doctor's timeline and in the inbox ("notes to review", counted in the badge); the patient's "My records" page (shared entries and documents, which they can now open); the doctor assistant reads only approved entries, never drafts
- [x] Browser check in Chromium against the real services (fake microphone, scripted STT and model): two parts, review with an edit, approval, the patient sees only the shared summary

**After v1: Online sessions** (moved out of v1 on review, 2026-09-26: LiveKit is a lot of infrastructure for what the first clinics need)
- [ ] LiveKit room per online appointment, with the link sent in the confirmation
- [ ] Egress recording to S3 that triggers `ConsultationWorkflow`

**Phase 9: Hardening and launch** (the production-readiness gates in PLAN.md §6b)
- [x] Reproducible config: Claude model IDs and prompt versions on every service's `/health` with the environment and commit (baked into each image), third-party and base images pinned by digest, the STT model pinned; bge-m3 still to pin (see Needs you)
- [x] dev / staging / prod: `ENVIRONMENT`, and start-up checks that refuse laptop secrets, open proxies, insecure cookies, per-process limits, unversioned builds and cloud tracing with prompts visible; `docker-compose.prod.yml` requiring every secret and publishing only the web proxy; promotion with its gates (CI including the safety eval, staging release check, load test, eval, a person's walk-through), rollback by image tag with additive migrations, a promotion log (docs/operations/deploy.md)
- [x] Prometheus `/metrics` on every service (requests by route template, model calls and tokens, gate verdicts, escalations, bookings, visit-note outcomes, reply ratings, workflow failures), a Grafana dashboard, system and behavioural alerts with promtool tests in CI
- [x] Feedback: thumbs on the assistant's replies; an optional `service_improvement` consent; `make export-feedback` writes de-identified rated replies, escalations with the doctor's answers, visit notes (draft against approved) and eval candidates, for human review; the run is audited
- [x] SLOs and a capacity plan from a real load test (docs/operations/slo.md, capacity.md); it found and fixed database pool churn (throughput doubled, p95 down 4-5x), argon2 on the event loop, and identity asked on every request; `make load-test` gates on the SLOs
- [x] Rate limits shared across replicas in Postgres (the gateway's own `edge` schema, keys hashed); the audit log was already one table
- [x] Observability: JSON logs (`LOG_FORMAT=json`), redacted as before; metrics and alerts above; the Temporal UI; error tracking through the error-ratio alerts and logs rather than a third-party service
- [x] Low-hanging fruit: patients open the documents shared with them; "My records"; notes to review counted in the doctor's badge; `disable-account` / `enable-account`
- [x] Deployment on one compose host, backups (database and objects, checksums, encrypted with `age`), a restore drill that was run, a runbook for every alert, secret rotation, a release check
- [x] Browser recording and the image build are proven here only up to what the sandbox allows; CI builds an image for real

**Later: messaging channels** (deferred 2026-09-26; everything is in the web app for now)
- [ ] Telegram bot (shared bot, per-doctor deep links), voice notes through the same STT pipeline
- [ ] Email booking (inbound parse, SMTP out, `.ics` invites)
- [ ] WhatsApp

**Needs you** (cannot be done from a cloud session)
- [ ] Before real patients: a lawyer's and a clinician's read of the consent texts (data processing, AI chat, recording, service improvement), the retention periods, and the breach procedure the runbook points to
- [ ] A staging host and a production host (GPU for stt, tts and the dialect-router), their secrets, and a first promotion recorded in docs/operations/promotions.md
- [ ] Measure the stt service's real-time factor on the GPU (`make check-stt` now reports it): it sizes the card for recorded visits
- [ ] Decide how long consultation audio is kept after approval (kept for now; deleted on discard) and whether the approved note should be locked or amendable with an audit trail
- [ ] Merge PR #1; after it, one PR per phase
- [ ] Add `ANTHROPIC_API_KEY` as an environment secret, so the prompts run against real Arabic dialect messages, not only a scripted model
- [ ] Run `uv lock` in `services/tts` where download.pytorch.org is reachable
- [ ] Run the GPU checks and the listening test (Phase 3b's scripts), a clinician's sign-off on the safety eval set (`services/conversation/evals/safety.jsonl`) and its thresholds, a native speakers' pass on the normaliser
- [ ] Labelled Arabic sentences for `make check-dialects`, to decide whether the dialect suggestion stays on
- [ ] Pin bge-m3 (`services/embeddings/embeddings/model.toml`) to a Hugging Face commit, and lock `services/embeddings` where download.pytorch.org is reachable
