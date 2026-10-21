"""Look up the delivery IPs and resource IDs of browser video requests."""

import logging
import subprocess
import time

from measure_tiktok.utils.common import (
    collect_first_video_url,
    collect_network_response_vod_fallback,
    get_hostname,
    resolve_hostname_ips,
)

logger = logging.getLogger(__name__)


def get_current_video_used_ips(v_link, driver):
    video_cdn_info = collect_first_video_url(driver, v_link)
    if not video_cdn_info:
        return [], None, None
    video_cdn_url = video_cdn_info["url"]
    resource_id = video_cdn_info["resource_id"]
    hostname = get_hostname(video_cdn_url)
    curr_ips = resolve_hostname_ips(hostname)
    logger.debug(f"current video with url: {video_cdn_url} and {resource_id}")
    return curr_ips, hostname, resource_id


def get_current_video_used_ips_w_resource_id(v_link, resource_id, driver):
    video_cdn_info = collect_network_response_vod_fallback(driver, v_link, resource_id)
    if not video_cdn_info:
        return None, None, None, None
    video_cdn_url = video_cdn_info["url"]
    resource_id = video_cdn_info["resource_id"]
    hostname = get_hostname(video_cdn_url)
    curr_ips = resolve_hostname_ips(hostname)
    x_cache = video_cdn_info["x-cache"]
    return curr_ips, hostname, resource_id, x_cache


def flush_dns_cache():
    try:
        logger.info("Flushing DNS cache...")
        subprocess.run(["sudo", "resolvectl", "flush-caches"], check=True)
        logger.info("DNS cache flushed")
        time.sleep(5)
    except subprocess.CalledProcessError as e:
        logger.warning(f"Error resetting network: {e}")


def get_country_to_continents():
    return {
        "US": "North America",
        "MX": "North America",
        "CA": "North America",
        "DE": "Europe",
        "DK": "Europe",
        "FR": "Europe",
        "ES": "Europe",
        "GB": "Europe",
        "PL": "Europe",
        "NL": "Europe",
        "BE": "Europe",
        "SE": "Europe",
        "GR": "Europe",
        "HU": "Europe",
        "PT": "Europe",
        "IE": "Europe",
        "CH": "Europe",
        "NO": "Europe",
        "FI": "Europe",
        "JP": "Asia",
        "SG": "Asia",
        "MY": "Asia",
        "KR": "Asia",
        "AE": "Asia",
        "AU": "Oceania",
        "NZ": "Oceania",
        "AR": "South America",
        "PE": "South America",
        "CL": "South America",
        "ZA": "Africa",
    }


def get_country_codes():
    return [
        "US",
        "MX",
        "DE",
        "GB",
        "FR",
        "ES",
        "JP",
        "MY",
        "AR",
        "PE",
        "CA",
        "PL",
        "AU",
        "CL",
        "KR",
        "NL",
        "ZA",
        "SG",
        "BE",
        "SE",
        "GR",
        "HU",
        "PT",
        "IE",
        "AE",
        "CH",
        "NO",
        "NZ",
        "FI",
        "DK",
    ]
