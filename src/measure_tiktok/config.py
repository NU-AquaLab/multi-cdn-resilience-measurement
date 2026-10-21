"""Load explicit run configuration and resolve user-owned data paths."""

import json
import os
import sys
from importlib.resources import files
from pathlib import Path

from dotenv import load_dotenv

_config_dir: Path | None = None


def load_config(path: str | Path | None = None) -> None:
    """Load one .env file without searching parent directories.

    Relative data paths are resolved beside this file, or in the current working
    directory when no file is specified. Existing environment variables win.
    """
    global _config_dir
    env_path = Path(path).expanduser().resolve() if path else Path.cwd() / ".env"
    if path is not None and not env_path.is_file():
        raise FileNotFoundError(f"Configuration file does not exist: {env_path}")
    _config_dir = env_path.parent
    load_dotenv(env_path, override=False)


def resolve_path(value: str | Path) -> Path:
    """Resolve a data path relative to the selected configuration directory."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (_config_dir or Path.cwd()) / path
    return path.resolve()


def get_cookie_path() -> Path:
    """Return the shared local cookie file used by collection and fallback."""
    return resolve_path(os.getenv("TIKTOK_COOKIE_FILE", "tiktok_cookies.pkl"))


def get_output_dir() -> Path:
    """Create and return the directory for generated discovery records."""
    path = resolve_path(os.getenv("OUTPUT_DIR", "results"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_session_id() -> str:
    """Require a session cookie without including its value in error messages."""
    session_id = os.getenv("TIKTOK_SESSION_ID", "").strip()
    if not session_id:
        raise ValueError("Set TIKTOK_SESSION_ID in the environment or .env")
    return session_id


def get_os_type() -> str:
    """Select a supported firewall backend for the measurement host."""
    default = {"linux": "linux", "darwin": "mac"}.get(sys.platform, "")
    os_type = os.getenv("MEASUREMENT_OS", default)
    if os_type not in {"linux", "mac"}:
        raise ValueError("Fallback measurements require MEASUREMENT_OS=linux or mac")
    return os_type


def load_live_categories(path: str | Path | None = None) -> list[str]:
    """Read a custom category list or the public URLs bundled in the package."""
    custom_path = path or os.getenv("LIVE_CATEGORIES_FILE")
    resource = (
        resolve_path(custom_path)
        if custom_path
        else files("measure_tiktok.data").joinpath("livestream_categories.json")
    )
    categories = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(categories, list) or not categories:
        raise ValueError("Live categories must be a nonempty JSON list of URLs")
    if not all(
        isinstance(url, str) and url.startswith("https://www.tiktok.com/live/")
        for url in categories
    ):
        raise ValueError("Live categories must contain TikTok live URLs")
    return categories


def validate_configuration(command: str) -> None:
    """Check local prerequisites before starting a browser or changing rules."""
    missing = [
        name for name in ("DB_NAME", "DB_USER", "DB_HOST") if not os.getenv(name)
    ]
    if missing:
        raise ValueError("Set database configuration: " + ", ".join(missing))
    if command.startswith("fallback-"):
        get_session_id()
        get_os_type()
    if command == "collect-live" or command in {"fallback-vod", "fallback-iterative"}:
        if not get_cookie_path().is_file():
            raise FileNotFoundError(
                "Cookie file is missing. Run collect-vod to log in, or set "
                "TIKTOK_COOKIE_FILE to your existing Selenium cookie pickle."
            )
    if command == "collect-vod" and os.getenv("HEADLESS", "0") == "1":
        raise ValueError("collect-vod requires HEADLESS=0 for interactive login")
    if command == "fallback-live":
        load_live_categories()
