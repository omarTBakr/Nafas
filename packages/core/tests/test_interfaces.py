import math
from uuid import uuid4

import pytest

from nafas_core.config import Settings
from nafas_core.enums.channel import Channel
from nafas_core.exceptions.config import MissingSettingError
from nafas_core.exceptions.providers import StorageError
from nafas_core.interfaces.channels.factory import get_channel, set_channel
from nafas_core.interfaces.channels.fake import FakeChannel
from nafas_core.interfaces.embeddings.base import EMBEDDING_DIMENSIONS
from nafas_core.interfaces.embeddings.factory import get_embeddings
from nafas_core.interfaces.embeddings.fake import FakeEmbeddings
from nafas_core.interfaces.storage.base import patient_key
from nafas_core.interfaces.storage.fake import InMemoryStorage
from nafas_core.interfaces.storage.s3 import S3Storage
from nafas_core.interfaces.stt.factory import get_stt
from nafas_core.interfaces.stt.fake import FakeSTT


async def test_fake_embeddings_are_deterministic_unit_vectors():
    first, again, other = await FakeEmbeddings().embed(["ألم في الصدر", "ألم في الصدر", "headache"])

    assert len(first) == EMBEDDING_DIMENSIONS
    assert first == again
    assert math.isclose(sum(x * x for x in first), 1.0)
    assert abs(sum(a * b for a, b in zip(first, other, strict=True))) < 0.2


async def test_fake_stt_records_the_request():
    stt = FakeSTT("عايز أحجز بكرة")

    transcript = await stt.transcribe(b"ogg", "audio/ogg", language_hint="ar")

    assert transcript.text == "عايز أحجز بكرة"
    assert stt.calls[0]["language_hint"] == "ar"


def test_unconfigured_providers_fail_by_name(monkeypatch):
    """A call to a backend nobody chose must say so, not fail obscurely."""
    monkeypatch.setenv("STT_PROVIDER", "")
    with pytest.raises(MissingSettingError, match="STT_PROVIDER"):
        get_stt()
    with pytest.raises(MissingSettingError, match="EMBEDDINGS_PROVIDER"):
        get_embeddings()
    with pytest.raises(MissingSettingError, match="whatsapp"):
        get_channel(Channel.WHATSAPP)


async def test_a_registered_channel_is_served_and_can_reply():
    fake = FakeChannel(Channel.TELEGRAM)
    set_channel(Channel.TELEGRAM, fake)
    try:
        channel = get_channel(Channel.TELEGRAM)
        inbound = channel.parse_inbound({"external_id": "42", "message_id": "1", "text": "hello"})
        await channel.send_text(inbound.external_id, "hi")
    finally:
        set_channel(Channel.TELEGRAM, None)

    assert inbound.channel is Channel.TELEGRAM
    assert fake.sent == [("42", "hi")]


def test_patient_keys_group_by_doctor_then_patient():
    doctor, patient = uuid4(), uuid4()

    assert patient_key(doctor, patient, "voice", "1.ogg") == f"doctor/{doctor}/patient/{patient}/voice/1.ogg"


async def test_in_memory_storage_round_trip():
    storage = InMemoryStorage()

    await storage.put("a/b", b"data", "text/plain")
    assert await storage.get("a/b") == b"data"

    await storage.delete("a/b")
    with pytest.raises(StorageError):
        await storage.get("a/b")


@pytest.fixture
async def s3_storage():
    """The S3 store from docker-compose, or a skip when it is not running."""
    settings = Settings(_env_file=None)
    storage = S3Storage(
        bucket="nafas-test",
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        access_key=settings.s3_access_key.get_secret_value(),
        secret_key=settings.s3_secret_key.get_secret_value(),
    )
    try:
        await storage.ensure_bucket()
    except Exception as exc:  # any failure here means "no S3 to test against"
        pytest.skip(f"no S3 at {settings.s3_endpoint_url}: {exc}")

    return storage


async def test_s3_round_trip(s3_storage):
    key = f"test/{uuid4()}.txt"

    await s3_storage.put(key, "تقرير".encode(), "text/plain; charset=utf-8")
    assert (await s3_storage.get(key)).decode() == "تقرير"
    assert key in await s3_storage.presigned_get_url(key)

    await s3_storage.delete(key)
    with pytest.raises(StorageError):
        await s3_storage.get(key)
