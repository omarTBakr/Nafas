"""stt: Arabic-dialect speech-to-text over HTTP, on the GPU when there is one.

POST /v1/transcribe takes one recording (a browser voice note: webm/opus,
ogg, mp3, wav — anything ffmpeg reads) and returns its text. One model covers
13 dialects with no switch; the patient's chosen dialect is for the reply
voice, not for this. Audio and transcripts are patient data and never logged.
"""
