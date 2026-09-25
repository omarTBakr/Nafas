import os

import pytest

from nafas_core.config import Settings
from nafas_core.tracing import configure_tracing

LANGSMITH_VARS = [
    "LANGSMITH_TRACING",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
    "LANGSMITH_ENDPOINT",
    "LANGSMITH_HIDE_INPUTS",
    "LANGSMITH_HIDE_OUTPUTS",
]


@pytest.fixture(autouse=True)
def restore_environment(monkeypatch):
    """configure_tracing writes os.environ; monkeypatch puts every key back afterwards."""
    for name in LANGSMITH_VARS:
        monkeypatch.delenv(name, raising=False)


def test_tracing_is_off_by_default():
    assert configure_tracing(Settings(_env_file=None)) is False
    assert os.environ["LANGSMITH_TRACING"] == "false"


def test_tracing_without_a_key_stays_off():
    """A half-filled .env must not turn every model call into an auth failure."""
    settings = Settings(_env_file=None, langsmith_tracing=True)

    assert configure_tracing(settings) is False
    assert os.environ["LANGSMITH_TRACING"] == "false"


def test_settings_from_env_file_reach_the_process_environment():
    settings = Settings(
        _env_file=None,
        langsmith_tracing=True,
        langsmith_api_key="lsv2-test",
        langsmith_project="nafas-test",
        langsmith_hide_inputs=True,
    )

    assert configure_tracing(settings) is True
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_API_KEY"] == "lsv2-test"
    assert os.environ["LANGSMITH_PROJECT"] == "nafas-test"
    assert os.environ["LANGSMITH_HIDE_INPUTS"] == "true"
    assert os.environ["LANGSMITH_HIDE_OUTPUTS"] == "false"
