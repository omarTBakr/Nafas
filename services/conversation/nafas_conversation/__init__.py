"""conversation: the patient's assistant chat.

Owns the `conversation` schema (conversations, messages). A
PatientConversationWorkflow per patient and doctor takes each message in
order — transcribing a voice note first — decides what it is for, and
answers: booking through the scheduling service's API (phase 3), medical
questions behind the safety gates (phase 4). See docs/PLAN.md §3.
"""
