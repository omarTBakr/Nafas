# Nafas — AI assistant for patients and doctors: master plan

## Context

Nafas is currently a bare FastAPI + Temporal skeleton (commit `cb4a8db`) with no domain code. It has a layered layout:
`routes/` → `workflows/` → `activities/` → `utils/`, plus `schemas/`, `interfaces/`, `prompts/`, `enums/` and `exceptions/`.
The goal is to ship v1 of a two-sided medical assistant.

- **Patient side:** runs on Telegram first, then email, with WhatsApp later. Input can be text or voice notes.
  - Book, reschedule or cancel an appointment, with the time checked to the minute against the doctor's real schedule.
  - After a booking is confirmed, chat about medical topics based on the patient's own history, limited to the doctor's specialization.
  - Sensitive questions go to the doctor instead of getting an answer from the model.
- **Doctor side:** a web dashboard.
  - See the schedule and the next patient.
  - Chat freely about any patient, with fewer restrictions than the patient side.
  - Upload reports, X-rays and scans, which feed a per-patient RAG.
  - Record sessions (in person now, online later). The model transcribes and summarizes each session, and the doctor approves the summary before it joins the patient's history.

Decisions confirmed with the user:
- Sessions: **both** in-person (recorded in the browser) and online video (in a later phase).
- Doctor UI: **web dashboard**.
- Tenancy: **multi-doctor platform**.
- Languages: **Arabic (including dialects) and English** for both text and voice.

---

## 1. Architecture

```
 Telegram ──┐                         ┌──────────── Doctor web dashboard (React/Vite, web/)
 Email ─────┤  webhooks               │  REST + SSE
 (WhatsApp)─┘                         ▼
        ┌──────────────── FastAPI (routes/) ────────────────┐
        │ channel webhooks · doctor API · auth · uploads    │
        └──────────────┬────────────────────────────────────┘
                       │ signal-with-start / update
                ┌──────▼──── Temporal (queue per service) ──┐
                │ workflows: conversation, booking,     │
                │ escalation, session, document ingest  │
                └──────┬────────────────────────────────┘
                       │ activities (thin) → utils (logic) → interfaces (ports)
   ┌──────────┬────────┼─────────┬──────────┬──────────┬───────────┐
 Postgres   S3 store  Claude     STT       Embeddings  Channel     LiveKit
 +pgvector  (files)   (LLM)    (Whisper-   (bge-m3,    senders     (phase 9)
                               class)      multiling.) (TG/email)
```

**Stack choices**
- **DB:** Postgres 16 with `pgvector`, accessed through SQLAlchemy 2 (async, asyncpg). Migrations use Alembic.
- **Files:** SeaweedFS (S3 API) locally and S3-compatible storage in production. Objects are keyed by `doctor/{id}/patient/{id}/...` and served through presigned URLs.
- **LLM (`interfaces/llm`):** Claude.
  - `claude-sonnet-5` for patient and doctor chat.
  - `claude-haiku-4-5` for the cheap classifiers (intent, scope, sensitivity, output guard).
  - `claude-opus-5-5` for session summaries.
  - Claude vision gives descriptive text for images that are uploaded to the doctor side. It is never a diagnosis.
- **Tracing:** LangSmith. Every Claude call is an LLM run through `@traceable(run_type="llm")` in `interfaces/llm/claude.py` (langsmith 0.14.1's `wrap_anthropic` breaks on anthropic 1.x), and each agent loop and pipeline step is decorated with `@traceable`, so a patient message shows up as one trace: intent → gates → retrieval → answer → guard.
  - It is off unless `LANGSMITH_TRACING=true`. The key comes from `LANGSMITH_API_KEY`, and `LANGSMITH_PROJECT` separates environments.
  - Traces carry prompts, and prompts carry PHI. Before any real patient data, either self-host LangSmith or set `LANGSMITH_HIDE_INPUTS`/`LANGSMITH_HIDE_OUTPUTS`, and never trace to the cloud from production without a data agreement.
- **STT (`interfaces/stt`):** a Protocol with two implementations.
  - Hosted Whisper-large-v3-class, used for voice notes.
  - A diarizing provider for sessions (doctor vs patient speakers).
  - Pick the vendors in a Phase 0 spike that tests Egyptian, Gulf and Levantine Arabic plus code-switching. The self-hosted candidates include `oddadmix/whisper-large-v3-arabic-dialectal-v2` and the other Arabic-dialect ASR fine-tunes by the same author, run as a GPU service beside the hosted vendors.
- **Dialect identification (`interfaces/dialect`, the `dialect-router` service on GPU):** [`oddadmix/dialect-router-v0.1`](https://huggingface.co/oddadmix/dialect-router-v0.1). It is a small BERT (`bert-mini-arabic`, MIT) that labels text with one of 12 codes from its `config.json`: ar (MSA), eg, sa, ma, iq, sd, tn, lb, sy, ly, ps, and en for English. The model card lists 11 and calls Moroccan `mo`; `config.json` is authoritative.
  - Uses: tagging transcripts and messages (for the STT spike, analytics and reply tone), and later choosing a dialect voice for TTS replies. Its home project, Lahgtna, is built for exactly that.
  - Limits: no published accuracy, unreliable on short or code-switched text, and adjacent dialects get confused. **It is never an input to a safety or clinical decision.** Before relying on it, evaluate it on our own labelled samples.
  - First probe, 2026-09-26, on an RTX 4060: 8 of 9 labelled sentences were right. Syrian came back as Palestinian (0.87). Code-switched "عندي pain في الـ chest" came back as MSA at 0.90, which is confidently wrong, and the low-confidence flag cannot catch that. "شكرا" was correctly flagged low-confidence (0.26).
- **Text-to-speech (`interfaces/tts`, the `tts` GPU service, Phase 3):** [`ehabnegm/lahgtna-omnivoice-egyptian-v3`](https://huggingface.co/ehabnegm/lahgtna-omnivoice-egyptian-v3), decided on 2026-09-26. It is an OmniVoice fine-tune (the `omnivoice` package, Apache-2.0) continued from `oddadmix/lahgtna-omnivoice-v2`, and reads raw, non-diacritized Egyptian text. The weights are Apache-2.0, about 2.4 GB, and run in fp16 alongside the dialect-router on 8 GB. It is pinned at `e859e1f49e2d45eb0d6dfc48e48e03697dfccc65`.
  - Routing: patients whose messages the dialect-router labels `eg` with confidence get voice replies. Everyone else gets text until there is a model for their dialect.
  - Voice: **zero-shot cloning from a reference recording Nafas owns, made with the speaker's written consent.** The two trained voices (Eqkawkab, Noselleel) come from YouTube creators' audio, their card asks for permission before commercial use, and v2 declares no licence. They are not shipped.
  - Safety: the model cannot say English words and mangles digits. So TTS speaks **booking and administrative messages only** (confirmations, reminders, "your question went to the doctor"). Clinical answers, drug names and doses are text-only, and every voice note is sent with its text. Numbers, dates and times are converted to words by our own code before synthesis, never left to the model.
- **Embeddings (`interfaces/embeddings`):** `bge-m3`, which is multilingual Arabic/English with 1024 dimensions. It sits behind a Protocol so a hosted model can replace it.
- **Channels (`interfaces/channels`):** a `ChannelAdapter` Protocol (`parse_inbound`, `send_text`, `send_voice`, `download_media`).
  - Implementations: `telegram` (aiogram, webhook mode) and `email` (inbound-parse webhook, SMTP out).
  - WhatsApp becomes one more file.
- **Web:** `web/` holds a React + Vite + TypeScript app.
  - Auth uses JWT in an httpOnly cookie, with argon2 password hashes.
  - In-person recording uses the browser MediaRecorder with chunked upload.
- **Online sessions (phase 9):** LiveKit (self-hosted or cloud), with Egress recording to S3.

### Why one database, not a database per doctor
- Patients can see several doctors.
- Migrations, backups and connection pools would multiply with every doctor.
- Cross-doctor admin and analytics would become impossible.

Instead: **one Postgres database where every clinical row carries `doctor_id`.**
- Postgres **row-level security** is keyed on `app.current_doctor_id`, set per transaction, so a missed `WHERE` clause cannot leak data.
- The per-minute booking guarantee comes from a **GiST exclusion constraint** per doctor, not from isolating databases.
- Enterprise clinics that need physical isolation can later get schema-per-tenant or a dedicated database, with no code change beyond the connection factory.

---

## 2. Database design

All times are `timestamptz` in UTC. Each doctor has an IANA `timezone` used for display and for parsing "tomorrow at 5".

**Identity and tenancy**
| Table | Key columns |
|---|---|
| `users` | id, email (unique), password_hash, role enum(doctor, admin, staff), is_active, last_login_at |
| `specializations` | id, code (unique, e.g. `cardiology`), name_en, name_ar, `scope_description` (text given to the scope classifier), `in_scope_topics` jsonb, `always_escalate` jsonb (topics that must go to the doctor) |
| `doctors` | id, user_id → users, full_name_en/ar, specialization_id → specializations, languages text[]. Booking settings live in the scheduling service (below) |
| `patients` | id, full_name, date_of_birth, sex, phone, email, preferred_language enum(ar, en), created_at |
| `patient_channels` | id, patient_id, channel enum(telegram, email, whatsapp), external_id, verified_at. Unique on (channel, external_id) |
| `doctor_patients` | doctor_id, patient_id, status enum(active, archived), first_seen_at. **This is the access-control boundary for every clinical query** |
| `consents` | id, patient_id, doctor_id, kind enum(data_processing, session_recording, ai_chat), granted_at, revoked_at, channel, evidence (message id) |

**Scheduling**
| Table | Key columns |
|---|---|
| `booking_settings` | doctor_id (PK), timezone, slot_minutes, buffer_minutes, min_notice_minutes, horizon_days, hold_minutes. No row means the doctor is not bookable yet |
| `availability_rules` | id, doctor_id, weekday 0-6, start_local time, end_local time, slot_minutes (nullable → doctor default), mode enum(in_person, online, both), effective_from/to |
| `time_off` | id, doctor_id, `during tstzrange`, reason |
| `appointments` | id, doctor_id, patient_id, starts_at, ends_at, `during tstzrange GENERATED`, status enum(held, confirmed, cancelled, completed, no_show), mode, hold_expires_at, meeting_url, reason_for_visit, booking_workflow_id, created_via channel. **`EXCLUDE USING gist (doctor_id WITH =, during WITH &&) WHERE (status IN ('held','confirmed'))`**. Requires the `btree_gist` extension |

**Conversations and safety**
| Table | Key columns |
|---|---|
| `conversations` | id, audience enum(patient, doctor), doctor_id, patient_id (the patient speaking, or the subject patient in a doctor chat, which is nullable for general doctor chat), channel, workflow_id |
| `messages` | id, conversation_id, role enum(user, assistant, doctor, system), modality enum(text, voice), content, audio_object_key, transcript_lang, intent enum, safety jsonb (classifier verdicts), model, tokens_in/out, created_at |
| `escalations` | id, doctor_id, patient_id, message_id, reason enum(sensitive, out_of_scope_medical, emergency, unclear), status enum(open, answered, closed, expired), doctor_reply, answered_at |

**Clinical record and RAG**
| Table | Key columns |
|---|---|
| `consultations` | id, appointment_id, doctor_id, patient_id, mode, recording_object_key, transcript jsonb (speaker-labelled segments), summary_draft jsonb (SOAP), summary_final jsonb, patient_summary (plain-language text), status enum(recording, transcribing, draft_ready, approved, failed), approved_by, approved_at |
| `history_entries` | id, patient_id, doctor_id, kind enum(visit_summary, diagnosis, medication, allergy, lab_result, procedure, note, intake), content, structured jsonb, source_type/source_id, **visibility enum(doctor_only, patient_visible)**, occurred_at, created_by |
| `documents` | id, patient_id, doctor_id, kind enum(report, xray, ct, mri, ultrasound, lab, prescription, other), object_key, mime, sha256, page_count, extracted_text, ai_description, status enum(uploaded, processing, indexed, failed), visibility, uploaded_by |
| `chunks` | id, patient_id, doctor_id, source_type enum(history, document, consultation), source_id, content, `embedding vector(1024)`, `tsv tsvector` (hybrid search), visibility, metadata jsonb. Indexes: HNSW on embedding and btree on (patient_id, doctor_id) |
| `audit_log` | id, actor_type, actor_id, action, resource_type, resource_id, at, ip. Every read of clinical data by a person or by the model is logged |

"RAG per patient" means **one `chunks` table, and every retrieval is filtered by `patient_id` plus `doctor_id` plus the allowed `visibility`.**
- Patient-side retrieval only sees `patient_visible` rows that the doctor has approved.
- Doctor-side retrieval sees everything for that doctor's patients.

---

## 3. Core flows (Temporal)

The Temporal conventions come from the existing README and `workflows/__init__.py`:
- no I/O inside workflows
- `imports_passed_through`
- `workflow.patched()` for any change to a workflow's shape
- one generation of workers per task queue

1. **`PatientConversationWorkflow`**: a long-lived entity workflow, ID `conv-{doctor_id}-{patient_id}`.
   - Webhooks **signal-with-start** it, so messages from one patient are processed strictly in order. The workflow also holds the conversation state, such as a booking in progress.
   - It uses `continue_as_new` every N messages.
   - Per message:
     - If the message is a voice note, transcribe it.
     - Run `classify_intent`, then route: booking tools, the medical pipeline, or an administrative reply.
     - Persist the result and send the reply.

2. **Booking** is tool-use with the LLM, and the LLM never states availability on its own authority. The tools are:
   - `find_slots(from, to, mode)`
   - `check_slot(start)`
   - `hold_slot(start)`
   - `confirm_hold`, `cancel`, `reschedule`

   Relative Arabic and English times ("بكرة بعد العصر", "next Tuesday 5:40") are handled in two steps:
   - The LLM only *extracts* a structured `TimeExpression`: a day reference, an hour and minute, am/pm, and a period such as asr.
   - `nafas_scheduling.logic.time_expressions.resolve` then does the date arithmetic in the doctor's timezone. It is pure code and unit-tested.
   - An hour without am/pm that nothing settles gives both candidates. The one inside the doctor's hours wins, or the agent asks. Nothing is guessed.
   - A patient may book any whole minute inside the doctor's hours (17:40, not just the grid). The grid only drives suggestions. Holds are inserted as `held` rows, so the exclusion constraint settles any race. **`BookingWorkflow`** takes over from there:
   - It waits for a `confirm` signal. The hold expires after 10 minutes, which releases the slot.
   - Once confirmed, it sends a confirmation (plus an `.ics` file for email).
   - It fires reminder timers at T-24h and T-1h.
   - It handles `cancel` and `reschedule` signals.
   - It marks the appointment `completed` or `no_show`.

3. **Patient medical pipeline**, which runs only when the patient has an active `doctor_patients` link and a confirmed or past appointment:
   1. **Emergency gate:** a deterministic keyword list (AR/EN) plus a Haiku classifier. On a hit, send a fixed emergency message with the local emergency number, open an `emergency` escalation, and notify the doctor.
   2. **Scope gate:** Haiku compares the question with `specializations.scope_description` and returns in_scope, out_of_scope_medical or non_medical.
   3. **Sensitivity gate:** the question goes to the doctor if it is a diagnosis request, a dose or medication change, interpretation of a new result, a matching `always_escalate` topic, or a mental-health crisis.
   4. **Answer:** Sonnet answers with RAG over patient-visible chunks and a conservative system prompt (`prompts/patient_chat.py`).
   5. **Output guard:** Haiku checks that the answer contains no diagnosis or prescription. If it does, the answer is replaced with an escalation.

   **`EscalationWorkflow`** tells the patient "I've forwarded this to Dr. X", puts the item in the doctor's inbox, and waits for the `doctor_replied` signal before relaying the reply. After a timeout it sends a follow-up nudge to both sides.

4. **Doctor chat** runs as a request/response route that calls utils directly, streamed over SSE. It does not need Temporal.
   - It uses Sonnet with a permissive clinical system prompt (`prompts/doctor_chat.py`).
   - RAG covers everything for the selected patient.
   - Tools: `get_patient_timeline`, `search_patient_docs`, `get_today_schedule`, `get_next_patient`.

5. **`DocumentIngestionWorkflow`**: upload → store in S3 → extract. Text PDFs are parsed directly, scanned pages get OCR, and images get a Claude vision description labelled "AI description, not a read". The result is then chunked, embedded and marked `indexed`.

6. **`ConsultationWorkflow`**: runs when a recording is uploaded, either from the browser recorder or from LiveKit Egress.
   - It needs the `session_recording` consent first.
   - Steps: transcribe with diarization → Opus SOAP summary plus a plain-language patient summary → status `draft_ready`, and the doctor is notified.
   - It then waits for the `approve` signal, which can come with edits.
   - After approval it writes the `history_entries` (a visit summary plus extracted meds, allergies and diagnoses), embeds them, and sends the patient their summary if the doctor chose to.

---

## 4. Services and code layout

Every feature is its own deployable service, and all of them live in one repository as a **uv workspace**. That was decided on 2026-09-26.
- Services coordinate through Temporal: each worker polls its own task queue, and workflows call activities across queues.
- Each service can be built, deployed, scaled and rolled back on its own.
- One shared library keeps settings, the database layer, the provider interfaces and the error hierarchy identical everywhere.

### Service map

| Service | Package | Runs | Task queue / port | Owns (Postgres schema) |
|---|---|---|---|---|
| gateway | `services/gateway` | FastAPI | :8000 | none. It is the HTTP edge for the dashboard: auth, then routes to domain services |
| channels | `services/channels` | FastAPI + worker | `channels` | the Telegram and email webhooks in; outbound sends as activities |
| identity | `services/identity` | FastAPI + worker | `identity` | `identity`: users, specializations, doctors, patients, patient_channels, doctor_patients, consents |
| scheduling | `services/scheduling` | worker (+ internal API) | `scheduling` | `scheduling`: availability_rules, time_off, appointments, and `BookingWorkflow` |
| conversation | `services/conversation` | worker | `conversation` | `conversation`: conversations, messages, escalations, plus `PatientConversationWorkflow`, the safety gates and `EscalationWorkflow` |
| doctor-assistant | `services/doctor_assistant` | FastAPI (SSE) | :8020 | none. Doctor chat, reading clinical data through the clinical-records API |
| clinical-records | `services/clinical_records` | FastAPI + worker | `clinical` | `clinical`: history_entries, documents, chunks, `DocumentIngestionWorkflow`, and RAG retrieval |
| consultation | `services/consultation` | worker | `consultation` | `consultation`: consultations and `ConsultationWorkflow` |
| dialect-router | `services/dialect_router` | FastAPI on **GPU** | :8410 | none. Arabic dialect identification (see §1) |
| tts | `services/tts` | FastAPI on **GPU** | :8440 | none. Egyptian TTS (Lahgtna OmniVoice v3), for administrative messages only |
| stt / embeddings | `services/stt`, `services/embeddings` | FastAPI on GPU, if self-hosted | :8420, :8430 | none. Built only if the vendor spike picks a self-hosted model |
| web | `web/` | static | :5173 | none. The doctor dashboard |

**Rules**
- A service reads and writes only its own schema.
- It gets anything else by calling the owning service: a Temporal activity on that service's queue, or its internal API.
- The one allowed coupling is foreign keys to `identity` (doctor_id, patient_id), so row-level security and referential integrity still hold.
- There is one Alembic history, at the repository root, covering every schema. This means migrations never race each other across services.
- Services are created when their phase starts, not ahead of time. An empty service is just maintenance.

### Shared library, `packages/core` (`nafas_core`)
- `config`, `logger` and `tracing` (LangSmith).
- `temporal`: the client, the worker factory, and `TaskQueue`, the enum naming every queue.
- `db`: the engine, `session_scope(doctor_id=...)` for RLS, and `Base`. Each service keeps its ORM models in its own package.
- `interfaces/{llm,stt,embeddings,storage,channels,dialect}`: a Protocol, the implementations, a fake and a factory.
- `enums` and `exceptions`: vocabulary shared across services.

### Inside a Python service (the original layer rules, per service)
`routes/` (HTTP, no logic) → `workflows/` (order, no I/O) → `activities/` (one side effect each) → `logic/` (the actual work, framework-free and unit-tested). Plus `schemas/` (dataclasses that cross Temporal), `prompts/`, `models.py` (ORM), and `worker.py` / `main.py` entrypoints. Tests live in each service's `tests/`.

Where the plan's earlier modules land:
- `utils/scheduling.py` goes to scheduling's `logic/`.
- `utils/safety.py` goes to conversation.
- `utils/rag.py` goes to clinical-records.
- Each LLM tool loop lives in the service that runs it.

### Containers
- Python services share one `docker/service.Dockerfile`, built with the package name as a build argument (`uv sync --package ...`).
- GPU services have their own CUDA Dockerfile.
- Compose runs against the **native Docker engine** through the `Makefile` (`DOCKER_CONTEXT=default`). Docker Desktop's VM cannot see the GPU.

---

## 5. Low-hanging fruit (cheap once the core exists; the user picks which ship in v1)

- **Reminders:** 24h and 1h before, plus "reply 1 to confirm / 2 to cancel". This is already inside `BookingWorkflow`.
- **Cancel or reschedule by chat**, plus a **waitlist** that offers a freed-up slot to the next patient.
- **Pre-visit intake:** the bot asks for the reason for the visit, symptoms, meds and allergies, and saves an `intake` history entry for the doctor.
- **Next-patient brief:** generated automatically 10 minutes before each appointment and pushed to the dashboard.
- **Post-visit patient summary and instructions** in the patient's language, sent after the doctor approves.
- **Voice replies (TTS)** for patients who send voice notes. **Chosen**: Lahgtna OmniVoice v3 for Egyptian, admin messages only (see §1).
- **`.ics` invites** by email, and Google Calendar export for the doctor.
- **No-show tracking** and a simple per-doctor stats page.

---

## 6. Compliance and safety baseline (not optional)

- Explicit consent at onboarding covers data processing and AI chat. Recording needs a separate consent every time.
- Every assistant message is labelled as from an AI assistant and not a doctor.
- Encryption: TLS in transit, and encrypted disk and bucket at rest.
- PHI stays out of logs; the logger redacts it.
- `audit_log` records every clinical read.
- LangSmith traces contain PHI, so the same vendor rules apply to them as to the LLM.
- The design targets the Egypt PDPL (Law 151/2020) and HIPAA-style controls. A zero-data-retention agreement with the LLM and STT vendors is needed before any real patients use the system.

---

## 6b. Production readiness (every model and every service, before production)

Here "model" means anything whose behaviour is learned or prompted: the dialect-router, the STT and embedding models, and every Claude call with its prompt. The same five gates apply to each one.

1. **Clear, reproducible model config.**
   - Every model is pinned exactly. Hugging Face models use a commit sha. Claude calls use a model ID plus a versioned prompt module under `prompts/`, and the prompt version is recorded on every trace and message.
   - Container images are pinned by digest in staging and production.
   - The service's config (model, revision, thresholds, batch sizes) lives in a versioned file inside the service, and the service reports it on `/health`. Anyone can then tell exactly what answered a request.
2. **Promotion rules and rollback conditions across dev → staging → prod.**
   - Each model has an eval set and pass thresholds, for example the safety-gate evals from Phase 5 and a labelled dialect set. CI runs them, and a change is promoted only if it passes.
   - Staging runs the candidate against replayed, de-identified traffic.
   - Production rolls out as a canary. It rolls back automatically on error-rate, latency or behavioural-metric regressions beyond set bounds, and by hand at any time by redeploying the previous pinned version.
   - Promotions and rollbacks are recorded, including who did it, what changed and why.
3. **Monitoring and observability, both behavioural and system.**
   - System: every service exposes Prometheus `/metrics` (request rate, latency histograms, errors, and GPU memory and utilisation for GPU services), plus structured logs and the Temporal UI. Grafana holds the dashboards and alerts.
   - Behavioural: LangSmith traces for every LLM call. Rates of escalations, refusals and output-guard triggers. The intent and scope mix. The confidence distribution of the dialect-router. Summary edit distance, meaning how much doctors change AI summaries. Alerts fire on drift from the baseline.
4. **Feedback → data pipeline.**
   - Signals are captured where they happen:
     - doctor edits to consultation summaries
     - doctor answers to escalations
     - thumbs up/down on doctor-chat answers
     - dialect predictions with low confidence
     - patient "that's wrong" replies
   - These signals go to a feedback store and to LangSmith datasets. Items are de-identified, and only included where consent covers training or evaluation.
   - They feed the next eval sets and the next model or prompt generation, and they catch regressions early.
5. **Infrastructure sized to the SLOs and able to scale.**
   - Each service has written SLOs, for example booking replies at p95 under 5 s, voice-note transcription at p95 under 10 s, 99.5 % availability, and escalations reaching the doctor in under 1 min.
   - A capacity plan sets requests per doctor and the GPU memory and throughput each GPU service needs. This dev machine has one RTX 4060 with 8 GB.
   - Load tests prove the SLOs. Services scale horizontally: stateless APIs and workers scale by replica count, and each Temporal queue scales by adding workers.

## 7. Execution checklist

Tracked in [CHECKLIST.md](CHECKLIST.md). Each item is ticked in the same commit that completes it.

---

## 8. Verification

- **Unit tests:** `utils/` is framework-free per the existing rules, covering scheduling, safety gating, RAG filtering and parsers. Run with `uv run pytest`.
- **DB tests:** a Postgres test container covers the exclusion constraint (two concurrent holds on overlapping minutes → one fails) and RLS isolation.
- **Workflow tests:** `temporalio.testing.WorkflowEnvironment.start_time_skipping()` with fake interfaces covers hold expiry, reminders, escalation timeouts and consultation approval.
- **LLM evals:** a fixed AR/EN dataset for the intent, scope, sensitivity and output guards and for booking-time extraction, with pass-rate thresholds.
- **End to end:** `docker compose up` plus a test Telegram bot.
  - Book by voice in Arabic, then confirm the row in the DB and the reminders in the Temporal UI.
  - Ask an in-scope question, an out-of-scope question and a sensitive one, and confirm the escalation appears in the dashboard and the doctor's reply reaches Telegram.
  - Upload a PDF and ask the doctor chat about it.
  - Record a short session, then approve it and confirm it appears in the timeline.
