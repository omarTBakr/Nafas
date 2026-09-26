# Nafas — AI assistant for patients and doctors: master plan

## Context

Nafas is currently a bare FastAPI + Temporal skeleton (commit `cb4a8db`) with no domain code. It has a layered layout:
`routes/` → `workflows/` → `activities/` → `utils/`, plus `schemas/`, `interfaces/`, `prompts/`, `enums/` and `exceptions/`.
The goal is to ship v1 of a two-sided medical assistant.

- **Patient side:** the Nafas web app. Messaging channels (Telegram, email, WhatsApp) are deferred and may be added later. Input can be text or voice recorded in the browser.
  - Sign up, pick a doctor by specialization, and book with a slot picker or by talking to the assistant. The time is checked to the minute against the doctor's real schedule.
  - Reschedule or cancel an appointment.
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
- 2026-09-26: **everything in the web app**. One React app has a patient portal and a doctor portal. Patients sign up themselves and choose a doctor, and book with a slot picker plus the AI chat, by text or voice. The Telegram and email bots are deferred.
- Tenancy: **multi-doctor platform**.
- Languages: **Arabic (including dialects) and English** for both text and voice.

---

## 1. Architecture

```
         Nafas web app (React/Vite, web/): patient portal + doctor portal
                                      │  REST + SSE
                                      ▼
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
 +pgvector  (files)   (LLM)    (Whisper-   (bge-m3,    senders     (phase 8)
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
- **STT (`interfaces/stt`, the `stt` GPU service), decided 2026-09-26:** [`oddadmix/whisper-large-v3-turbo-arabic-dialectal-v2`](https://huggingface.co/oddadmix/whisper-large-v3-turbo-arabic-dialectal-v2), self-hosted and pinned at `b12b09bc6601f2116410ccc9716596de0301c24a` (Apache-2.0).
  - It is Whisper large-v3-turbo (809M) fine-tuned on a dialect-balanced set of the same 13 dialects the voices cover. Published WER is 0.332 overall, against 0.320 for the 1.5B large-v3 at twice the size. Per dialect it ranges from Saudi (0.17), Iraqi, Egyptian and Syrian (about 0.27) to Tunisian (0.48, the hardest).
  - It is one model for every dialect, with no dialect switch. The patient's chosen dialect is for the voice and the reply style.
  - Open question for Phase 3: English voice notes. The fine-tune may have lost English, so test it, and fall back to the base turbo model for English-language patients if needed.
  - Consultation recordings (Phase 7) run through the same model in parts, each part keeping its time offset. v1 has no acoustic speaker separation (§6c).
- **Dialect identification (`interfaces/dialect`, the `dialect-router` service on GPU):** [`oddadmix/dialect-router-v0.1`](https://huggingface.co/oddadmix/dialect-router-v0.1). It is a small BERT (`bert-mini-arabic`, MIT) that labels text with one of 12 codes from its `config.json`: ar (MSA), eg, sa, ma, iq, sd, tn, lb, sy, ly, ps, and en for English. The model card lists 11 and calls Moroccan `mo`; `config.json` is authoritative.
  - Uses: tagging transcripts and messages (for the STT spike, analytics and reply tone), and later choosing a dialect voice for TTS replies. Its home project, Lahgtna, is built for exactly that.
  - Limits: no published accuracy, unreliable on short or code-switched text, and adjacent dialects get confused. **It is never an input to a safety or clinical decision.** Before relying on it, evaluate it on our own labelled samples.
  - First probe, 2026-09-26, on an RTX 4060: 8 of 9 labelled sentences were right. Syrian came back as Palestinian (0.87). Code-switched "عندي pain في الـ chest" came back as MSA at 0.90, which is confidently wrong, and the low-confidence flag cannot catch that. "شكرا" was correctly flagged low-confidence (0.26).
- **Text-to-speech (`interfaces/tts`, the `tts` GPU service, Phase 3), decided 2026-09-26: the patient chooses their dialect and hears a built-in voice.**
  - [`oddadmix/lahgtna-omnivoice-v2`](https://huggingface.co/oddadmix/lahgtna-omnivoice-v2) (pinned `55c38a613e316499829eef60b006edc6da9499e2`) speaks **13 dialects**: Egyptian, Saudi, Moroccan, Bahraini, Sudanese, Iraqi, Lebanese, Syrian, Libyan, Palestinian, Tunisian, Algerian and Yemeni. The dialect is the model's `language` (`"egyptian lahgtna"` → `eg`, …). The voice is its built-in one, optionally steered to male or female. There is no reference recording and no cloning. It reads diacritized text.
  - For Egyptian, [`ehabnegm/lahgtna-omnivoice-egyptian-v3`](https://huggingface.co/ehabnegm/lahgtna-omnivoice-egyptian-v3) (pinned `e859e1f49e2d45eb0d6dfc48e48e03697dfccc65`, Apache-2.0) with its two trained voices. It is Egyptian-only, but clearly better there: round-trip CER is 0.063 against 0.109 for the base, it holds up on long replies, and it reads raw text with no diacritizer. It is used only if it also wins a side-by-side listen against v2's Egyptian voice.
  - Each is about 2.4 GB of weights and runs in fp16. With STT and the dialect-router, they fit on the 8 GB GPU.
  - Voice notes were trained on third-party audio. v2 declares no licence on Hugging Face, and v3's two voices come from YouTube creators whose card asks for permission before commercial use. Both are fine for development. Clear them before any commercial deployment.
  - **The patient picks their dialect** (and optionally a male or female voice) in their profile. The dialect-router only *suggests* a default from their first messages, and never overrides the choice. The choice also sets the dialect Claude replies in.
  - Safety is unchanged: TTS speaks **booking and administrative messages only**. Clinical answers, drug names and doses stay text-only, every voice note is shown with its text, and numbers, dates and times are converted to words by our code, not the model.
- **Embeddings (`interfaces/embeddings`):** `bge-m3`, which is multilingual Arabic/English with 1024 dimensions. It sits behind a Protocol so a hosted model can replace it.
- **Channels (`interfaces/channels`), deferred:** a `ChannelAdapter` Protocol (`parse_inbound`, `send_text`, `send_voice`, `download_media`) is kept for when Telegram, email or WhatsApp return. Each would be one module plus the `channels` service.
- **Web:** `web/` holds a React + Vite + TypeScript app.
  - Auth uses JWT in an httpOnly cookie, with argon2 password hashes.
  - In-person recording uses the browser MediaRecorder with chunked upload.
- **Online sessions (phase 8):** LiveKit (self-hosted or cloud), with Egress recording to S3.

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
| `users` | id, email (unique), password_hash, role enum(doctor, patient, admin, staff), is_active, last_login_at |
| `specializations` | id, code (unique, e.g. `cardiology`), name_en, name_ar, `scope_description` (text given to the scope classifier), `in_scope_topics` jsonb, `always_escalate` jsonb (topics that must go to the doctor) |
| `doctors` | id, user_id → users, full_name_en/ar, specialization_id → specializations, languages text[]. Booking settings live in the scheduling service (below) |
| `patients` | id, user_id → users (their web login), full_name, dialect (one of the 13, chosen by the patient), voice (male, female), date_of_birth, sex, phone, email, preferred_language enum(ar, en), created_at. Visible to the patient themself and to linked doctors |
| `patient_channels` | id, patient_id, channel enum(telegram, email, whatsapp), external_id, verified_at. Unique on (channel, external_id). Unused until messaging channels return |
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
   - Once confirmed, it shows the confirmation in the app.
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
   - Steps: transcribe the recorded parts in order → Opus SOAP summary plus a plain-language patient summary → status `draft_ready`, and the doctor is notified.
   - The recording can be discarded at any point before approval, and then its audio is deleted.
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
| gateway | `services/gateway` | FastAPI | :8000 | none. It is the web app's HTTP edge: sessions for patients and doctors, a role check on every route, then the call to the owning service |
| channels (deferred) | `services/channels` | FastAPI + worker | `channels` | Telegram and email, when they return |
| identity | `services/identity` | FastAPI + worker | `identity` | `identity`: users, specializations, doctors, patients, patient_channels, doctor_patients, consents |
| scheduling | `services/scheduling` | worker (+ internal API) | `scheduling` | `scheduling`: availability_rules, time_off, appointments, and `BookingWorkflow` |
| conversation | `services/conversation` | worker | `conversation` | `conversation`: conversations, messages, escalations, plus `PatientConversationWorkflow`, the safety gates and `EscalationWorkflow` |
| doctor-assistant | `services/doctor_assistant` | FastAPI (SSE) | :8020 | none. Doctor chat, reading clinical data through the clinical-records API |
| clinical-records | `services/clinical_records` | FastAPI + worker | `clinical` | `clinical`: history_entries, documents, chunks, `DocumentIngestionWorkflow`, and RAG retrieval |
| consultation | `services/consultation` | worker | `consultation` | `consultation`: consultations and `ConsultationWorkflow` |
| dialect-router | `services/dialect_router` | FastAPI on **GPU** | :8410 | none. Arabic dialect identification (see §1) |
| tts | `services/tts` | FastAPI on **GPU** | :8440 | none. Lahgtna OmniVoice: 13 dialects (v2), Egyptian v3 if it wins the listening test; administrative messages only |
| stt | `services/stt` | FastAPI on **GPU** | :8420 | none. Arabic-dialect Whisper turbo |
| embeddings | `services/embeddings` | FastAPI on GPU | :8430 | none. bge-m3, when documents arrive (Phase 6) |
| web | `web/` | static | :5173 | none. One React app: the patient portal and the doctor portal |

**Who may do what (patients and doctors share one web app)**
- The gateway checks the session role on every route. Patient routes act only on the logged-in patient, and doctor routes act only on the logged-in doctor.
- Row-level security has two scopes. `session_scope(doctor_id=...)` shows a doctor's rows, and `session_scope(patient_id=...)` shows a patient's own rows (their profile and their appointments with any doctor).
- Booking is done by the scheduling service *on the patient's behalf*, inside the doctor's scope, because checking a slot means reading the doctor's whole calendar. The patient only ever receives their own appointment back. The care link to the doctor is created on the first booking.

**Rules**
- A service reads and writes only its own schema, enforced by the database: each logs in with a role that holds only its schema. The one exception is appending to `audit.audit_log` (§6c).
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
- **Voice replies (TTS)** for patients who send voice notes. **Chosen**: Lahgtna OmniVoice in the patient's chosen dialect (13), admin messages only (see §1).
- **Calendar export** (`.ics` download) for patients and doctors, and Google Calendar sync for the doctor.
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
   - Each model has an eval set and pass thresholds, for example the safety-gate evals from Phase 4 and a labelled dialect set. CI runs them, and a change is promoted only if it passes.
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

## 6c. Review, 2026-09-26 (after Phase 3)

Changes agreed after the booking chat and voice landed:

- **Safety work moves before medical data.** Consent, rate limits, PHI-free logs, the audit log and a cross-doctor isolation sweep move from Phase 9 to a new Phase 3b, ahead of Phase 4, because Phase 4 is where a patient's own history first reaches the model.
  - Consent is two records: `data_processing` once at sign-up, platform-wide (so `consents.doctor_id` becomes nullable), and `ai_chat` per doctor before the first chat message. The chat refuses a patient without it.
  - The audit log lives in its own `audit` schema that every service may append to and none may read or change. It is the one exception to "a service writes only its own schema", like the foreign keys into `identity`: an audit trail a service could edit would prove nothing.
  - Rate limits in 3b are per process; limits shared across replicas come with scaling in Phase 9.
- **Reminders also go by email.** In-app notices reach only patients who open the app, so confirmations, reminders and a doctor's cancellation are also emailed (SMTP). Email booking stays deferred.
- **A minimal escalations inbox ships with Phase 4**, so an escalation can be tested end to end; Phase 5 extends it.
- **No token streaming in the patient chat.** A reply is one workflow update, and the booking agent calls tools before it answers; replies arrive whole with a typing indicator. Doctor chat (Phase 5) is request/response and can stream over SSE as planned.
- **Online sessions move after v1.** LiveKit adds a media server, egress and TURN for what the first clinics do not need yet.
- **GPU budget.** The 8 GB card holds stt, the dialect-router and tts v2. Egyptian v3 loads only if it wins the listening test, and embeddings (bge-m3) run on the CPU by default.
- **Decided at Phase 7: v1 ships without diarization.** pyannote's weights are gated on Hugging Face and neither option could be compared on our own recordings from here. The transcript is kept as timed parts, the summary model tells doctor from patient by what is said (questions, examination, advice), and nothing reaches the record until the doctor has read and approved the draft. A diarization backend can be added behind the stt interface later without changing the workflow; the choice stays open for when clinic recordings exist to compare on.
  - Browser recording is cut into 60-second parts, each uploaded straight to storage with its own link, so a dropped connection loses one part at most.
- **Checks only a person or the GPU can do** get one-command scripts: STT WER per dialect on labelled clips, the tts service's dialect support, a v2/v3 listening page, and a review sheet of the normaliser's number and time words for native speakers.
- **Found by the isolation sweep:** every service logged in as `nafas_service`, whose group could read every schema, including the password hashes in `identity.users`. Each service now logs in as `nafas_<service>_svc`, which holds its own schema through `nafas_<service>_access` and no other. `nafas_app` is still the role the row-level security policies name, so every login is in it, but it holds no tables. "A service reads and writes only its own schema" is now enforced by the database, not only by convention.
- **Found while building tts:** the base OmniVoice package drops a language name it does not know and speaks language-agnostic. Whether the Lahgtna fine-tune registers names like `"egyptian lahgtna"` can only be seen with the weights, so the service reports it per dialect on `/health` and refuses a dialect it does not know.

- **Found in Phase 9:** the load test showed each process opening a new database connection (TLS and SCRAM) for most requests under load, because the default pool closes its overflow after one use; pools are now sized per process, and Postgres or PgBouncer must be sized for them (docs/operations/capacity.md). Password hashing ran on the event loop; it runs in a thread. The gateway asked identity about the account on every request; it now trusts a confirmed account for 30 s, so disabling an account takes effect within that.
- **Found in Phase 9:** the sign-up consent does not cover using patients' data to improve the assistant, so the feedback export reads only patients who gave a separate, optional `service_improvement` consent, and de-identifies what it writes for a person to review.
- **Decided in Phase 9:** one compose host per environment for v1, with promotion through staging on the same images and rollback by image tag; migrations are additive so an image rollback never meets a schema it cannot read.

## 7. Execution checklist

Tracked in [CHECKLIST.md](CHECKLIST.md). Each item is ticked in the same commit that completes it.

---

## 8. Verification

- **Unit tests:** `utils/` is framework-free per the existing rules, covering scheduling, safety gating, RAG filtering and parsers. Run with `uv run pytest`.
- **DB tests:** a Postgres test container covers the exclusion constraint (two concurrent holds on overlapping minutes → one fails) and RLS isolation.
- **Workflow tests:** `temporalio.testing.WorkflowEnvironment.start_time_skipping()` with fake interfaces covers hold expiry, reminders, escalation timeouts and consultation approval.
- **LLM evals:** a fixed AR/EN dataset for the intent, scope, sensitivity and output guards and for booking-time extraction, with pass-rate thresholds.
- **End to end:** `make up`, then through the web app:
  - Sign up as a patient, book with the slot picker, then book by voice in Arabic. Confirm the rows in the DB and the reminders in the Temporal UI.
  - Ask an in-scope question, an out-of-scope question and a sensitive one, and confirm the escalation appears in the doctor portal and the doctor's reply appears in the patient's chat.
  - Upload a PDF and ask the doctor chat about it.
  - Record a short session, then approve it and confirm it appears in the timeline.
