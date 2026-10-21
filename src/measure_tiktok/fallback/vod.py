"""Measure successive CDN fallback events for video-on-demand."""

import json
import logging
import time

from measure_tiktok.config import get_os_type, get_session_id
from measure_tiktok.fallback.browser import SeleniumController
from measure_tiktok.fallback.network import NetworkController
from measure_tiktok.storage.postgres import PostgresDB
from measure_tiktok.utils import common as util
from measure_tiktok.utils.common import (
    get_uuid_timestamp,
    init_timezone,
)
from measure_tiktok.utils.video import (
    get_current_video_used_ips,
    get_current_video_used_ips_w_resource_id,
)

logger = logging.getLogger(__name__)


class VODFallbackMeasurer:
    """Follow CDN changes until a VOD fallback cycle completes."""

    def __init__(self, session_id):
        self.session_id = session_id
        self.selenium = SeleniumController(session_id)
        self.network = NetworkController(self.selenium)
        self.os_type = get_os_type()
        init_timezone()

    def write_into_db(self, data_entry):
        db = PostgresDB()
        init_timezone()
        insert_query = """  
        INSERT INTO video_fallback_mechanism_vod (
            video_link, crawler_timestamp, resource_id, fallback_logs, 
            timezone, city, region, country_code, source, stream_type, status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (video_link, crawler_timestamp) 
        DO NOTHING
        """
        data = (
            data_entry["video_link"],
            data_entry["crawler_timestamp"],
            data_entry["resource_id"],
            data_entry["fallback_logs"],
            util.timezone,
            util.city,
            util.region,
            util.country,
            data_entry["source"],
            data_entry["stream_type"],
            data_entry["status"],
        )

        try:
            db.insert(insert_query, data)
        except Exception as e:
            logger.warning(f"Error inserting data into the database: {e}")
        finally:
            db.disconnect()

    def measure(self, max_delay=300000):
        try:
            video_links = self.selenium.scrape_vod_links()
            for v_link in video_links[:50]:
                try:
                    logger.info(f"\n=== Processing vod: {v_link} ===")
                    curr_ips, hostname, resource_id = get_current_video_used_ips(
                        v_link, self.selenium.driver
                    )
                    need_to_block = list(set(curr_ips))
                    if not need_to_block:
                        logger.warning(f"No IPs found to block for {hostname}")
                        continue

                    rule = self.network.create_block_rule(need_to_block, self.os_type)
                    block_time = self.network.block_ips_by_rule(rule, self.os_type)
                    switch_counter, index = 0, 0
                    fallback_logs, status = self.recursive_fallback(
                        hostname,
                        v_link,
                        need_to_block,
                        resource_id,
                        block_time,
                        switch_counter,
                        index,
                        need_to_block,
                        max_delay,
                    )
                    if not fallback_logs:
                        continue
                    resource_id = None
                    if fallback_logs:
                        resource_id = fallback_logs[0].get("resource_id")
                    data_entry = {
                        "video_link": v_link,
                        "crawler_timestamp": get_uuid_timestamp(),
                        "resource_id": resource_id,
                        "fallback_logs": json.dumps(fallback_logs),
                        "source": 1,  # web
                        "stream_type": 1,  # vod,
                        "status": status,
                    }
                    self.write_into_db(data_entry)
                    logger.info("written into db")
                except Exception as e:
                    logger.warning(f"Error in fallback VOD: {e}")

        except Exception as e:
            logger.warning(f"Error in measure: {e}")
        finally:
            logger.info("Final cleanup...")
            if "need_to_block" in locals() and need_to_block:
                try:
                    self.network.cleanup_ipconfig(need_to_block, self.os_type)
                except Exception as e:
                    logger.warning(f"Final linux iptables cleanup failed: {e}")
            try:
                self.selenium.cleanup_driver()
            except Exception as e:
                logger.warning(f"Failed to close Selenium browser: {e}")

    def recursive_fallback(
        self,
        hostname,
        v_link,
        need_to_block,
        resource_id,
        block_time,
        switch_counter,
        index,
        blocked_ips_history,
        max_delay=None,
        fallback_log=None,
    ):
        if get_uuid_timestamp() - block_time > max_delay:
            logger.warning(f"Timeout after {max_delay}ms — fallback not detected.")
            self.network.cleanup_ipconfig(blocked_ips_history, self.os_type)
            return fallback_log, "incomplete"
        if fallback_log is None:
            fallback_log = []
        if switch_counter >= 2:
            logger.info(
                f"Fallback cycle complete after {switch_counter} switches — stabilized."
            )
            self.network.cleanup_ipconfig(blocked_ips_history, self.os_type)
            return fallback_log, "complete"

        try:
            is_resolved, resolved_hostname, resolved_ips = self.is_resolved_vod(
                blocked_ips_history, v_link, resource_id
            )
            logger.info(
                f"Current hostname: {hostname} | Resolved: {resolved_hostname} | resolved_ips: {resolved_ips} | resource_id: {resource_id}"
            )
            if is_resolved:
                fallback_delay = get_uuid_timestamp() - block_time
                if resolved_hostname != hostname:
                    switch_counter += 1
                    f"Fallback {switch_counter + 1}: {hostname} → {resolved_hostname}"
                else:
                    logger.info(
                        f"Fallback {switch_counter}: {hostname} → {resolved_hostname}"
                    )
                logger.info(
                    f"    ↳ Delay: {fallback_delay:.2f}ms | New IPs: {resolved_ips}"
                )

                index += 1
                fallback_log.append(
                    {
                        "index": index,
                        "video_url": v_link,
                        "switch_counter": switch_counter,
                        "from_hostname": hostname,
                        "to_hostname": resolved_hostname,
                        "blocked_ips": need_to_block.copy(),
                        "new_ips": resolved_ips,
                        "delay_ms": round(fallback_delay, 2),
                        "resource_id": resource_id,
                    }
                )

                # Block new IPs
                new_block = list(set(resolved_ips))
                rule = self.network.create_block_rule(new_block, self.os_type)
                new_block_time = self.network.block_ips_by_rule(rule, self.os_type)
                blocked_ips_history.extend(new_block)

                # Recurse
                return self.recursive_fallback(
                    resolved_hostname,
                    v_link,
                    new_block,
                    resource_id,
                    new_block_time,
                    switch_counter,
                    index,
                    blocked_ips_history,
                    max_delay,
                    fallback_log,
                )

            else:
                logger.warning("No new IPs/hostnames — waiting before retrying...")
                time.sleep(2)
                return self.recursive_fallback(
                    hostname,
                    v_link,
                    need_to_block,
                    resource_id,
                    block_time,
                    switch_counter,
                    index,
                    blocked_ips_history,
                    max_delay,
                    fallback_log,
                )

        except KeyboardInterrupt:
            self.network.cleanup_ipconfig(blocked_ips_history, self.os_type)
            return
        except Exception as e:
            logger.warning(f"Error in recursive fallback: {e}")

    def is_resolved_vod(self, blocked_ips, v_link, resource_id):
        try:
            resolved_ips, hostname, _, _ = get_current_video_used_ips_w_resource_id(
                v_link, resource_id, self.selenium.driver
            )
            if not resolved_ips:
                return False, None, None
            blocked_set = {ipr.strip() for ipr in blocked_ips}
            new_set = {ipr.strip() for ipr in resolved_ips}

            new_ips = list(new_set - blocked_set)
            if new_ips:
                logger.info(f"Detected new IPs serving current video: {new_ips}")
                return True, hostname, new_ips
            else:
                logger.warning(
                    f"No new IPs detected; video still on blocked IPs: {blocked_ips}"
                )
                return False, hostname, None

        except KeyboardInterrupt:
            raise

        except Exception as e:
            logger.warning(f"Error while checking fallback resolution: {e}")
            return False, None, None


def main():
    session_id = get_session_id()
    measurer = VODFallbackMeasurer(session_id)

    measurer.measure()
