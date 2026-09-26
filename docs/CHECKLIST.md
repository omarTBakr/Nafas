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

**Phase 5: Doctor dashboard** (creates `doctor_assistant`)
- [ ] The next-patient card
- [ ] Patient list and timeline (history, documents, consultations)
- [ ] Escalations inbox, extended: filters, history, and answering from the patient's timeline (the minimal inbox ships in Phase 4)
- [ ] Doctor chat (SSE streaming, patient-scoped RAG and tools)

**Phase 6: Documents and RAG** (creates `clinical_records`)
- [ ] Upload route (presigned PUT) → `DocumentIngestionWorkflow`
- [ ] PDF text, OCR and image vision description; chunk, embed, hybrid search
- [ ] Embeddings: bge-m3 on the CPU by default (decided 2026-09-26: the 8 GB GPU is spent on stt, the dialect-router and tts), behind the Protocol so a GPU or hosted model can replace it
- [ ] Visibility toggle per document

**Phase 7: In-person session recording** (creates `consultation`)
- [ ] Decide the diarization backend for consultations (open: pyannote's weights are gated on Hugging Face; compare it with a pyannote-free option on our own recordings)
- [ ] Browser recorder with chunked upload and a recording-consent checkbox
- [ ] `ConsultationWorkflow`: diarized transcript → SOAP draft → doctor review/edit UI → approve → history and embeddings → optional patient summary

**After v1: Online sessions** (moved out of v1 on review, 2026-09-26: LiveKit is a lot of infrastructure for what the first clinics need)
- [ ] LiveKit room per online appointment, with the link sent in the confirmation
- [ ] Egress recording to S3 that triggers `ConsultationWorkflow`

**Phase 9: Hardening and launch** (the production-readiness gates in PLAN.md §6b)
- [ ] Reproducible config: every model pinned (HF sha, Claude model ID plus prompt version on each trace), images pinned by digest, config reported on `/health`
- [ ] dev / staging / prod environments; eval gates in CI; staging replay; canary rollout with automatic rollback bounds; a promotion log
- [ ] Prometheus `/metrics` on every service, Grafana dashboards and alerts (system and behavioural), and drift alerts
- [ ] Feedback store and pipeline (summary edits, escalation answers, thumbs, low-confidence dialect items) into de-identified eval and training datasets
- [ ] Written SLOs per service, a capacity plan including GPU, load tests that prove them, and horizontal scaling per service and queue
- [ ] Rate limits and the audit log shared across replicas (Phase 3b's are per process and per database)
- [ ] Observability (structured logs, Temporal UI, error tracking)
- [ ] Chosen low-hanging-fruit features
- [ ] Deployment (compose → VM or k8s), backups, runbook

**Later: messaging channels** (deferred 2026-09-26; everything is in the web app for now)
- [ ] Telegram bot (shared bot, per-doctor deep links), voice notes through the same STT pipeline
- [ ] Email booking (inbound parse, SMTP out, `.ics` invites)
- [ ] WhatsApp

**Needs you** (cannot be done from a cloud session)
- [ ] Merge PR #1; after it, one PR per phase
- [ ] Add `ANTHROPIC_API_KEY` as an environment secret, so the prompts run against real Arabic dialect messages, not only a scripted model
- [ ] Run `uv lock` in `services/tts` where download.pytorch.org is reachable
- [ ] Run the GPU checks and the listening test (Phase 3b's scripts), a clinician's sign-off on the safety eval set (`services/conversation/evals/safety.jsonl`) and its thresholds, a native speakers' pass on the normaliser
- [ ] Labelled Arabic sentences for `make check-dialects`, to decide whether the dialect suggestion stays on
