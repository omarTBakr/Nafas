from utils.config import Settings, get_setting


def test_settings_load_without_an_env_file():
    """A fresh checkout has no .env, and that has to be enough to start."""
    settings = Settings()

    assert settings.api_port == 8000
    assert settings.temporal_task_queue == "nafas_queue"
    assert settings.temporal_namespace == "default"


def test_the_worker_is_off_by_default():
    """
    Two workers on one queue is the expensive mistake, so the default is the
    one that cannot cause it: the API runs no worker unless asked.
    """
    assert Settings().run_worker_in_api is False


def test_get_setting_is_a_singleton():
    assert get_setting() is get_setting()


def test_temp_root_is_created_on_use(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMP_DIR", str(tmp_path / "scratch"))

    root = Settings().temp_root

    assert root.is_dir()


def test_unknown_variables_are_ignored(monkeypatch):
    """A shared .env may hold keys for other tools; they must not fail startup."""
    monkeypatch.setenv("SOMETHING_ELSE_ENTIRELY", "1")

    assert Settings().api_host == "0.0.0.0"
