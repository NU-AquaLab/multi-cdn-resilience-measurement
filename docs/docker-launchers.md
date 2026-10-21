# Docker launchers

The repository includes a launcher for each measurement workflow:

| Script | Container command |
| --- | --- |
| `bash_video.sh` | `collect-vod` |
| `bash_live_streaming.sh` | `collect-live` |
| `bash_live_streaming_fallbacks.sh` | `fallback-live` |
| `bash_vod_fallbacks.sh` | `fallback-vod` |
| `bash_vod_fallbacks_iterative.sh` | `fallback-iterative` |

All five call `scripts/run_docker.sh`, so image selection, configuration, mounts, and permissions are handled consistently. Bash and Docker are required; the host does not need a Python installation to use these launchers.

## Configuration

Copy `.env.example` to `.env` and fill in your measurement settings. Launchers default to the repository's `.env`, even when invoked from another directory. Select another file with `ENV_FILE`:

```bash
ENV_FILE=/path/to/experiment/.env ./bash_live_streaming.sh
```

Use Docker env-file syntax: unquoted `KEY=value` lines, without `export`, variable expansion, or shell commands. The scripts read this file as data and never source it. Relative cookie, category, and output paths are resolved beside the selected env file. Exported measurement settings override file values.

| Setting | Default | Purpose |
| --- | --- | --- |
| `DOCKER_IMAGE` | `measure-tiktok:latest` | Measurement image |
| `ENV_FILE` | Repository `.env` | Measurement configuration |
| `VPN_CONTAINER` | Unset | Share an existing VPN container's network |
| `CONTAINER_NAME` | Generated name | Optional name for a single measurement container |
| `LOG_LEVEL` | `INFO` | Measurement log verbosity |

These launcher settings are exported shell variables. Database, session, and path settings belong in `.env` or exported variables. The launchers translate host file paths to container paths and always use the image's Chromium binary and Linux firewall backend.

## Build and run

```bash
./scripts/build_docker.sh
./bash_vod_fallbacks.sh --dry-run
./bash_vod_fallbacks.sh
```

A missing image builds automatically. Pass `--build` to rebuild an existing image. `--dry-run` prints the Docker commands without running Docker or creating files; it still checks the configuration and required input files. Secret values are not printed.

Measurements run in the foreground so their output and exit status remain visible. Containers are removed when they exit. Use your scheduler or terminal session manager if you need unattended execution.

`OUTPUT_DIR` is created on the host and mounted at `/work/results`. Live collection and VOD fallback mount the cookie file read-only. VOD collection mounts that one file writable so it can save login cookies; the rest of your configuration directory is not mounted. Custom live category JSON is mounted read-only.

Fallback commands receive `NET_ADMIN` for their container network namespace. They do not use the host network namespace. When sharing a VPN container, the experiment and VPN share that network namespace.

## Interactive VOD collection

`bash_video.sh` needs an interactive terminal, `HEADLESS=0`, and a local X11 display. The launcher forwards `DISPLAY` and the X11 socket directory. If `XAUTHORITY` is set, it mounts that authorization file read-only. The X server must permit the container's user to connect.

```bash
./bash_video.sh
```

`X11_SOCKET_DIR` can override `/tmp/.X11-unix`. A dry run uses `:0` as a display placeholder if `DISPLAY` is unset; an actual run requires a real display. On Wayland-only desktops, macOS, Windows, or remote machines without X11, use the local `measure-tiktok collect-vod` command for interactive collection.

## Measurements through a VPN

To reuse an already connected VPN container:

```bash
VPN_CONTAINER=my-vpn ./bash_vod_fallbacks.sh
```

This joins the existing network without starting or stopping that VPN container. Ensure it is connected before launching the measurement.

For country-by-country measurements, the batch runner starts a dedicated Gluetun container for each country:

```bash
cp .env.vpn.example .env.vpn
# Fill in your VPN provider credentials in .env.vpn.
# Edit the example list or create your own country file.
./scripts/run_vpn_measurements.sh collect-live config/vpn_countries.example.txt --dry-run
./scripts/run_vpn_measurements.sh collect-live config/vpn_countries.example.txt
```

The example VPN configuration uses Surfshark with WireGuard. Supply your own key and provider settings. Countries must use names supported by your provider, one per line; blank lines and lines beginning with `#` are ignored. Names containing spaces are preserved.

The runner waits for Docker to report the VPN as healthy before starting the measurement. It runs countries sequentially, stops on the first measurement failure, and removes its containers after completion, failure, or interruption. Existing containers are not taken over. VOD collection still needs manual login for each run.

Additional exported settings:

| Setting | Default |
| --- | --- |
| `VPN_ENV_FILE` | Repository `.env.vpn` |
| `VPN_IMAGE` | `qmcgaw/gluetun:v3.38.0` |
| `VPN_READY_TIMEOUT` | `180` seconds |

The image tag follows the original launcher; override it when testing another Gluetun release. `VPN_PROVIDER` defaults to the configured `VPN_SERVICE_PROVIDER` when no metadata label is supplied.

Use a `DB_HOST` reachable through the VPN container. The batch runner adds `host.docker.internal` for the Docker host; a separately managed VPN container must provide its own host mapping. If Gluetun blocks access to your database network, configure `FIREWALL_OUTBOUND_SUBNETS` in `.env.vpn` for that network. `.env.vpn` is ignored by Git and excluded from image builds.

Launcher tests use a mock Docker executable. They validate orchestration and cleanup without testing a provider connection or running live measurements.
