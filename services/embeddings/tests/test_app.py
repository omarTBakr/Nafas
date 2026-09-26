from fastapi.testclient import TestClient

from embeddings.app import create_app
from embeddings.config import Settings


class FakeEncoder:
    device = "cpu"

    def __init__(self, width=1024):
        self.width = width

    def encode(self, texts):
        return [[float(len(t))] + [0.0] * (self.width - 1) for t in texts]


def test_texts_come_back_as_one_vector_each_with_the_model_named():
    client = TestClient(create_app(FakeEncoder(), Settings()))

    body = client.post("/v1/embed", json={"texts": ["ضغط الدم", "LDL 162"]}).json()

    assert [v[0] for v in body["vectors"]] == [8.0, 7.0] and len(body["vectors"][0]) == 1024
    assert body["model_id"] == "BAAI/bge-m3"


def test_too_many_or_too_long_texts_are_refused():
    client = TestClient(create_app(FakeEncoder(), Settings(max_texts=2, max_chars=10)))

    assert client.post("/v1/embed", json={"texts": ["a", "b", "c"]}).status_code == 413
    assert client.post("/v1/embed", json={"texts": ["x" * 11]}).status_code == 413


def test_a_model_of_the_wrong_width_is_caught():
    client = TestClient(create_app(FakeEncoder(width=768), Settings()), raise_server_exceptions=False)

    assert client.post("/v1/embed", json={"texts": ["a"]}).status_code == 500


def test_health_says_the_model_is_not_pinned_yet():
    health = TestClient(create_app(FakeEncoder(), Settings())).get("/health").json()

    assert health["pinned"] is False and health["device"] == "cpu"
