"""Keep tests independent of local credentials and research configuration."""

import pytest

from measure_tiktok import config


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch, tmp_path):
    for name in (
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "DB_HOST",
        "DB_PORT",
        "TIKTOK_SESSION_ID",
        "TIKTOK_COOKIE_FILE",
        "OUTPUT_DIR",
        "LIVE_CATEGORIES_FILE",
        "MEASUREMENT_OS",
        "HEADLESS",
        "VPN_PROVIDER",
        "LIVE_FALLBACK_WRITE_DB",
        "PYTHON_DOTENV_DISABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "_config_dir", None)
    monkeypatch.chdir(tmp_path)
