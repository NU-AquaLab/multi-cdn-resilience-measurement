# Database setup

The measurement code uses PostgreSQL through `psycopg2`. Configure the connection using the `DB_*` values in `.env` or environment variables.

An existing research schema is required. This repository does not include a schema dump or migrations, so installing the package does not create tables. Use the insert statements below to identify the columns expected by each workflow; provision compatible types in your database before running measurements.

| Command | Table | Unique constraint used by `ON CONFLICT` | Insert implementation |
| --- | --- | --- | --- |
| `collect-vod` | `web_video_cdn_metadata_vpn` | `(video_id, crawler_timestamp)` | [workflows/vod.py](../src/measure_tiktok/workflows/vod.py) |
| `collect-live` | `streaming_cdn_metadata` | `(stream_id, cdn_host_name)` | [workflows/live.py](../src/measure_tiktok/workflows/live.py) |
| `fallback-live` | `video_fallback_mechanism` | `(room_id, start_time)` | [fallback/live.py](../src/measure_tiktok/fallback/live.py) |
| `fallback-vod` | `video_fallback_mechanism_vod` | `(video_link, crawler_timestamp)` | [fallback/vod.py](../src/measure_tiktok/fallback/vod.py) |
| `fallback-iterative` | `video_fallback_mechanism_vod_iterative` | `(video_link, start_time)` | [fallback/iterative.py](../src/measure_tiktok/fallback/iterative.py) |

Live fallback database writes are disabled by default. Set `LIVE_FALLBACK_WRITE_DB=1` to enable them. Other workflows persist their results automatically.

The storage module also contains query helpers for analysis and an optional `InfraDB` connection for IP geolocation. The five measurement commands do not require that separate infrastructure database.

For Docker, set `DB_HOST` to a host reachable from the container. The example value `localhost` only works when PostgreSQL runs in the same network namespace as the measurement process.
