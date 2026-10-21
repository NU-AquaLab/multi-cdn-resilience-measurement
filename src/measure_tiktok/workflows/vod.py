"""Run VOD collection and store metadata in PostgreSQL."""

import asyncio
import logging
import os

import measure_tiktok.utils.common as util
from measure_tiktok.collectors.base import BaseUploader
from measure_tiktok.collectors.vod import TikTokVODCollector
from measure_tiktok.storage.postgres import PostgresDB
from measure_tiktok.utils.common import extract_video_id

logger = logging.getLogger(__name__)


class VODMetadataUploader(BaseUploader):
    """Write VOD metadata batches to PostgreSQL."""

    def __init__(self):
        super().__init__()
        self.crawler_timestamp = util.get_uuid_timestamp()

    async def send(self, info: list[dict]):
        db = PostgresDB()
        try:
            for i in info:
                if not i:
                    continue
                await self._write_into_db_cdn(i, db)
        finally:
            db.disconnect()

    async def _write_into_db_cdn(self, info: dict, db: PostgresDB):
        video_id = extract_video_id(info["webpage_url"], info["webpage_url_domain"])

        insert_query = """  
        INSERT INTO web_video_cdn_metadata_vpn (
            uploader_id, video_id, crawler_timestamp, duration, title, upload_timestamp, view_count, like_count, comment_count, 
            webpage_url, original_url, webpage_url_domain, upload_date, ext, vcodec, acodec, format_id, tbr, 
            filesize, width, height, fps, dynamic_range, x_cache, x_cache_remote, x_parent_response, x_origin_response, 
            timing, network_cdn_url, timezone, city, region, country_code, cname, vpn_provider
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (video_id, crawler_timestamp) 
        DO UPDATE SET 
            view_count = EXCLUDED.view_count,
            like_count = EXCLUDED.like_count,
            comment_count = EXCLUDED.comment_count
        """

        for key in ["fps", "x-cache-remote", "x-origin-response", "tbr"]:
            if key not in info:
                info[key] = None
        data = (
            info["uploader_id"],
            video_id,
            self.crawler_timestamp,
            info["duration"],
            info["title"],
            info["upload_timestamp"],
            info["view_count"],
            info["like_count"],
            info["comment_count"],
            info["webpage_url"],
            info["original_url"],
            info["webpage_url_domain"],
            info["upload_date"],
            info["ext"],
            info["vcodec"],
            info["acodec"],
            info["format_id"],
            float(info["tbr"]) if info["tbr"] else None,
            info["filesize"],
            info["width"],
            info["height"],
            float(info["fps"]) if info["fps"] else None,
            info["dynamic_range"],
            info["x-cache"],
            info["x-cache-remote"],
            info["x-parent-response"],
            info["x-origin-response"],
            float(info["timing"]),
            info["network-cdn-url"],
            util.timezone,
            util.city,
            util.region,
            info["country_code"],
            info["cname"],
            os.getenv("VPN_PROVIDER") or None,
        )

        try:
            db.insert(insert_query, data)
        except Exception as e:
            logger.warning(f"Error inserting data into the database: {e}")


def main() -> None:
    downloader = TikTokVODCollector()
    downloader.register_uploader(VODMetadataUploader())
    asyncio.run(downloader.run())
