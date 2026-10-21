"""Configuration must work outside the source tree without leaking parent settings."""

import json
import os

import pytest

from measure_tiktok import config


def test_default_config_does_not_search_parents(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("DB_NAME=parent_database\n")
    child = tmp_path / "experiment"
    child.mkdir()
    monkeypatch.chdir(child)
    config.load_config()
    assert os.getenv("DB_NAME") is None
    assert config.get_cookie_path() == child / "tiktok_cookies.pkl"


def test_explicit_config_resolves_paths_and_preserves_environment(
    tmp_path, monkeypatch
):
    folder = tmp_path / "experiment"
    folder.mkdir()
    env = folder / ".env"
    env.write_text("DB_NAME=file_database\nTIKTOK_COOKIE_FILE=sessions/login.pkl\n")
    monkeypatch.setenv("DB_NAME", "environment_database")
    # Track variables that dotenv will set so fixture teardown removes them.
    monkeypatch.setenv("TIKTOK_COOKIE_FILE", "sessions/login.pkl")
    config.load_config(env)
    assert os.getenv("DB_NAME") == "environment_database"
    assert config.get_cookie_path() == folder / "sessions/login.pkl"
    assert config.get_output_dir() == folder / "results"
    assert (folder / "results").is_dir()


def test_dotenv_is_loaded(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_NAME", "temporary")
    monkeypatch.delenv("DB_NAME")
    env = tmp_path / ".env"
    env.write_text("DB_NAME=from_file\n")
    config.load_config(env)
    assert os.getenv("DB_NAME") == "from_file"


def test_explicit_missing_config_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="Configuration file"):
        config.load_config(tmp_path / "missing.env")


def test_session_is_required_and_trimmed(monkeypatch):
    with pytest.raises(ValueError, match="TIKTOK_SESSION_ID"):
        config.get_session_id()
    monkeypatch.setenv("TIKTOK_SESSION_ID", " example-session ")
    assert config.get_session_id() == "example-session"


@pytest.mark.parametrize("platform,expected", [("linux", "linux"), ("darwin", "mac")])
def test_platform_detection(monkeypatch, platform, expected):
    monkeypatch.setattr(config.sys, "platform", platform)
    assert config.get_os_type() == expected


def test_platform_override_and_rejection(monkeypatch):
    monkeypatch.setenv("MEASUREMENT_OS", "mac")
    assert config.get_os_type() == "mac"
    monkeypatch.setenv("MEASUREMENT_OS", "unsupported")
    with pytest.raises(ValueError, match="MEASUREMENT_OS"):
        config.get_os_type()


def test_packaged_categories_available_without_source_relative_paths():
    categories = config.load_live_categories()
    assert categories
    assert all(url.startswith("https://www.tiktok.com/live/") for url in categories)


def test_custom_categories(tmp_path, monkeypatch):
    categories = ["https://www.tiktok.com/live/gaming"]
    (tmp_path / "categories.json").write_text(json.dumps(categories))
    monkeypatch.setenv("LIVE_CATEGORIES_FILE", "categories.json")
    assert config.load_live_categories() == categories


@pytest.mark.parametrize("value", [[], {}, [42], ["https://example.com/live/"]])
def test_invalid_category_config_is_rejected(tmp_path, value):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="categor"):
        config.load_live_categories(path)
