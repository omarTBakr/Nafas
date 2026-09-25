"""dialect-router: Arabic dialect identification over HTTP, on the GPU when there is one.

POST /v1/classify takes up to max_batch_size texts and returns one label per
text. The label set is whatever the model's config.json says (12 codes today:
ar, eg, en, iq, lb, ly, ma, ps, sa, sd, sy, tn), not the model card's list.

Its output is metadata — for analytics, reply tone and TTS voice choice. It is
never an input to a safety or clinical decision (docs/PLAN.md §1).
"""
