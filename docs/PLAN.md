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
                ┌──────▼──────── Temporal ──────────────┐
                │ workflows: conversation, booking,     │
                │ escalation, session, document ingest  │
                └──────┬────────────────────────────────┘
                       │ activities (thin) → utils (logic) → interfaces (ports)
   ┌──────────┬────────┼─────────┬──────────┬──────────┬───────────┐
 Postgres   MinIO/S3  Claude     STT       Embeddings  Channel     LiveKit
 +pgvector  (files)   (LLM)    (Whisper-   (bge-m3,    senders     (phase 9)
                               class)      multiling.) (TG/email)
```

**Stack choices**
- **DB:** Postgres 16 with `pgvector`, accessed through SQLAlchemy 2 (async, asyncpg). Migrations use Alembic.
- **Files:** MinIO locally and S3-compatible storage in production. Objects are keyed by `doctor/{id}/patient/{id}/...` and served through presigned URLs.
- **LLM (`interfaces/llm`):** Claude.
  - `claude-sonnet-5` for patient and doctor chat.
  - `claude-haiku-4-5` for the cheap classifiers (intent, scope, sensitivity, output guard).
  - `claude-opus-5-5` for session summaries.
  - Claude vision gives descriptive text for images that are uploaded to the doctor side. It is never a diagnosis.
- **STT (`interfaces/stt`):** a Protocol with two implementations.
  - Hosted Whisper-large-v3-class, used for voice notes.
  - A diarizing provider for sessions (doctor vs patient speakers).
  - Pick the vendors in a Phase 0 spike that tests Egyptian, Gulf and Levantine Arabic plus code-switching.
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
| `doctors` | id, user_id → users, full_name_en/ar, specialization_id → specializations, timezone, default_slot_minutes, buffer_minutes, languages text[], booking_horizon_days, min_notice_minutes, telegram_bot_username (optional per-doctor bot) |
| `patients` | id, full_name, date_of_birth, sex, phone, email, preferred_language enum(ar, en), created_at |
| `patient_channels` | id, patient_id, channel enum(telegram, email, whatsapp), external_id, verified_at. Unique on (channel, external_id) |
| `doctor_patients` | doctor_id, patient_id, status enum(active, archived), first_seen_at. **This is the access-control boundary for every clinical query** |
| `consents` | id, patient_id, doctor_id, kind enum(data_processing, session_recording, ai_chat), granted_at, revoked_at, channel, evidence (message id) |

**Scheduling**
| Table | Key columns |
|---|---|
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

   `utils/scheduling.py` handles relative Arabic and English times ("بكرة بعد العصر", "next Tuesday 5:40") in the doctor's timezone. It is pure code and unit-tested. Holds are inserted as `held` rows, so the exclusion constraint settles any race. **`BookingWorkflow`** takes over from there:
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

## 4. Code layout (follows the existing layer rules)

- `utils/db/`: engine, session and RLS helper, plus ORM models per table group (`models/identity.py`, `scheduling.py`, `clinical.py`, `chat.py`). `alembic/` sits at the repository root.
- `utils/scheduling.py`: slot generation, the timezone and natural-time parser, and hold/confirm logic.
- `utils/safety.py`: the emergency keywords and the gate orchestration, as pure functions over the classifier results.
- `utils/rag.py`: chunking, hybrid retrieval and visibility filtering.
- `utils/booking_agent.py`, `utils/patient_chat.py` and `utils/doctor_chat.py`: the LLM tool loops.
- `interfaces/{llm,stt,embeddings,storage,channels}/`: a Protocol plus implementations and a factory in each.
- `prompts/`: `intent.py`, `scope.py`, `sensitivity.py`, `output_guard.py`, `booking.py`, `patient_chat.py`, `doctor_chat.py`, `consultation_summary.py`, `document_describe.py`.
- `enums/`: every enum listed above.
- `exceptions/`: new subtrees `scheduling.py` (SlotUnavailable, OutsideAvailability, HoldExpired), `channels.py`, `safety.py` and `auth.py`.
- `schemas/`, `activities/` and `workflows/`: one file per step and per flow, registered in `ACTIVITIES` and `WORKFLOWS`.
- `routes/`: `telegram.py`, `email.py`, `auth.py`, `doctor_schedule.py`, `doctor_patients.py`, `doctor_chat.py`, `documents.py`, `consultations.py` and `escalations.py`. Auth is attached where the routers are included in `main.py`.
- `utils/config.py`: new settings for DB, S3, Anthropic, STT, embeddings, Telegram, email and JWT.
- `docker-compose.yml`: postgres+pgvector, temporal plus UI, minio, api, worker and web.
- `web/`: the dashboard.

---

## 5. Low-hanging fruit (cheap once the core exists; the user picks which ship in v1)

- **Reminders:** 24h and 1h before, plus "reply 1 to confirm / 2 to cancel". This is already inside `BookingWorkflow`.
- **Cancel or reschedule by chat**, plus a **waitlist** that offers a freed-up slot to the next patient.
- **Pre-visit intake:** the bot asks for the reason for the visit, symptoms, meds and allergies, and saves an `intake` history entry for the doctor.
- **Next-patient brief:** generated automatically 10 minutes before each appointment and pushed to the dashboard.
- **Post-visit patient summary and instructions** in the patient's language, sent after the doctor approves.
- **Voice replies (TTS)** for patients who send voice notes.
- **`.ics` invites** by email, and Google Calendar export for the doctor.
- **No-show tracking** and a simple per-doctor stats page.

---

## 6. Compliance and safety baseline (not optional)

- Explicit consent at onboarding covers data processing and AI chat. Recording needs a separate consent every time.
- Every assistant message is labelled as from an AI assistant and not a doctor.
- Encryption: TLS in transit, and encrypted disk and bucket at rest.
- PHI stays out of logs; the logger redacts it.
- `audit_log` records every clinical read.
- The design targets the Egypt PDPL (Law 151/2020) and HIPAA-style controls. A zero-data-retention agreement with the LLM and STT vendors is needed before any real patients use the system.

---

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
