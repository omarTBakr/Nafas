"""Real object storage: the bucket script, S3Storage itself, and a backup of every object and its restore."""

import httpx

from nafas_core.config import get_setting
from nafas_core.exceptions.providers import StorageError
from nafas_core.interfaces.storage.s3 import S3Storage
from scripts import backup_storage, init_storage


def storage() -> S3Storage:
    s = get_setting()
    return S3Storage(
        bucket=s.s3_bucket,
        endpoint_url=s.s3_endpoint_url,
        region=s.s3_region,
        access_key=s.s3_access_key.get_secret_value(),
        secret_key=s.s3_secret_key.get_secret_value(),
    )


async def test_objects_round_trip_through_s3_and_presigned_links_work(s3_prefix):
    await init_storage.main()
    await init_storage.main()  # a second run is harmless
    store = storage()
    key = f"{s3_prefix}doctor/d1/patient/p1/documents/echo.pdf"

    await store.put(key, b"%PDF-1.4 echo", "application/pdf")
    assert await store.get(key) == b"%PDF-1.4 echo"
    fetched = httpx.get(await store.presigned_get_url(key, 60), timeout=10)
    assert fetched.status_code == 200 and fetched.content == b"%PDF-1.4 echo"
    put = httpx.put(
        await store.presigned_put_url("doctor/d1/upload.png", "image/png", 60),
        content=b"png",
        headers={"Content-Type": "image/png"},
    )
    assert put.status_code == 200 and await store.get("doctor/d1/upload.png") == b"png"

    await store.delete(key)
    try:
        await store.get(key)
        raise AssertionError("a deleted object came back")
    except StorageError:
        pass


async def test_a_backup_holds_every_object_and_restores_it_where_it_was(s3_prefix, tmp_path):
    await init_storage.main()
    store = storage()
    objects = {
        f"{s3_prefix}doctor/d1/patient/p1/documents/a.pdf": b"a",
        f"{s3_prefix}doctor/d1/patient/p1/consultations/c1/part-0000.webm": b"voice",
        f"{s3_prefix}doctor/d2/patient/p2/voice/m1.ogg": b"note",
    }
    for key, data in objects.items():
        await store.put(key, data, "application/octet-stream")

    assert await backup_storage.save(tmp_path, prefix=s3_prefix) == 3
    assert (tmp_path / s3_prefix / "doctor/d1/patient/p1/documents/a.pdf").read_bytes() == b"a"

    for key in objects:
        await store.delete(key)
    assert await backup_storage.restore(tmp_path) == 3
    for key, data in objects.items():
        assert await store.get(key) == data
