"""Repeat video-on-demand fallback trials for each discovered video."""

import json
import logging

from measure_tiktok.config import get_os_type, get_session_id
from measure_tiktok.fallback.browser import SeleniumController
from measure_tiktok.fallback.network import NetworkController
from measure_tiktok.storage.postgres import PostgresDB
from measure_tiktok.utils.common import (
    get_uuid_timestamp,
    init_timezone,
)
from measure_tiktok.utils.video import (
    get_current_video_used_ips,
    get_current_video_used_ips_w_resource_id,
)

logger = logging.getLogger(__name__)


class IterativeVODFallbackMeasurer:
    """Repeat the initial fallback measurement across VOD trials."""

    def __init__(self, session_id):
        self.session_id = session_id
        self.selenium = SeleniumController(session_id)
        self.network = NetworkController(self.selenium)
        self.crawler_timestamp = None
        self.db = None
        self.os_type = get_os_type()
        init_timezone()

    def write_into_db(self, data_entry):
        insert_query = """
            INSERT INTO video_fallback_mechanism_vod_iterative (
                video_link,
                resource_id,
                start_time,
                fallback_logs,
                whole_fallback_delay,
                index
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (video_link, start_time) 
            DO NOTHING;
        """

        data = (
            data_entry["video_link"],
            data_entry["resource_id"],
            data_entry["start_time"],
            data_entry["fallback_logs"],
            data_entry["whole_fallback_delay"],
            data_entry["index"],
        )

        try:
            self.db.insert(insert_query, data)
        except Exception as e:
            logger.warning(f"Error inserting data into the database: {e}")

    def measure(self, max_delay=300000):
        try:
            video_links = self.selenium.scrape_vod_links()
            iteration_times = 30
            for v_link in video_links[:10]:
                logger.info(f"\n=== Processing vod: {v_link} ===")
                self.crawler_timestamp = get_uuid_timestamp()
                self.start_fallback_logic(v_link, iteration_times, max_delay=max_delay)
        except Exception as e:
            logger.warning(f"Error in measure: {e}")
            return
        finally:
            try:
                self.selenium.cleanup_driver()
            except Exception as e:
                logger.warning(f"Failed to close Selenium browser: {e}")

    def start_fallback_logic(self, v_link, iteration_times=10, max_delay=300000):
        self.db = PostgresDB()
        for index in range(iteration_times):
            logger.info(f"\n=== Processing vod: {v_link} in iteration: {index} ===")
            try:
                curr_ips, hostname, resource_id = get_current_video_used_ips(
                    v_link, self.selenium.driver
                )
                if not curr_ips:
                    logger.warning(f"No IPs found for {v_link}")
                    continue
                need_to_block = list(set(curr_ips))
                if not need_to_block:
                    logger.warning(f"No IPs found to block for {hostname}")
                    continue

                rule = self.network.create_block_rule(need_to_block, self.os_type)
                block_time = self.network.block_ips_by_rule(rule, self.os_type)
                start_time = get_uuid_timestamp()
                fallback_logs = self.recursive_fallback(
                    hostname,
                    v_link,
                    need_to_block,
                    resource_id,
                    block_time,
                    need_to_block,
                    start_time,
                    max_delay,
                )
                end_time = get_uuid_timestamp()
                if not fallback_logs:
                    continue

                resource_id = fallback_logs[0].get("resource_id")
                data_entry = {
                    "video_link": v_link,
                    "resource_id": resource_id,
                    "start_time": start_time,
                    "fallback_logs": json.dumps(fallback_logs),
                    "whole_fallback_delay": end_time - start_time,  # in ms
                    "index": index,
                    "source": 1,  # web
                    "stream_type": 1,  # vod,
                }
                self.write_into_db(data_entry)
                logger.info("written into db")

            except Exception as e:
                logger.warning(f"Error in fallback logic: {e}")
            finally:
                logger.info("Final cleanup...")
                if "need_to_block" in locals() and need_to_block:
                    try:
                        self.network.cleanup_ipconfig(need_to_block, self.os_type)
                    except Exception as e:
                        logger.warning(f"Final linux iptables cleanup failed: {e}")
        self.db.disconnect()

    def recursive_fallback(
        self,
        hostname,
        v_link,
        need_to_block,
        resource_id,
        block_time,
        blocked_ips_history,
        very_start_time,
        max_delay=None,
        fallback_logs=None,
    ):
        if get_uuid_timestamp() - block_time > max_delay:
            logger.warning(f"Timeout after {max_delay}ms — fallback not detected.")
            self.network.cleanup_ipconfig(blocked_ips_history, self.os_type)
            return fallback_logs
        if not fallback_logs:
            fallback_logs = []

        try:
            is_resolved, resolved_hostname, resolved_ips, x_cache = (
                self.is_resolved_vod(blocked_ips_history, v_link, resource_id)
            )
            logger.info(
                f"Current hostname: {hostname} | Resolved: {resolved_hostname} | resolved_ips: {resolved_ips} | resource_id: {resource_id}"
            )
            if is_resolved:
                fallback_delay = get_uuid_timestamp() - block_time
                if resolved_hostname != hostname:
                    logger.info(f"Fallback: {hostname} → {resolved_hostname}")
                    logger.info(
                        f"    ↳ Delay: {fallback_delay:.2f}ms | New IPs: {resolved_ips}"
                    )
                    fallback_logs.append(
                        {
                            "attempt_index": len(fallback_logs) + 1,
                            "elapsed": get_uuid_timestamp() - very_start_time,
                            "original_hostname": hostname,
                            "hostname": resolved_hostname,
                            "block_time": block_time,
                            "fallback_delay": fallback_delay,
                            "blocked_ips": need_to_block,
                            "new_ips": resolved_ips,
                            "resource_id": resource_id,
                            "x_cache": x_cache,
                            "is_switch": True,
                        }
                    )
                    return fallback_logs
                else:
                    logger.info(f"Fallback: {hostname} → {resolved_hostname}")
                    fallback_logs.append(
                        {
                            "attempt_index": len(fallback_logs) + 1,
                            "elapsed": get_uuid_timestamp() - very_start_time,
                            "original_hostname": hostname,
                            "hostname": resolved_hostname,
                            "block_time": block_time,
                            "fallback_delay": fallback_delay,
                            "blocked_ips": need_to_block,
                            "new_ips": resolved_ips,
                            "resource_id": resource_id,
                            "x_cache": x_cache,
                            "is_switch": False,
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
                        blocked_ips_history,
                        very_start_time,
                        max_delay,
                        fallback_logs,
                    )
            else:
                logger.warning("No new IPs/hostnames — waiting before retrying...")
                return self.recursive_fallback(
                    hostname,
                    v_link,
                    need_to_block,
                    resource_id,
                    block_time,
                    blocked_ips_history,
                    very_start_time,
                    max_delay,
                    fallback_logs,
                )

        except KeyboardInterrupt:
            self.network.cleanup_ipconfig(blocked_ips_history, self.os_type)
            return fallback_logs
        except Exception as e:
            logger.warning(f"Error in recursive fallback: {e}")
            return fallback_logs

    def is_resolved_vod(self, blocked_ips, v_link, resource_id):
        try:
            resolved_ips, hostname, _, x_cache = (
                get_current_video_used_ips_w_resource_id(
                    v_link, resource_id, self.selenium.driver
                )
            )
            if not resolved_ips:
                return False, None, None, None
            blocked_set = {ipr.strip() for ipr in blocked_ips}
            new_set = {ipr.strip() for ipr in resolved_ips}

            new_ips = list(new_set - blocked_set)
            if new_ips:
                logger.info(f"Detected new IPs serving current video: {new_ips}")
                return True, hostname, new_ips, x_cache
            else:
                logger.warning(
                    f"No new IPs detected; video still on blocked IPs: {blocked_ips}"
                )
                return False, hostname, None, None

        except KeyboardInterrupt:
            raise

        except Exception as e:
            logger.warning(
                f"Error while checking fallback resolution inside is_resolved_vod: {e}"
            )
            return False, None, None, None


def main():
    session_id = get_session_id()
    measurer = IterativeVODFallbackMeasurer(session_id)

    measurer.measure()
