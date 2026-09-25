from exceptions.providers import StorageError


class InMemoryStorage:
    """A dict standing in for a bucket; `objects` maps key to (data, content_type)."""

    def __init__(self):
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def get(self, key: str) -> bytes:
        if key not in self.objects:
            raise StorageError(f"no object at {key}")

        return self.objects[key][0]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def presigned_get_url(self, key: str, expires_seconds: int = 300) -> str:
        return f"memory://get/{key}?expires={expires_seconds}"

    async def presigned_put_url(self, key: str, content_type: str, expires_seconds: int = 300) -> str:
        return f"memory://put/{key}?expires={expires_seconds}"
