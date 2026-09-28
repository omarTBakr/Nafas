# Local Test Data

These fixtures are synthetic and contain no patient information. They cover
Arabic dialect routing, English fallback checks, clinical retrieval, and local
LLM smoke tests. Do not place real medical records or API credentials here.

## Seed Demo Accounts

After `make migrate`, `make seed`, and `make storage`, populate the local
database with reusable doctors, patients, care links, AI-chat consents, and
weekly schedules:

```bash
uv run python test_data/seed_demo_data.py
```

The script is safe to run repeatedly. It creates eight doctors across different
specializations and sixteen synthetic patients, including patients shared
across multiple doctors. All demo accounts use the password
`NafasDemo!2026`; emails and generated IDs are written to
`test_data/demo_manifest.json`.

## Seed A Patient's Visits

With the stack up (the script reaches Postgres, S3 and the embeddings service
from the host), give one demo patient a history of visits with one doctor:

```bash
uv run python test_data/seed_visits.py
```

Dr Salma Hassan (cardiology) and Mariam Ali get five visits: a recorded,
approved first visit with an ECG and a note filed under it; an online
follow-up with a Holter summary, a lipid panel and two notes; a cancelled
visit; a no-show; and one confirmed for next week. One note in her file belongs
to no visit. Some items are shared with Mariam, so both sides can be checked:
log in as the doctor and open My patients → مريم علي → Visits, or as Mariam and
open My records. Safe to run repeatedly; it seeds the demo accounts first.

The accounts use the reserved `.test` domain and must never be replaced with
real patient data.

- `dialect_samples.csv`: labelled text for dialect-router evaluation.
- `patient.json`: synthetic profile for integration setup.
- `clinical_note.txt`: synthetic bilingual note for OCR and embeddings tests.
- `seed_demo_data.py`: idempotent database seeder for doctors and patients.
- `seed_visits.py`: idempotent use case of one patient's visits, recordings, notes and documents.
- `demo_manifest.json`: generated demo credentials and IDs.
