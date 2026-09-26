"""The small pieces every service leans on: the tts client, the API-and-worker runner, the migration helpers, the factories."""

import asyncio
import json

import httpx
import pytest

from nafas_core.db import migration_ops
from nafas_core.exceptions.providers import TTSError
from nafas_core.interfaces.tts.http import HttpTTS
from nafas_core.temporal import TaskQueue, serve


async def test_the_tts_client_returns_audio_and_what_made_it():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/speak"
        assert json.loads(request.read()) == {"text": "موعدك الأربعاء", "dialect": "eg", "voice": "female"}
        return httpx.Response(
            200, content=b"RIFF", headers={"content-type": "audio/wav", "x-audio-seconds": "1.5", "x-model-id": "omnivoice"}
        )

    tts = HttpTTS("http://tts", httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://tts"))
    speech = await tts.speak("موعدك الأربعاء", "eg", "female")

    assert (speech.audio, speech.mime_type, speech.seconds, speech.model_id) == (b"RIFF", "audio/wav", 1.5, "omnivoice")


@pytest.mark.parametrize("answer", [httpx.Response(503), httpx.ConnectError("down")])
async def test_a_tts_failure_is_a_tts_error(answer):
    def handler(request):
        if isinstance(answer, Exception):
            raise answer
        return answer

    tts = HttpTTS("http://tts", httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://tts"))
    with pytest.raises(TTSError):
        await tts.speak("x", "eg", None)


async def test_the_worker_waits_for_temporal_while_the_api_already_answers(monkeypatch):
    attempts = []

    class Worker:
        async def run(self):
            await asyncio.sleep(3600)

    async def create_worker(queue, workflows, activities):
        attempts.append(queue)
        if len(attempts) < 3:
            raise RuntimeError("temporal is not up yet")
        return Worker()

    monkeypatch.setattr(serve, "create_worker", create_worker)
    monkeypatch.setattr(serve, "RECONNECT_SECONDS", 0)

    task = asyncio.create_task(serve._worker_forever(TaskQueue.SCHEDULING, [], []))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if len(attempts) == 3:
            break
    task.cancel()

    assert attempts == [TaskQueue.SCHEDULING] * 3


async def test_when_the_api_stops_the_worker_stops_with_it(monkeypatch):
    cancelled = asyncio.Event()

    class Server:
        def __init__(self, config):
            pass

        async def serve(self):
            return None  # the API ended at once

    async def worker_forever(queue, workflows, activities):
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(serve.uvicorn, "Server", Server)
    monkeypatch.setattr(serve, "_worker_forever", worker_forever)

    await asyncio.wait_for(
        serve.serve_with_worker(object(), port=0, task_queue=TaskQueue.SCHEDULING, workflows=[], activities=[]), 2
    )
    await asyncio.wait_for(cancelled.wait(), 1)


class Recorder:
    def __init__(self):
        self.sql: list[str] = []

    def execute(self, statement):
        self.sql.append(str(statement))


@pytest.fixture
def op(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(migration_ops, "op", recorder)
    return recorder


def test_a_service_schema_is_usable_by_its_own_role_alone(op):
    migration_ops.create_service_schema("clinical")

    assert migration_ops.service_role("clinical") == "nafas_clinical_access"
    assert any("CREATE ROLE nafas_clinical_access NOLOGIN" in s for s in op.sql)
    assert "GRANT USAGE ON SCHEMA clinical TO nafas_clinical_access" in op.sql
    assert any("GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO nafas_clinical_access" in s for s in op.sql)
    assert not any("nafas_app" in s for s in op.sql)


def test_isolation_policies_name_the_app_role_and_qualify_the_patient(op):
    migration_ops.enable_doctor_isolation("scheduling.appointments")
    migration_ops.enable_patient_isolation("identity.patient_channels")
    migration_ops.enable_patient_self_access("scheduling.appointments", commands=("SELECT", "UPDATE"))

    joined = "\n".join(op.sql)
    assert "ALTER TABLE scheduling.appointments ENABLE ROW LEVEL SECURITY" in joined
    assert "USING (doctor_id = nafas_current_doctor()) WITH CHECK (doctor_id = nafas_current_doctor())" in joined
    # the regression the sweep found: the patient column must be the policy's table's, not doctor_patients'
    assert "dp.patient_id = patient_channels.patient_id" in joined and "dp.patient_id = patient_id " not in joined
    assert "FOR INSERT TO nafas_app WITH CHECK (true)" in joined
    own_update = "patient_own_update ON scheduling.appointments FOR UPDATE TO nafas_app"
    assert f"{own_update} USING (patient_id = nafas_current_patient()) WITH CHECK" in joined


def test_the_factories_choose_by_setting(monkeypatch):
    import nafas_core.config
    from nafas_core.interfaces.dialect import factory as dialect
    from nafas_core.interfaces.email import factory as email
    from nafas_core.interfaces.tts import factory as tts

    for module, setter in ((dialect, "set_dialect_classifier"), (tts, "set_tts"), (email, "set_email_sender")):
        if hasattr(module, setter):
            getattr(module, setter)(None)
    monkeypatch.setenv("SMTP_HOST", "")
    nafas_core.config._settings_instance = None

    from nafas_core.interfaces.email.smtp import DisabledSender

    assert isinstance(email.get_email_sender(), DisabledSender)
    assert tts.get_tts() is not None and dialect.get_dialect_classifier() is not None
