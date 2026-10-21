# TikTok Multi-CDN Measurements

Tools for studying how TikTok delivers video-on-demand (VOD) and live streams through multiple content delivery networks (CDNs). The project collects delivery metadata and measures how playback switches to another hostname or IP address when the current delivery path is blocked.

Selenium captures browser network activity, yt-dlp extracts media metadata, and PostgreSQL stores measurement results.

## Installation

Use Python 3.11 or 3.12 and install Google Chrome. Selenium can manage ChromeDriver, or you can install a driver compatible with your browser.

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
cp .env.example .env
measure-tiktok --help
```

Edit `.env` with your database connection details. The scripts expect an existing PostgreSQL schema; table creation and migrations are not included. See [database setup](docs/database.md) for the required tables and constraints.

## Running measurements

| Measurement | Local command | Docker launcher |
| --- | --- | --- |
| Collect VOD metadata | `measure-tiktok collect-vod` | `./bash_video.sh` |
| Collect live-stream metadata | `measure-tiktok collect-live` | `./bash_live_streaming.sh` |
| Measure live-stream fallback | `measure-tiktok fallback-live` | `./bash_live_streaming_fallbacks.sh` |
| Measure VOD fallback | `measure-tiktok fallback-vod` | `./bash_vod_fallbacks.sh` |
| Repeat VOD fallback trials | `measure-tiktok fallback-iterative` | `./bash_vod_fallbacks_iterative.sh` |

You can also run these commands with `python -m measure_tiktok`. Use `--help` after any command to see its description.

By default, configuration comes from `.env` in the working directory. To run an experiment stored elsewhere:

```bash
measure-tiktok --config /path/to/experiment/.env collect-live
```

Environment variables override `.env` values. Cookie and output paths are relative to the configuration file's directory, or the working directory when using environment variables alone. The package never searches parent directories for credentials.

### TikTok login

Run `collect-vod` with `HEADLESS=0`. It opens Chrome, prompts you to log in, and saves your Selenium cookies to `tiktok_cookies.pkl`. Live collection and VOD fallback read the same file. Set `TIKTOK_COOKIE_FILE` to use an existing cookie file or a different location.

All fallback commands also require `TIKTOK_SESSION_ID`, set to the value of your TikTok `sessionid` cookie. Keep this value and your cookies private; `.env` and cookie pickles are excluded from version control. Only load pickle files you created or trust.

### Fallback experiments

Fallback experiments change firewall rules. Run them in a dedicated measurement environment:

- **Linux:** install `iptables` and allow the measurement process to invoke it through `sudo`.
- **macOS:** the scripts use `pfctl` and modify `/etc/pf.conf`.

The firewall backend is detected automatically. Set `MEASUREMENT_OS=linux` or `mac` to override it. The optional packet-capture helper needs TShark; use `CAPTURE_INTERFACE` to select the interface.

Live fallback logs results by default. Set `LIVE_FALLBACK_WRITE_DB=1` to also write them to PostgreSQL. The other four commands write to the database.

Live category URLs are bundled with the package. Set `LIVE_CATEGORIES_FILE` to a JSON list of TikTok live URLs to customize discovery. Generated room records go to `results/`, or the directory specified by `OUTPUT_DIR`.

Use the [VPN batch runner](docs/docker-launchers.md#measurements-through-a-vpn) for measurements across countries, or connect to your VPN separately. `VPN_PROVIDER` supplies the provider label recorded with VOD metadata.

## Code layout

```text
src/measure_tiktok/
├── cli.py          Command-line interface
├── config.py       Configuration and runtime paths
├── collectors/     VOD and live-stream discovery and extraction
├── workflows/      Collection entry points and metadata uploaders
├── fallback/       Fallback experiments, browser control, and firewall rules
├── storage/        PostgreSQL connections and queries
├── utils/          Network-response parsing and shared helpers
└── data/           Bundled live category URLs
tests/              Offline tests
docs/               Architecture and database setup
docker/             Shared measurement image
scripts/            Docker build, launch, and VPN helpers
config/             Example VPN country list
bash_*.sh           Convenience launchers for the five workflows
```

See [architecture](docs/architecture.md) for module responsibilities and the mapping from the original scripts.

## Docker

The five `bash_*.sh` launchers use the shared measurement image. They read `.env` from the repository root, mount the required cookies and output directory, and add network permissions for fallback experiments. They work from any working directory and build the image automatically if it is missing.

```bash
# Build explicitly, or let a launcher build on first use.
./scripts/build_docker.sh

# Inspect a launch without starting Docker.
./bash_live_streaming_fallbacks.sh --dry-run

# Run the experiment in the foreground.
./bash_live_streaming_fallbacks.sh
```

Add `--build` to rebuild the image, or set `ENV_FILE` and `DOCKER_IMAGE` to select another experiment configuration or image. Docker env files use unquoted `KEY=value` lines; they are never executed as shell code.

The image includes Chromium, ChromeDriver, TShark, and Linux firewall tools. `bash_video.sh` needs an interactive terminal and a local X11 display for login. On hosts without X11, run VOD collection locally. Use a database address reachable from the container, such as `host.docker.internal` for a database on the Docker host.

To use an already connected VPN container:

```bash
VPN_CONTAINER=my-vpn ./bash_vod_fallbacks.sh
```

For country-by-country runs, configure `.env.vpn` from `.env.vpn.example`, then use `scripts/run_vpn_measurements.sh`. See [Docker launchers](docs/docker-launchers.md) for configuration, display access, VPN batches, and cleanup behavior.

The image builds and passes an offline Chromium smoke test. Launcher behavior is tested with a mock Docker executable. Live TikTok, database, and VPN measurements still need validation in your environment.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
python -m pytest
python -m build
```

Tests run without TikTok access, a database, or firewall changes. CI checks formatting, tests, and package builds on Python 3.11 and 3.12. See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidance.

A distribution license has not yet been selected.
