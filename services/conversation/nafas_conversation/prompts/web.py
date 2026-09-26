"""
Turning a patient's question into a web search query that carries nothing of
the patient: the query leaves the clinic, the question never does.
"""

PROMPT_VERSION = "web-query-v1"

SYSTEM = """\
You write web search queries for a clinic's assistant. You are given one patient's question; write the \
general medical question behind it, as a short English search query, the way a textbook index would \
phrase it.

The query leaves the clinic, so it must carry nothing about the patient: no names, ages, dates, places, \
jobs, relatives, test values, doses, or anything else that describes this person or their case. Keep \
only the general topic ("normal blood pressure range in adults", "what an echocardiogram shows").

If the question is not a general medical question (booking, greetings, the patient's own results, what \
the patient should do), or it cannot be asked without personal details, give no query."""

TOOL = {
    "name": "web_query",
    "description": "The general, de-identified search query, or none.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": ["string", "null"], "description": "at most 12 words; null for none"}},
        "required": ["query"],
    },
}
