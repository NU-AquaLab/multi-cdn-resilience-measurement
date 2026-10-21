"""Measure live-stream CDN fallback after blocking delivery IPs."""

import json
import logging
import os
import time

from measure_tiktok.config import get_os_type, get_session_id
from measure_tiktok.fallback.browser import SeleniumController
from measure_tiktok.fallback.network import NetworkController
from measure_tiktok.storage.postgres import PostgresDB
from measure_tiktok.utils import common as util
from measure_tiktok.utils.common import init_timezone, parse_count, resolve_hostname_ips

logger = logging.getLogger(__name__)


class LiveFallbackMeasurer:
    """Measure delivery changes while a live stream is playing."""

    def __init__(self, session_id):
        self.selenium = SeleniumController(session_id)
        self.network = NetworkController(self.selenium)
        init_timezone()

    def write_into_db(
        self,
        room_id,
        start_time,
        resolved_time,
        room_category,
        viewer_count,
        fallback_delay,
        blocked_ip,
        resolved_ip,
        blocked_hostname,
        resolved_hostname,
    ):
        insert_query = """  
        INSERT INTO video_fallback_mechanism (
            room_id, start_time, resolved_time, room_category, viewer_count, fallback_delay,
            blocked_ip, resolved_ip, blocked_hostname, resolved_hostname, 
            timezone, city, region, country_code, source, stream_type
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (room_id, start_time) 
        DO NOTHING
        """
        init_timezone()
        viewer_count = parse_count(viewer_count)
        source = 1  # web
        stream_type = 1  # live
        data = (
            room_id,
            start_time,
            resolved_time,
            room_category,
            viewer_count,
            fallback_delay,
            blocked_ip,
            resolved_ip,
            blocked_hostname,
            resolved_hostname,
            util.timezone,
            util.city,
            util.region,
            util.country,
            source,
            stream_type,
        )

        if os.getenv("LIVE_FALLBACK_WRITE_DB", "0") != "1":
            logger.info("Live fallback record (database writes disabled): %s", data)
            return
        db = PostgresDB()
        try:
            db.insert(insert_query, data)
        finally:
            db.disconnect()

    def measure(self, room_id_path=None, max_delay=300000, refresh_interval=3600):
        """
        Scrape and refresh room IDs often, processing only unvisited ones.
        """
        processed_room_ids = set()
        seen_stream_ids = set()
        curr_hostname = None
        last_refresh_time = 0
        room_records = []
        os_type = get_os_type()

        try:
            now = time.time()
            resolved_time = None
            if now - last_refresh_time > refresh_interval:
                logger.info("Refreshing room list...")
                if room_id_path:
                    with open(room_id_path) as f:
                        room_records = json.load(f)
                else:
                    room_records = self.selenium.scrape_room_ids()
                    logger.debug(room_records)
                last_refresh_time = now

            for room_record in room_records[: min(50, len(room_records) - 1)]:
                room_id = room_record["id"]
                logger.info(f"room: {room_id}")
                if room_id in processed_room_ids:
                    logger.info(f"skipping room: {room_id}")
                    continue

                room_category = room_record.get("category", "unknown")
                logger.info(
                    f"\n=== Processing Room: {room_id} | Category: {room_category} ==="
                )

                try:
                    self.selenium.enter_live_stream(room_id)
                    time.sleep(5)

                    viewer_count = self.selenium.scrape_viewer_count()
                    if not viewer_count:
                        processed_room_ids.add(room_id)
                        continue

                    for _ in range(20):
                        hostname, stream_id = self.selenium.get_curr_stream_request(
                            room_id
                        )
                        if stream_id and stream_id not in seen_stream_ids:
                            curr_hostname = hostname
                            seen_stream_ids.add(stream_id)
                            logger.info(f"Updated stream ID: {stream_id}")
                            break
                        logger.warning(
                            "Stream ID not found or same as previous, retrying..."
                        )
                        time.sleep(2)

                    # Block individual delivery IPs.
                    target_ips = resolve_hostname_ips(curr_hostname)
                    need_to_block = list(set(target_ips))

                    if need_to_block:
                        rule = self.network.create_block_rule(need_to_block, os_type)

                        block_time = self.network.block_ips_by_rule(rule, os_type)
                        if not block_time:
                            processed_room_ids.add(room_id)
                            continue
                    else:
                        logger.warning(
                            "Skipping room: Could not determine current IP addresses."
                        )
                        processed_room_ids.add(room_id)
                        continue

                    while True:
                        resolved_hostname = None
                        try:
                            is_resolved, resolved_hostname, resolved_ip = (
                                self.network.is_resolved(
                                    stream_id, need_to_block, room_id
                                )
                            )

                            if is_resolved:
                                resolved_time = util.get_uuid_timestamp()
                                fallback_delay = resolved_time - block_time
                                logger.info(
                                    f"Fallback delay after blocking {need_to_block}: {fallback_delay:.2f} seconds"
                                )
                                self.write_into_db(
                                    room_id,
                                    block_time,
                                    resolved_time,
                                    room_category,
                                    viewer_count,
                                    fallback_delay,
                                    sorted(need_to_block),
                                    sorted(resolved_ip),
                                    curr_hostname,
                                    resolved_hostname,
                                )
                                break
                            else:
                                time.sleep(2)

                        except KeyboardInterrupt:
                            raise
                        except Exception as e:
                            logger.warning(f"Error inside fallback check loop: {e}")

                        curr_time = util.get_uuid_timestamp()
                        if curr_time - block_time > max_delay:
                            logger.warning(
                                f"Timeout reached after {max_delay}s — fallback not detected."
                            )
                            self.write_into_db(
                                room_id,
                                block_time,
                                -max_delay,
                                room_category,
                                viewer_count,
                                -max_delay,
                                need_to_block,
                                None,
                                curr_hostname,
                                resolved_hostname,
                            )
                            break

                except Exception as e:
                    logger.warning(f"Error processing room {room_id}: {e}")

                processed_room_ids.add(room_id)

                if "need_to_block" in locals() and need_to_block:
                    self.network.cleanup_ipconfig(need_to_block, os_type)

                # Refresh room list again if enough time has passed
                if time.time() - last_refresh_time > refresh_interval:
                    break  # break out of for-loop and refresh early

        except KeyboardInterrupt:
            logger.warning("\nMeasurement interrupted by user.")

        finally:
            logger.info("Final cleanup...")
            if "need_to_block" in locals() and need_to_block:
                try:
                    self.network.cleanup_ipconfig(need_to_block, os_type)
                except Exception as e:
                    logger.warning(f"Final linux iptables cleanup failed: {e}")
            try:
                self.selenium.cleanup_driver()
            except Exception as e:
                logger.warning(f"Failed to close Selenium browser: {e}")


def main():
    session_id = get_session_id()

    measurer = LiveFallbackMeasurer(session_id=session_id)

    measurer.measure()
