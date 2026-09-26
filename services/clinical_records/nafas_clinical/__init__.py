"""clinical-records: a patient's record with one doctor, and the search over it.

Owns the `clinical` schema: history entries (notes, visit summaries,
medications, allergies), documents (reports, scans, images) and the chunks
both are searched through. A DocumentIngestionWorkflow reads each upload
(PDF text, OCR for scanned pages, an AI description for images), chunks
and embeds it. Every row belongs to one doctor and one patient; a patient
sees only what their doctor marked patient-visible. See docs/PLAN.md §2-3.
"""
