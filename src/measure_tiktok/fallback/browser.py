"""Discover TikTok content and inspect Chrome performance logs."""

import json
import logging
import os
import pickle
import random
import re
import time
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from measure_tiktok.config import get_cookie_path, get_output_dir, load_live_categories
from measure_tiktok.utils.common import (
    format_time,
    modify_cookie,
)

logger = logging.getLogger(__name__)


class SeleniumController:
    """Manage a Chrome session used by fallback experiments."""

    def __init__(self, session_id):
        self.driver = self.init_driver(session_id)

    def init_driver(self, session_id):
        """
        Initialize driver by opening Chrome, opening TikTok and adding session cookie
        """

        logger.info("Initializing Selenium browser connection...")

        options = webdriver.ChromeOptions()
        if binary := os.getenv("CHROME_BINARY"):
            options.binary_location = binary
        options.add_argument("--window-size=1280,720")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")  # Required for root environments
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        options.add_argument(
            "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )

        driver = webdriver.Chrome(options=options)
        driver.execute_cdp_cmd("Network.enable", {})

        driver.get("https://www.tiktok.com/")

        driver.add_cookie(
            {
                "name": "sessionid",
                "value": session_id,
                "domain": ".tiktok.com",
                "path": "/",
            }
        )

        return driver

    def enter_live_stream(self, room_id):
        """
        Enter live stream of {room_id}
        """
        logger.info("Navigating to live stream room...")
        _ = self.driver.get_log("performance")  # Read & discard old logs
        time.sleep(1)
        self.driver.get(f"https://www.tiktok.com/{room_id}/live")
        time.sleep(3)

    def get_log_entries(self):
        logger.info("Getting network log entries...")
        return self.driver.get_log("performance")

    def scrape_room_ids(self, category_path=None):
        """
        Iterate over categories, enter category page, scrape room IDs and save as JSON
        """
        logger.info("Scraping for room ids...")

        category_urls = load_live_categories(category_path)
        room_id_path = get_output_dir() / f"room_ids_{format_time(time.time())}.json"

        all_data = []
        logger.info(f"Number of category URLs: {len(category_urls)}")

        for url in random.sample(category_urls, min(5, len(category_urls))):
            logger.info(f"Scraping room id from: {url}")
            self.driver.get(url)
            time.sleep(10)
            room_ids = set()

            try:
                category = urlparse(url).path.split("/category/")[-1].strip("/")
            except Exception:
                category = "unknown"

            try:
                elements = self.driver.find_elements(
                    By.CSS_SELECTOR, "a[href*='/@'][href*='/live']"
                )
                for el in elements:
                    href = el.get_attribute("href")
                    logger.info(f"Found href: {href}")
                    if href and "/@" in href:
                        room_id = href.split("/")[-1]
                        if not room_id.startswith("@"):
                            room_id = href.split("/")[-2]
                        room_ids.add(room_id)
                logger.info(f"Found room IDs: {room_ids}")
            except Exception as e:
                logger.warning(f"Failed to scrape room IDs: {e}")

            usernames_records = [
                {"id": uname, "category": category} for uname in sorted(room_ids)
            ]

            try:
                existing_data = []
                if os.path.exists(room_id_path):
                    with open(room_id_path) as f:
                        existing_data = json.load(f)
                        if not isinstance(existing_data, list):
                            existing_data = []

                # Merge while avoiding duplicates by "id + category"
                existing_ids = {(d["id"], d["category"]) for d in existing_data}
                new_records = [
                    record
                    for record in usernames_records
                    if (record["id"], record["category"]) not in existing_ids
                ]
                all_data = existing_data + new_records

                random.shuffle(all_data)

                with open(room_id_path, "w") as f:
                    json.dump(all_data, f, indent=2)
                logger.info(f"Saved room IDs to {room_id_path}")
            except Exception as e:
                logger.warning(f"Failed to write usernames to {room_id_path}: {e}")

        return all_data

    def cleanup_driver(self):
        logger.info("Closing Selenium browser...")
        try:
            if self.driver:
                self.driver.quit()
                logger.info("Closed Selenium browser.")
        except Exception as e:
            logger.warning(f"Failed to close browser: {e}")

    def scrape_viewer_count(
        self, viewer_count_selector='//div[@data-e2e="live-people-count"]'
    ):
        logger.info("Scraping viewer count...")
        try:
            element = self.driver.find_element(By.XPATH, viewer_count_selector)
            viewer_count = element.text.strip()
            logger.info(f"Viewer Count: {viewer_count}")
        except Exception as e:
            logger.warning(f"Viewer count not found: {e}")
            return 0
        return viewer_count

    def get_curr_stream_request(self, room_id):
        """
        Find HTTP requests that contain TikTok stream video URL,
        and filter those with matching responses with status 200
        """

        log_entries = self.driver.get_log("performance")
        logs = [json.loads(entry["message"])["message"] for entry in log_entries]

        candidate_requests = []

        for entry in logs:
            if entry["method"] == "Network.requestWillBeSent":
                try:
                    request = entry["params"]["request"]
                    request_id = entry["params"]["requestId"]
                    if "postData" in request:
                        post_data = json.loads(request["postData"])
                        if isinstance(post_data, list):
                            for item in post_data:
                                if "events" in item:
                                    for event in item["events"]:
                                        if "params" in event and isinstance(
                                            event["params"], str
                                        ):
                                            try:
                                                params_data = json.loads(
                                                    event["params"]
                                                )
                                                if "cdn_play_url" in params_data:
                                                    url = params_data["cdn_play_url"]
                                                    candidate_requests.append(
                                                        (request_id, url)
                                                    )
                                            except json.JSONDecodeError:
                                                continue
                except (KeyError, json.JSONDecodeError):
                    continue

        if not candidate_requests:
            logger.warning("Stream request URL not found")
            return None, None

        successful_stream_url = None
        for entry in logs:
            if entry["method"] == "Network.responseReceived":
                try:
                    response = entry["params"]["response"]
                    request_id = entry["params"]["requestId"]

                    if response.get("status") == 200:
                        for cand_id, url in candidate_requests:
                            if cand_id == request_id:
                                successful_stream_url = url
                                break
                except KeyError:
                    continue
            if successful_stream_url:
                break

        if not successful_stream_url:
            logger.warning("Stream response not found")
            return None, None

        parsed = urlparse(successful_stream_url)
        hostname = parsed.hostname
        match = re.search(r"stream-(\d+)", parsed.path)
        stream_id = match.group(1) if match else None

        logger.info("Found current stream:")
        logger.info(f"Hostname: {hostname}, Stream ID: {stream_id}")

        return hostname, stream_id

    def scrape_vod_links(self):
        logger.info("Scraping VOD...")
        # override existing cookies since it's different from live stream
        self.driver.delete_all_cookies()
        self.driver.get("https://www.tiktok.com/login")

        with get_cookie_path().open("rb") as f:
            cookies = pickle.load(f)
        modify_cookie(cookies, self.driver)

        # Refresh to apply cookies and bypass login
        self.driver.refresh()
        time.sleep(2)

        logger.info("Logged in using saved cookies!")

        url = "https://www.tiktok.com/explore"
        self.driver.get(url)
        time.sleep(3)
        for _ in range(30):  # Adjust the range for more scrolls
            self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.PAGE_DOWN)
            time.sleep(random.uniform(2, 3))

        video_elements = self.driver.find_elements(
            By.CSS_SELECTOR, "a[href*='/video/']"
        )
        video_links = [element.get_attribute("href") for element in video_elements]

        video_links = list(set(video_links))
        video_links = video_links[: min(len(video_links), 50)]
        logger.info(len(video_links))

        return video_links
