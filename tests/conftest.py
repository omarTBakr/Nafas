import pytest

import utils.config


@pytest.fixture(autouse=True)
def fresh_settings(monkeypatch, tmp_path):
    """
    Gives every test its own Settings, and its own scratch directory.

    The settings object is a module-level singleton, so without this a test
    that sets an environment variable would either see a cached instance from
    an earlier test or leak its own into a later one. Pointing TEMP_DIR at
    tmp_path keeps `temp_root` from creating `assets/` in the repository.
    """
    utils.config._settings_instance = None
    monkeypatch.setenv("TEMP_DIR", str(tmp_path / "assets"))

    yield

    utils.config._settings_instance = None
