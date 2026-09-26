# Database schema

Generated from a migrated database by `scripts/schema_doc.py`; do not edit by hand.
Run `uv run python -m scripts.schema_doc` after a migration.

One Postgres database, one schema per service. A service logs in with a role that holds
its own schema and nothing else (`deploy/postgres/roles.sql`); row-level security then
narrows every row to the doctor or patient the request is for (`nafas_core.db.session_scope`).

## `identity`

The identity service: accounts, doctors, patients, care links, consents.

```mermaid
erDiagram
    consents {
        uuid id PK
        uuid patient_id FK
        uuid doctor_id FK
        consent_kind kind
        timestamptz granted_at
        timestamptz revoked_at
        channel channel
        text evidence
    }
    doctor_patients {
        uuid doctor_id PK,FK
        uuid patient_id PK,FK
        care_status status
        timestamptz first_seen_at
    }
    doctors {
        uuid id PK
        uuid user_id FK
        text full_name_en
        text full_name_ar
        uuid specialization_id FK
        ARRAY languages
        timestamptz created_at
    }
    patient_channels {
        uuid id PK
        uuid patient_id FK
        channel channel
        text external_id
        timestamptz verified_at
    }
    patients {
        uuid id PK
        text full_name
        date date_of_birth
        sex sex
        varchar phone
        varchar email
        language preferred_language
        timestamptz created_at
        uuid user_id FK
        spoken_dialect dialect
        voice_gender voice
        boolean email_notices
    }
    specializations {
        uuid id PK
        varchar code
        text name_en
        text name_ar
        text scope_description
        jsonb in_scope_topics
        jsonb always_escalate
    }
    users {
        uuid id PK
        varchar email
        text password_hash
        user_role role
        boolean is_active
        timestamptz created_at
        timestamptz last_login_at
    }
    doctors ||--o{ consents : "doctor_id"
    patients ||--o{ consents : "patient_id"
    doctors ||--o{ doctor_patients : "doctor_id"
    patients ||--o{ doctor_patients : "patient_id"
    specializations ||--o{ doctors : "specialization_id"
    users ||--o{ doctors : "user_id"
    patients ||--o{ patient_channels : "patient_id"
    users ||--o{ patients : "user_id"
```

| Table | Row-level security |
| --- | --- |
| `consents` | `doctor_isolation` (all): `(doctor_id = nafas_current_doctor())`<br>`patient_own_insert` (insert): `(patient_id = nafas_current_patient())`<br>`patient_own_select` (select): `(patient_id = nafas_current_patient())`<br>`patient_own_update` (update): `(patient_id = nafas_current_patient())` |
| `doctor_patients` | `doctor_isolation` (all): `(doctor_id = nafas_current_doctor())`<br>`patient_own_select` (select): `(patient_id = nafas_current_patient())` |
| `doctors` | off (see the isolation sweep for why this table may be open) |
| `patient_channels` | `anyone_inserts` (insert): `true`<br>`linked_doctor_deletes` (delete): `(EXISTS ( SELECT 1 FROM identity.doctor_patients dp WHERE ((dp.patient_id = patient_channels.patient_id) AND (dp.doctor_id = nafas_current_doctor()))))`<br>`linked_doctor_reads` (select): `(EXISTS ( SELECT 1 FROM identity.doctor_patients dp WHERE ((dp.patient_id = patient_channels.patient_id) AND (dp.doctor_id = nafas_current_doctor()))))`<br>`linked_doctor_updates` (update): `(EXISTS ( SELECT 1 FROM identity.doctor_patients dp WHERE ((dp.patient_id = patient_channels.patient_id) AND (dp.doctor_id = nafas_current_doctor()))))` |
| `patients` | `anyone_inserts` (insert): `true`<br>`linked_doctor_deletes` (delete): `(EXISTS ( SELECT 1 FROM identity.doctor_patients dp WHERE ((dp.patient_id = patients.id) AND (dp.doctor_id = nafas_current_doctor()))))`<br>`linked_doctor_reads` (select): `(EXISTS ( SELECT 1 FROM identity.doctor_patients dp WHERE ((dp.patient_id = patients.id) AND (dp.doctor_id = nafas_current_doctor()))))`<br>`linked_doctor_updates` (update): `(EXISTS ( SELECT 1 FROM identity.doctor_patients dp WHERE ((dp.patient_id = patients.id) AND (dp.doctor_id = nafas_current_doctor()))))`<br>`patient_own_select` (select): `(id = nafas_current_patient())`<br>`patient_own_update` (update): `(id = nafas_current_patient())` |
| `specializations` | off (see the isolation sweep for why this table may be open) |
| `users` | off (see the isolation sweep for why this table may be open) |

## `scheduling`

The scheduling service: hours, time off, appointments, notices.

```mermaid
erDiagram
    appointments {
        uuid id PK
        uuid doctor_id FK
        uuid patient_id FK
        timestamptz starts_at
        timestamptz ends_at
        appointment_status status
        appointment_mode mode
        timestamptz hold_expires_at
        text meeting_url
        text reason_for_visit
        text booking_workflow_id
        timestamptz created_at
        timestamptz updated_at
    }
    availability_rules {
        uuid id PK
        uuid doctor_id FK
        smallint weekday
        time_without_time_zone start_local
        time_without_time_zone end_local
        availability_mode mode
        integer slot_minutes
        date effective_from
        date effective_to
    }
    booking_settings {
        uuid doctor_id PK,FK
        varchar timezone
        integer slot_minutes
        integer buffer_minutes
        integer min_notice_minutes
        integer horizon_days
        integer hold_minutes
    }
    notifications {
        uuid id PK
        uuid doctor_id FK
        uuid patient_id FK
        uuid appointment_id FK
        notification_kind kind
        integer minutes_before
        jsonb details
        timestamptz read_at
        timestamptz created_at
    }
    time_off {
        uuid id PK
        uuid doctor_id FK
        timestamptz starts_at
        timestamptz ends_at
        text reason
    }
    appointments ||--o{ notifications : "appointment_id"
```

References into other schemas (in the database only, never on the ORM models):

- `appointments.doctor_id` → `identity.doctors`
- `appointments.patient_id` → `identity.patients`
- `availability_rules.doctor_id` → `identity.doctors`
- `booking_settings.doctor_id` → `identity.doctors`
- `notifications.doctor_id` → `identity.doctors`
- `notifications.patient_id` → `identity.patients`
- `time_off.doctor_id` → `identity.doctors`

| Table | Row-level security |
| --- | --- |
| `appointments` | `doctor_isolation` (all): `(doctor_id = nafas_current_doctor())`<br>`patient_own_select` (select): `(patient_id = nafas_current_patient())` |
| `availability_rules` | `doctor_isolation` (all): `(doctor_id = nafas_current_doctor())` |
| `booking_settings` | `doctor_isolation` (all): `(doctor_id = nafas_current_doctor())` |
| `notifications` | `doctor_isolation` (all): `(doctor_id = nafas_current_doctor())`<br>`patient_own_select` (select): `(patient_id = nafas_current_patient())`<br>`patient_own_update` (update): `(patient_id = nafas_current_patient())` |
| `time_off` | `doctor_isolation` (all): `(doctor_id = nafas_current_doctor())` |

## `conversation`

The conversation service: the patient's chat, escalations, reply ratings.

```mermaid
erDiagram
    conversations {
        uuid id PK
        uuid patient_id FK
        uuid doctor_id FK
        timestamptz created_at
    }
    escalations {
        uuid id PK
        uuid conversation_id FK
        uuid doctor_id FK
        uuid patient_id FK
        uuid message_id FK
        escalation_reason reason
        escalation_status status
        text doctor_reply
        uuid reply_message_id
        varchar workflow_id
        timestamptz nudged_at
        timestamptz answered_at
        timestamptz created_at
    }
    messages {
        uuid id PK
        uuid conversation_id FK
        message_role role
        modality modality
        text content
        text audio_key
        intent intent
        varchar model
        varchar prompt_version
        integer tokens_in
        integer tokens_out
        varchar detected_dialect
        timestamptz created_at
        jsonb safety
    }
    reply_feedback {
        uuid id PK
        uuid message_id FK
        uuid patient_id FK
        uuid doctor_id FK
        varchar rating
        timestamptz created_at
    }
    conversations ||--o{ escalations : "conversation_id"
    messages ||--o{ escalations : "message_id"
    conversations ||--o{ messages : "conversation_id"
    messages ||--o{ reply_feedback : "message_id"
```

References into other schemas (in the database only, never on the ORM models):

- `conversations.doctor_id` → `identity.doctors`
- `conversations.patient_id` → `identity.patients`
- `escalations.doctor_id` → `identity.doctors`
- `escalations.patient_id` → `identity.patients`
- `reply_feedback.doctor_id` → `identity.doctors`
- `reply_feedback.patient_id` → `identity.patients`

| Table | Row-level security |
| --- | --- |
| `conversations` | `party_access` (all): `((patient_id = nafas_current_patient()) OR (doctor_id = nafas_current_doctor()))` |
| `escalations` | `party_access` (all): `((patient_id = nafas_current_patient()) OR (doctor_id = nafas_current_doctor()))` |
| `messages` | `party_access` (all): `(EXISTS ( SELECT 1 FROM conversation.conversations c WHERE ((c.id = messages.conversation_id) AND ((c.patient_id = nafas_current_patient()) OR (c.doctor_id = nafas_current_doctor())))))` |
| `reply_feedback` | `party_access` (all): `((patient_id = nafas_current_patient()) OR (doctor_id = nafas_current_doctor()))` |

## `clinical`

The clinical-records service: history, documents and their searchable passages.

```mermaid
erDiagram
    chunks {
        uuid id PK
        uuid patient_id FK
        uuid doctor_id FK
        source_type source_type
        uuid source_id
        integer position
        text content
        vector embedding
        tsvector tsv
        visibility visibility
        jsonb metadata
        timestamptz created_at
    }
    documents {
        uuid id PK
        uuid patient_id FK
        uuid doctor_id FK
        document_kind kind
        varchar filename
        text object_key
        varchar mime
        bigint size_bytes
        varchar sha256
        integer page_count
        text extracted_text
        text ai_description
        document_status status
        text error
        visibility visibility
        uuid uploaded_by
        timestamptz created_at
    }
    history_entries {
        uuid id PK
        uuid patient_id FK
        uuid doctor_id FK
        history_kind kind
        text content
        jsonb structured
        varchar source_type
        uuid source_id
        visibility visibility
        timestamptz occurred_at
        uuid created_by
        timestamptz created_at
    }
```

References into other schemas (in the database only, never on the ORM models):

- `chunks.doctor_id` → `identity.doctors`
- `chunks.patient_id` → `identity.patients`
- `documents.doctor_id` → `identity.doctors`
- `documents.patient_id` → `identity.patients`
- `history_entries.doctor_id` → `identity.doctors`
- `history_entries.patient_id` → `identity.patients`

| Table | Row-level security |
| --- | --- |
| `chunks` | `doctor_isolation` (all): `(doctor_id = nafas_current_doctor())`<br>`patient_visible_reads` (select): `((patient_id = nafas_current_patient()) AND (visibility = 'patient_visible'::clinical.visibility))` |
| `documents` | `doctor_isolation` (all): `(doctor_id = nafas_current_doctor())`<br>`patient_visible_reads` (select): `((patient_id = nafas_current_patient()) AND (visibility = 'patient_visible'::clinical.visibility))` |
| `history_entries` | `doctor_isolation` (all): `(doctor_id = nafas_current_doctor())`<br>`patient_visible_reads` (select): `((patient_id = nafas_current_patient()) AND (visibility = 'patient_visible'::clinical.visibility))` |

## `consultation`

The consultation service: recorded visits.

```mermaid
erDiagram
    consultations {
        uuid id PK
        uuid doctor_id FK
        uuid patient_id FK
        uuid appointment_id
        uuid consent_id FK
        consultation_status status
        jsonb parts
        jsonb transcript
        jsonb draft
        jsonb approved
        boolean share_with_patient
        varchar model
        varchar prompt_version
        text error
        timestamptz started_at
        timestamptz approved_at
        timestamptz created_at
        varchar source
        varchar room
        timestamptz recording_stopped_at
    }
```

References into other schemas (in the database only, never on the ORM models):

- `consultations.consent_id` → `identity.consents`
- `consultations.doctor_id` → `identity.doctors`
- `consultations.patient_id` → `identity.patients`

| Table | Row-level security |
| --- | --- |
| `consultations` | `doctor_isolation` (all): `(doctor_id = nafas_current_doctor())` |

## `edge`

The gateway: rate limits shared by its replicas.

```mermaid
erDiagram
    rate_hits {
        bigint id PK
        varchar limit_name
        varchar key_hash
        timestamptz hit_at
    }
```

| Table | Row-level security |
| --- | --- |
| `rate_hits` | off (see the isolation sweep for why this table may be open) |

## `audit`

The every service appends; no service reads.

```mermaid
erDiagram
    audit_log {
        bigint id PK
        timestamptz at
        text service
        text actor_type
        uuid actor_id
        text action
        text resource_type
        text resource_id
        uuid patient_id
        uuid doctor_id
        jsonb detail
    }
```

| Table | Row-level security |
| --- | --- |
| `audit_log` | off (see the isolation sweep for why this table may be open) |
