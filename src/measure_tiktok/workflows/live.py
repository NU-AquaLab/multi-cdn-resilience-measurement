"""Run live-stream collection and store metadata in PostgreSQL."""

import asyncio
import logging

import measure_tiktok.utils.common as util
from measure_tiktok.collectors.base import BaseUploader
from measure_tiktok.collectors.live import TikTokLiveCollector
from measure_tiktok.storage.postgres import PostgresDB
from measure_tiktok.utils.common import init_timezone

logger = logging.getLogger(__name__)


class LiveMetadataUploader(BaseUploader):
    """Write live-stream metadata batches to PostgreSQL."""

    def __init__(self):
        super().__init__()
        self.crawler_timestamp = util.get_uuid_timestamp()

    async def send(self, info: list[dict]):
        for i in info:
            if not i:
                continue
            await self._write_into_live_streaming_table(i)

    async def _write_into_live_streaming_table(self, info: dict):
        db = PostgresDB()
        insert_query = """  
        INSERT INTO streaming_cdn_metadata (
            uploader_id, stream_id, crawler_timestamp, title, stream_epoch, concurrent_view_count, 
            webpage_url, original_url, webpage_url_domain, ext, vcodec, format_id, tbr, 
            dynamic_range, network_cdn_url, cdn_host_name, cdn_servers, timezone, city, region, country_code, stream_category, source, stream_type
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (stream_id, cdn_host_name) 
        DO UPDATE SET 
            concurrent_view_count = EXCLUDED.concurrent_view_count
        """
        init_timezone()
        data = (
            info["uploader_id"],
            info["stream_id"],
            self.crawler_timestamp,
            info["title"],
            info["stream_epoch"],
            info["concurrent_view_count"],
            info["webpage_url"],
            info["original_url"],
            info["webpage_url_domain"],
            info["ext"],
            info["vcodec"],
            info["format_id"],
            info["tbr"],
            info["dynamic_range"],
            info["network-cdn-url"],
            info["cdn_host_name"],
            info["cdn_servers"],
            util.timezone,
            util.city,
            util.region,
            util.country,
            info["stream_category"],
            info["source"],
            info["stream_type"],
        )

        try:
            db.insert(insert_query, data)
            logger.info("Inserted data into the database")
        except Exception as e:
            logger.warning(f"Error inserting data into the database: {e}")
        finally:
            db.disconnect()


def main() -> None:
    downloader = TikTokLiveCollector()
    downloader.register_uploader(LiveMetadataUploader())
    asyncio.run(downloader.run())
