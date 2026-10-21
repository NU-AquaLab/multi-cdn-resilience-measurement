"""Parse CDN responses, cookies, identifiers, and location metadata."""

import json
import logging
import random
import re
import socket
import subprocess
import time
from datetime import datetime
from urllib.parse import urlparse

import dns.resolver
import pytz
import requests
from selenium import webdriver

logger = logging.getLogger(__name__)

timezone = None
city = "Unknown"
region = "Unknown"
country = "Unknown"
download_video = False


def init_timezone():
    response = requests.get("https://ipinfo.io", timeout=15)
    data = response.json()

    timezone_str = data.get("timezone", None)
    if timezone_str is None:
        return

    # Account for daylight saving time at the measurement location.
    local_time = datetime.now(pytz.timezone(timezone_str))
    utc_offset = local_time.utcoffset().total_seconds() / 3600

    global timezone, city, region, country
    timezone = f"UTC{'+' if utc_offset >= 0 else '-'}{abs(int(utc_offset))}"
    city = data.get("city", "Unknown")
    region = data.get("region", "Unknown")
    country = data.get("country", "Unknown")
    logger.info(
        f"Timezone: {timezone}, city: {city}, region: {region}, country: {country}"
    )
    resolver = dns.resolver.Resolver()
    logger.info("%s %s", "System DNS Servers:", resolver.nameservers)


def is_valid_ip(ip):
    """Check if a string is a valid IPv4 address."""
    ipv4_pattern = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
    return bool(ipv4_pattern.match(ip))


def resolve_hostname_ips(hostname):
    """
    Resolve hostname to IP addresses using dig command
    """
    resolver = dns.resolver.Resolver()
    resolver.nameservers = ["8.8.8.8", "8.8.4.4"]  # override slow campus DNS

    try:
        answers = resolver.resolve(hostname, "A")
        ip_addresses = [rdata.address for rdata in answers]

        return ip_addresses
    except Exception as e:
        logger.warning(f"Error resolving IPs for {hostname}: {e}")

        return []


def parse_count(s):
    s = s.upper().replace(",", "")
    if "K" in s:
        return int(float(s.replace("K", "")) * 1_000)
    elif "M" in s:
        return int(float(s.replace("M", "")) * 1_000_000)
    else:
        return int(s)


def get_live_streaming_hashtag():
    hashtags = [
        "following",
        "gaming",
        "lifestyle",
        "gaming/Fortnite",
        "gaming/Tom_Clancy's_Rainbow_Six_Extraction",
        "gaming/Call_of_Duty",
        "gaming/FIFA_23",
        "gaming/PUBG_Mobile",
        "gaming/Grand_Theft_Auto_V",
        "gaming/Mobile_Legends:_Bang_Bang",
        "gaming/Marvel_Rivals",
        "gaming/Call_of_Duty:_Mobile",
        "gaming/Arena_Breakout",
        "gaming/Garena_Free_Fire",
        "gaming/Roblox",
        "gaming/Minecraft",
        "gaming/Clash_Royale",
        "gaming/Arena_of_Valor",
        "gaming/VALORANT",
        "gaming/Brawl_Stars",
        "gaming/eFootball_2023",
        "gaming/Counter-Strike",
        "gaming/League_of_Legends",
        "gaming/Knives_Out",
        "gaming/Rocket_League",
        "gaming/Metin2",
        "gaming/Dota_2",
        "gaming/Dead_by_Daylight",
        "gaming/Resident_Evil",
        "gaming/Apex_Legends",
        "gaming/Euro_Truck_Simulator_2",
        "gaming/Genshin_Impact",
        "gaming/World_of_Tanks",
    ]

    random_hashtag = random.choice(hashtags)
    return random_hashtag


def retrieve_stream_id(url: str):
    pattern = re.compile(r"stream-(\d+)_")
    match = pattern.search(url)
    if match:
        return match.group(1)
    return None


def retrieve_streaming_category(url: str):
    pattern = re.compile(r"https://[^/]+/([^/]+)/")

    match = pattern.search(url)
    category_value = match.group(1) if match else None
    return category_value


def modify_cookie(cookies, driver):
    for cookie in cookies:
        if "domain" in cookie and "tiktok.com" not in cookie["domain"]:
            logger.info("Skipping cookie outside the TikTok domain")
            continue  # Skip cookies with incorrect domain

        # Modify region-assignment cookies
        if cookie["name"] == "store-country-code":
            logger.info(
                f"Modifying store-country-code: {cookie['value']} → {country.lower()}"
            )
            cookie["value"] = country.lower()

        if cookie["name"] == "store-idc":
            logger.info(f"Modifying store-idc: {cookie['value']} → ''")
            cookie["value"] = ""

        if cookie["name"] == "tt-target-idc":
            logger.info(f"Modifying tt-target-idc: {cookie['value']} → ''")
            cookie["value"] = ""

        # Remove possible region-locking cookies
        if cookie["name"] in ["tt-target-idc-sign"]:
            logger.info(f"Removing {cookie['name']} to allow reassignment")
            continue  # Skip adding this cookie

        # Optionally regenerate session-related cookies
        if cookie["name"] in ["sid_tt", "sessionid"]:
            logger.info(
                f"Removing session cookie {cookie['name']} to force reassignment"
            )
            continue  # Skip session cookies to get a fresh region-assigned one

        try:
            cookie.pop(
                "domain", None
            )  # Remove domain field (Selenium sets it automatically)
            driver.add_cookie(cookie)
        except Exception as e:
            logger.warning(
                f"Error adding cookie {cookie.get('name', 'unknown')}: {type(e).__name__}"
            )

    logger.info("Modified cookies added successfully!")


def modify_live_cookie(cookies, driver):
    for cookie in cookies:
        if "domain" in cookie and "tiktok.com" not in cookie["domain"]:
            logger.info("Skipping cookie outside the TikTok domain")
            continue  # Skip cookies with incorrect domain

        # Modify region-assignment cookies
        if cookie["name"] == "store-country-code":
            logger.info(
                f"Modifying store-country-code: {cookie['value']} → {country.lower()}"
            )
            cookie["value"] = country.lower()

        try:
            cookie.pop(
                "domain", None
            )  # Remove domain field (Selenium sets it automatically)
            driver.add_cookie(cookie)
        except Exception as e:
            logger.warning(
                f"Error adding cookie {cookie.get('name', 'unknown')}: {type(e).__name__}"
            )

    logger.info("Modified live streaming cookies added successfully!")


def get_uuid_timestamp():
    return int(time.time() * 1000)  # use timezone to convert to crawling timestamp]


def convert_str_into_ip(ss: str):
    return ss.replace("-", ".")


def get_hostname(url: str):
    parsed_url = urlparse(url)
    host_name = parsed_url.hostname

    if host_name.startswith("www."):
        host_name = host_name[4:]

    return host_name


def resolve_host_name(url: str):
    host_name = get_hostname(url)
    ip = socket.gethostbyname(host_name)

    return ip


def extract_dc_value(url: str):
    match = re.search(r"/tos/([^/]+)/", url)
    if match:
        extracted_value = match.group(1)

        return extracted_value


def extract_ip_addresses(text):
    pattern = r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
    res = re.findall(pattern, text)
    if res:
        return res[0]
    else:
        return None


def extract_vid(url: str):
    match = re.search(r"__vid=TT-vCache-(\d+)", url)

    if match:
        video_id = match.group(1)
        logger.info("%s %s", "Extracted Video ID:", video_id)
        return video_id
    return None


def get_cname(hostname):
    result = subprocess.run(
        f"dig {hostname} | awk '/CNAME/ {{print $5}}'",
        shell=True,
        capture_output=True,
        text=True,
    )
    cname = result.stdout.strip()
    if cname:
        cname = cname.split()[-1]
        logger.info(cname)

    return cname if cname else None


def regular_expression_for_x_cache(cache: str):
    if not cache:
        return None
    pattern = r"(TCP_HIT|TCP_MISS|TCP_IMS_HIT|TCP_MEM_HIT|TCP_SWAPFAIL_MISS) from ([a-zA-Z0-9.-]+)"
    match = re.search(pattern, cache)

    if match:
        cache_status, server = match.groups()
        parts = server.split(".")
        return cache_status + "," + parts[0]
    else:
        return cache


def get_random_hashtag():
    hashtags = [
        "fyp",
        "viral",
        "trending",
        "tiktokmademebuyit",
        "dance",
        "funny",
        "challenge",
        "comedy",
        "fashion",
        "duet",
        "beauty",
        "prank",
        "music",
    ]

    random_hashtag = random.choice(hashtags)
    return random_hashtag


def extract_video_id(url: str, domain: str) -> str:
    if domain == "youtube.com":
        pattern = r"v=([^&]+)"
        match = re.search(pattern, url)
        if match:
            video_id = match.group(1)
            logger.info(f"Video ID: {video_id}")
            return video_id
        else:
            return get_uuid_timestamp()
    elif domain == "tiktok.com":
        path = urlparse(url).path
        video_id = path.split("/")[-1]
        return video_id
    elif domain == "bilibili.com":
        pattern = r"BV1[A-Za-z0-9]+"
        match = re.search(pattern, url)
        if match:
            video_id = match.group(0)
            logger.info(f"Video ID: {video_id}")
            return video_id
        else:
            return get_uuid_timestamp()


def extract_resource_id_in_cdn_url(url: str):
    parsed = urlparse(url)
    resource_id = parsed.path.rstrip("/").split("/")[-1]
    return resource_id


def collect_network_response(driver: webdriver, link: str):
    logger.info(f"video_link is {link}")
    driver.get(link)

    time.sleep(6)

    curr_vid = extract_video_id(link, "tiktok.com")
    log_entries = driver.get_log("performance")
    logs = [json.loads(entry["message"])["message"] for entry in log_entries]

    largest_video = None
    largest_size = 0

    for entry in logs:
        if entry["method"].startswith("Network.responseReceived"):
            if "type" not in entry["params"]:
                continue
            if entry["params"]["type"] not in ("Media", "Fetch", "XHR"):
                continue
            if "response" not in entry["params"]:
                continue
            if entry["params"]["response"]["mimeType"] != "video/mp4":
                continue
            if "mime_type=video_mp4" not in entry["params"]["response"]["url"]:
                continue

            if "content-length" in entry["params"]["response"]["headers"]:
                content_length = int(
                    entry["params"]["response"]["headers"]["content-length"]
                )
                if content_length > largest_size:
                    largest_size = content_length
                    largest_video = entry["params"]

    x_cache = None
    x_cache_remote = None
    x_parent_response = None
    x_origin_response = None
    if largest_video:
        if "X-Cache" in largest_video["response"]["headers"]:
            x_cache = largest_video["response"]["headers"]["X-Cache"]
        if "x-cache" in largest_video["response"]["headers"]:
            x_cache = largest_video["response"]["headers"]["x-cache"]
        if "x-cache-remote" in largest_video["response"]["headers"]:
            x_cache_remote = largest_video["response"]["headers"]["x-cache-remote"]
        if "X-Cache-Remote" in largest_video["response"]["headers"]:
            x_cache_remote = largest_video["response"]["headers"]["X-Cache-Remote"]
        if "X-Parent-Response-Time" in largest_video["response"]["headers"]:
            x_parent_response = largest_video["response"]["headers"][
                "X-Parent-Response-Time"
            ]
        if "x-parent-response-time" in largest_video["response"]["headers"]:
            x_parent_response = largest_video["response"]["headers"][
                "x-parent-response-time"
            ]
        if "X-Origin-Response-Time" in largest_video["response"]["headers"]:
            x_origin_response = largest_video["response"]["headers"][
                "X-Origin-Response-Time"
            ]
        if "x-origin-response-time" in largest_video["response"]["headers"]:
            x_origin_response = largest_video["response"]["headers"][
                "x-origin-response-time"
            ]
        if not x_cache:
            return None
        video_url = largest_video["response"]["url"]
        status = largest_video["response"]["status"]
        if not (200 <= status < 300):
            logger.warning(f"Video response status is not 2xx: {status}")
            return None
        if video_url.startswith("https://v19"):
            # dynamically resolve the host name
            resolved_ip = resolve_host_name(video_url)
            x_cache += ", " + resolved_ip
            logger.info(f"resolved_ip: {resolved_ip}")

        vid = extract_vid(video_url)
        filter_params = {
            "x-cache": regular_expression_for_x_cache(x_cache),
            "x-cache-remote": regular_expression_for_x_cache(x_cache_remote),
            "x-parent-response": x_parent_response,
            "x-origin-response": x_origin_response,
            "mimeType": "video/mp4",
            "timing": float(
                largest_video["response"]["timing"]["receiveHeadersEnd"]
                - largest_video["response"]["timing"]["connectEnd"]
            ),
            "url": largest_video["response"]["url"],
            "vid": vid or curr_vid,
            "statusText": largest_video["response"]["statusText"],
            "resource_id": extract_resource_id_in_cdn_url(video_url),
        }
        largest_video = filter_params
        logger.debug(f"found video_url in network logs: {x_cache}")

    return largest_video


def collect_network_response_vod_fallback(
    driver: webdriver, link: str, resource_id: str
):
    logger.info(f"video_link is {link}")
    driver.get(link)

    time.sleep(2)

    driver.get(link)

    time.sleep(3)

    log_entries = driver.get_log("performance")
    logs = [json.loads(entry["message"])["message"] for entry in log_entries]

    same_video = None
    x_cache = None

    curr_resource_id = ""
    for entry in logs:
        if entry["method"].startswith("Network.responseReceived"):
            if "type" not in entry["params"]:
                continue
            if (
                "response" in entry["params"]
                and entry["params"]["response"]["mimeType"] == "video/mp4"
            ):
                url = entry["params"]["response"]["url"]
                curr_resource_id = extract_resource_id_in_cdn_url(url)
                if curr_resource_id == resource_id:
                    logger.info(f"Found the same resource_id: {curr_resource_id}")
                    same_video = entry["params"]
                    break

    if same_video:
        video_url = same_video["response"]["url"]
        logger.debug(f"found video_url in network logs: {video_url}")
        status = same_video["response"]["status"]
        if not (200 <= status < 300):
            logger.warning(f"Video response status is not 2xx: {status}")
            return None
        if "X-Cache" in same_video["response"]["headers"]:
            x_cache = same_video["response"]["headers"]["X-Cache"]
        if "x-cache" in same_video["response"]["headers"]:
            x_cache = same_video["response"]["headers"]["x-cache"]

        filter_params = {
            "url": video_url,
            "resource_id": curr_resource_id,
            "x-cache": regular_expression_for_x_cache(x_cache),
        }
        same_video = filter_params

    return same_video


def collect_first_video_url(driver: webdriver, link: str):
    logger.info(f"video_link is {link}")
    driver.get(link)
    time.sleep(2)
    _ = driver.get_log("performance")  # Read & discard old logs
    driver.get(link)
    time.sleep(3)
    _ = driver.get_log("performance")  # Read & discard old logs
    driver.get(link)
    time.sleep(3)

    log_entries = driver.get_log("performance")
    logs = [json.loads(entry["message"])["message"] for entry in log_entries]

    for entry in logs:
        if entry["method"].startswith("Network.responseReceived"):
            if "type" not in entry["params"]:
                continue
            if (
                "response" in entry["params"]
                and entry["params"]["response"]["mimeType"] == "video/mp4"
            ):
                video_url = entry["params"]["response"]["url"]
                if "mime_type=video_mp4" not in video_url:
                    continue
                status = entry["params"]["response"]["status"]
                if not (200 <= status < 300):
                    logger.warning(f"Video response status is not 2xx: {status}")
                    continue
                if not video_url.startswith("https://v16") and not video_url.startswith(
                    "https://v19"
                ):
                    continue
                curr_resource_id = extract_resource_id_in_cdn_url(video_url)
                filter_params = {
                    "url": video_url,
                    "resource_id": curr_resource_id,
                }
                return filter_params


def collect_live_streaming_network_response(driver: webdriver, link: str):
    logger.info(f"live_streamingvideo_link is {link}")
    driver.get(link)

    time.sleep(5)
    _ = driver.get_log("performance")  # Read & discard old logs

    driver.get(link)

    time.sleep(5)

    log_entries = driver.get_log("performance")
    logs = [json.loads(entry["message"])["message"] for entry in log_entries]

    collected_logs = []
    streaming_urls = set()
    for entry in logs:
        if (
            entry["method"] == "Network.requestWillBeSent"
        ):  # Capturing outgoing requests
            try:
                request = entry["params"]["request"]
                if "postData" in request:  # Ensure there's POST data
                    post_data = json.loads(
                        request["postData"]
                    )  # Convert JSON string to dict

                    # Look for `cdn_play_url`
                    if isinstance(
                        post_data, list
                    ):  # Sometimes postData is a list of events
                        for item in post_data:
                            if "events" in item:
                                for event in item["events"]:
                                    if "params" in event and isinstance(
                                        event["params"], str
                                    ):
                                        try:
                                            params_data = json.loads(event["params"])
                                            if "cdn_play_url" in params_data:
                                                url = params_data["cdn_play_url"]
                                                streaming_urls.add(url)
                                                collected_logs.append(entry)
                                        except json.JSONDecodeError:
                                            continue
            except (KeyError, json.JSONDecodeError):
                continue

    if streaming_urls:
        logger.debug(f"Found Streaming URLs: {streaming_urls}")

    filter_params = []
    stream_ids = set()
    for streaming_url in streaming_urls:
        stream_id = retrieve_stream_id(streaming_url)
        if stream_id in stream_ids:
            continue
        stream_ids.add(stream_id)
        stream_category = retrieve_streaming_category(streaming_url)
        tmp = {
            "mimeType": "video/x-flv",
            "timing": 0.0,
            "cdn_url": streaming_url,
            "stream_id": stream_id,
            "stream_category": stream_category,
            "cdn_servers": resolve_hostname_ips(get_hostname(streaming_url)),
        }
        filter_params.append(tmp)

    if len(filter_params) != 1:
        return None

    return filter_params[0]


def format_time(timestamp):
    formatted = datetime.fromtimestamp(timestamp).strftime("%m%d%y-%H%M%S")
    return formatted
