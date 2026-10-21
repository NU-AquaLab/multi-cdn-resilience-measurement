# Architecture

Each measurement starts through `measure-tiktok`. The CLI loads one configuration file, validates local prerequisites, and imports only the selected workflow. Importing the package or requesting help does not start Chrome, connect to PostgreSQL, or change firewall rules.

## Collection

`collectors/vod.py` and `collectors/live.py` discover TikTok content with Selenium and combine browser delivery information with yt-dlp metadata. Shared coordination and batching live in `collectors/base.py`.

`workflows/vod.py` and `workflows/live.py` register the corresponding PostgreSQL uploader and start collection. SQL column names and measurement fields follow the existing research schema.

## Fallback experiments

The three experiment modules in `fallback/` share two controllers:

- `browser.py` manages Chrome, discovers content, and reads performance logs.
- `network.py` resolves delivery IPs and applies or removes firewall rules.

`live.py` observes a live stream after blocking its current delivery IPs. `vod.py` follows successive VOD fallback events. `iterative.py` repeats the initial fallback measurement for each discovered video.

The live experiment preserves its original default of disabled database writes. `LIVE_FALLBACK_WRITE_DB=1` enables persistence; otherwise records are logged. VOD fallback and both collection workflows write to PostgreSQL.

## Configuration and files

`config.py` resolves credentials and user files separately from the installed package. The default configuration is `./.env`; an explicit `--config` path changes the base directory for relative paths. Existing environment variables take precedence.

| Setting | Purpose |
| --- | --- |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | PostgreSQL connection |
| `TIKTOK_SESSION_ID` | Session cookie used by fallback commands |
| `TIKTOK_COOKIE_FILE` | Selenium cookie pickle; defaults to `tiktok_cookies.pkl` |
| `OUTPUT_DIR` | Generated discovery records; defaults to `results` |
| `LIVE_CATEGORIES_FILE` | Optional JSON category list; otherwise use packaged URLs |
| `MEASUREMENT_OS` | Optional `linux` or `mac` firewall override |
| `CAPTURE_INTERFACE` | Optional packet-capture interface override |
| `CHROME_BINARY` | Optional Chrome/Chromium executable path |
| `HEADLESS` | VOD collection requires `0` for interactive login |
| `VPN_PROVIDER` | Optional provider label stored with VOD metadata |
| `LIVE_FALLBACK_WRITE_DB` | Set to `1` to persist live fallback records |
| `INFRA_DB_HOST` | Optional host for the auxiliary `InfraDB` query helper |

Public category URLs are installed as package data. Cookies and generated results are never written into the package directory, so the same layout works for editable installs and wheels.

## Original script mapping

| Original path | Package module |
| --- | --- |
| `download_video.py` | `measure_tiktok.workflows.vod` |
| `download_live_streamings.py` | `measure_tiktok.workflows.live` |
| `handler/tiktok_downloader.py` | `measure_tiktok.collectors.vod` |
| `handler/tiktok_live_downloader.py` | `measure_tiktok.collectors.live` |
| `fallback_mechanism/main.py` | `measure_tiktok.fallback.live` |
| `fallback_mechanism/vod_fallback.py` | `measure_tiktok.fallback.vod` |
| `fallback_mechanism/vod_fallback_iterative.py` | `measure_tiktok.fallback.iterative` |
| `fallback_mechanism/selenium_controller.py` | `measure_tiktok.fallback.browser` |
| `fallback_mechanism/network_controller.py` | `measure_tiktok.fallback.network` |
| `db/db.py` | `measure_tiktok.storage.postgres` |
| `utils/util.py` | `measure_tiktok.utils.common` and `measure_tiktok.collectors.base` |
| `utils/video_util.py` | `measure_tiktok.utils.video` |

The older standalone `measure_fallback.py`, non-TikTok handlers, analysis/plotting scripts, mobile instrumentation, and machine-specific cron jobs are outside this package's scope. The original VPN launchers are replaced by the shared [Docker launchers](docker-launchers.md), which keep credentials in local configuration.

## Refactoring notes

The package retains the research measurement algorithms, timing parameters, and database fields. Changes include consistent formatting/imports, module and class documentation, configurable paths, console logging, and a shared Docker image. Credentials and captured data are excluded.

A few error paths were corrected: failed VOD extraction returns an empty record, a missing cache header no longer raises an uninitialized-variable error, live discovery closes Chrome on failure, and database connection failures propagate. Live stream metadata now resolves the URL of the stream being processed rather than a leftover loop variable. Location requests have a timeout, and location fields have defined defaults.

These changes are covered by offline checks where applicable. They do not establish compatibility with current TikTok responses or validate the full measurement methodology. Browser runs, database integration, VPN behavior, and firewall cleanup still need validation in a controlled experiment.
