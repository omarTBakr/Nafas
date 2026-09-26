"""doctor-assistant: a doctor's chat about their own patients (docs/PLAN.md §3.4).

Request and response, streamed over SSE, with no workflow: a doctor is at
the screen waiting. Less restricted than the patient's assistant, because
its reader is the doctor, but every tool is read-only, bound to that
doctor, and audited by the service it reads. Owns no schema.
"""
