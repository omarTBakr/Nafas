"""
The doctor assistant's tools: read-only, bound to one doctor and at most one
patient, chosen by the dashboard, never by the model. Each reads through the
owning service, which audits it.
"""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from nafas_core.clients.timeline import timeline_items
from nafas_core.exceptions.providers import SearchError

TIMELINE_LIMIT = 30
WEB_RESULTS = 5
LATE_GRACE = timedelta(minutes=20)


class DoctorTools:
    def __init__(
        self,
        *,
        doctor_id: uuid.UUID,
        patient_id: uuid.UUID | None,
        timezone: str,
        identity,
        scheduling,
        clinical,
        conversation,
        web=None,
    ):
        self.doctor_id, self.patient_id = doctor_id, patient_id
        self._web = web
        self._zone = ZoneInfo(timezone)
        self._identity, self._scheduling, self._clinical, self._conversation = identity, scheduling, clinical, conversation

    def _local(self, when: str) -> str:
        return datetime.fromisoformat(when).astimezone(self._zone).strftime("%a %d %b %Y %H:%M")

    def _need_patient(self) -> dict | None:
        return None if self.patient_id else {"error": "no patient is selected; open a patient's page to ask about them"}

    async def get_patient_timeline(self, limit: int = TIMELINE_LIMIT) -> dict | list:
        if missing := self._need_patient():
            return missing
        items = await timeline_items(
            self.doctor_id, self.patient_id, scheduling=self._scheduling, clinical=self._clinical, conversation=self._conversation
        )
        out = []
        for item in items[: max(1, min(limit, 100))]:
            entry = {"type": item["type"], "when": self._local(item["at"])}
            match item["type"]:
                case "appointment":
                    entry |= {"status": item["status"], "reason_for_visit": item.get("reason_for_visit")}
                case "history":
                    entry |= {
                        "kind": item["kind"],
                        "content": item["content"],
                        "shared_with_patient": item["visibility"] == "patient_visible",
                    }
                case "document":
                    entry |= {"filename": item["filename"], "kind": item["kind"], "status": item["status"]}
                    if item.get("ai_description"):
                        entry["ai_description"] = f"[{item['ai_label']}] {item['ai_description']}"
                case "escalation":
                    entry |= {"question": item["question"], "status": item["status"], "reply": item.get("doctor_reply")}
            out.append(entry)
        return out

    async def search_patient_docs(self, query: str) -> dict | list:
        if missing := self._need_patient():
            return missing
        hits = await self._clinical.search(self.patient_id, self.doctor_id, query, audience="doctor", k=6)
        return [
            {"source": h["details"].get("filename") or h["details"].get("kind") or h["source_type"], "text": h["content"]}
            for h in hits
        ]

    async def _today(self) -> list[dict]:
        now = datetime.now(UTC)
        start = datetime.combine(now.astimezone(self._zone).date(), datetime.min.time(), tzinfo=self._zone)
        return await self._scheduling.doctor_appointments(self.doctor_id, start, start + timedelta(days=1))

    async def get_today_schedule(self) -> list[dict]:
        today = await self._today()
        names = await self._identity.patient_names(self.doctor_id, list({uuid.UUID(a["patient_id"]) for a in today}))
        return [
            {
                "time": self._local(a["start"]),
                "status": a["status"],
                "patient": names.get(a["patient_id"], "held, not yet confirmed"),
            }
            for a in today
        ]

    async def get_next_patient(self) -> dict:
        now = datetime.now(UTC)
        upcoming = [
            a
            for a in await self._today()
            if a["status"] == "confirmed" and datetime.fromisoformat(a["start"]) >= now - LATE_GRACE
        ]
        if not upcoming:
            return {"next": None}
        visit = min(upcoming, key=lambda a: datetime.fromisoformat(a["start"]))
        names = await self._identity.patient_names(self.doctor_id, [uuid.UUID(visit["patient_id"])])
        return {
            "next": {
                "time": self._local(visit["start"]),
                "patient": names.get(visit["patient_id"]),
                "patient_id": visit["patient_id"],
            }
        }

    async def search_web(self, query: str) -> dict | list:
        """General sources for the doctor: guidelines, drug information, literature. Never the record."""
        if self._web is None:
            return {"error": "web search is not available here"}
        try:
            found = await self._web.search(query, max_results=WEB_RESULTS)
        except SearchError:
            return {"error": "web search failed just now; answer without it and say so"}
        return [{"title": r.title, "url": r.url, "text": r.content} for r in found]

    async def run(self, name: str, arguments: dict):
        match name:
            case "get_patient_timeline":
                return await self.get_patient_timeline(int(arguments.get("limit") or TIMELINE_LIMIT))
            case "search_patient_docs":
                return await self.search_patient_docs(str(arguments.get("query", "")))
            case "get_today_schedule":
                return await self.get_today_schedule()
            case "get_next_patient":
                return await self.get_next_patient()
            case "search_web":
                return await self.search_web(str(arguments.get("query", "")))
        return {"error": f"no tool named {name}"}
