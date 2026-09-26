"""tts: Arabic-dialect speech from text over HTTP, on the GPU when there is one.

POST /v1/speak takes text our own code has already normalised (numbers,
dates and times as words, no Latin script) and the patient's dialect and
voice, and returns a WAV. It speaks booking and admin messages only; that
rule is enforced by the caller, which never sends clinical text. Text is
patient data and is never logged.
"""
