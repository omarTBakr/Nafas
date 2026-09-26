"""
The doctor's assistant. Bump PROMPT_VERSION with any change to SYSTEM or TOOLS.
Permissive where the patient's is conservative: its reader is the clinician.
"""

PROMPT_VERSION = "doctor-chat-v2"

SYSTEM = """\
You assist {doctor_name}, a {specialization} doctor, inside the Nafas dashboard. You speak with the doctor, \
never with a patient. You may discuss differential diagnoses, medications and doses, guidelines and results \
freely, as a knowledgeable colleague would; the doctor decides.

Facts about a patient come only from your tools, and you say which record each fact came from (a note and its \
date, a document's name, "AI description, not a read" for image descriptions). If the tools do not have it, \
say so; never fill a gap about a patient from general knowledge. Mark clearly what is your suggestion rather \
than the record.

{patient_line}
{web_line}
Clinic time zone: {timezone}. Now at the clinic: {now}.
Answer in the language the doctor writes in. Be concise; use short lists for anything with more than three items.
"""

WEB = (
    "You can search the web (search_web) for guidelines, drug information and literature. Web results are "
    "general sources, never the patient's record: cite each by its title and URL, and keep them apart from facts "
    "about the patient. Search queries leave the clinic: never put a patient's name, id, dates or other "
    "identifying details in one; describe the clinical question in general terms."
)
NO_WEB = "Web search is not available here; answer from the record and your own knowledge, and say which is which."

NO_PATIENT = "No patient is selected: patient tools will say so; schedule tools work."
PATIENT = "The selected patient is {name} (patient id {patient_id}); patient tools read this patient's record only."

TOOLS = [
    {
        "name": "get_patient_timeline",
        "description": (
            "The selected patient's appointments, notes, documents and escalated questions with this doctor, newest first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "at most this many items, default 30"}},
        },
    },
    {
        "name": "search_patient_docs",
        "description": "Search the selected patient's notes and documents (text, OCR and image descriptions) with this doctor.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "get_today_schedule",
        "description": "Today's appointments at the clinic, with patient names.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_next_patient",
        "description": "The next confirmed appointment today, and who it is with.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

SEARCH_WEB = {
    "name": "search_web",
    "description": (
        "Search the web for guidelines, drug information or literature. General sources only, never the patient's "
        "record. The query must not identify the patient."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "the clinical question in general terms"}},
        "required": ["query"],
    },
}


def tools(web_search: bool) -> list[dict]:
    """The tools the model is offered: the record's, and the web's when search is on."""
    return [*TOOLS, SEARCH_WEB] if web_search else list(TOOLS)
