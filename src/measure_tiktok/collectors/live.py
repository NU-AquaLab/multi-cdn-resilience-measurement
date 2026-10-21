"""Collect TikTok live-stream metadata and CDN responses."""

import asyncio
import logging
import os
import pickle
import random
import time

import yt_dlp
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

import measure_tiktok.utils.common as util
from measure_tiktok.collectors.base import BaseDownloader
from measure_tiktok.config import get_cookie_path
from measure_tiktok.utils.common import (
    collect_live_streaming_network_response,
    download_video,
    get_hostname,
    get_live_streaming_hashtag,
    modify_live_cookie,
)

logger = logging.getLogger(__name__)


class TikTokLiveCollector(BaseDownloader):
    """Discover live streams and combine browser and yt-dlp metadata."""

    def __init__(self):
        super().__init__()
        self.download_options = {
            "quiet": True,
            "ignoreerrors": True,
        }

    async def get_video_list(
        self, search_tag: str, max_count: int
    ) -> tuple[list[str], dict[str, dict]]:
        options = webdriver.ChromeOptions()
        if binary := os.getenv("CHROME_BINARY"):
            options.binary_location = binary
        options.add_argument("--window-size=1280,720")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")  # Required for root environments'
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        options.add_argument(
            "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )

        driver = webdriver.Chrome(options=options)
        try:
            driver.execute_cdp_cmd("Network.enable", {})

            # Open TikTok login page
            driver.get("https://www.tiktok.com/login")

            with get_cookie_path().open("rb") as f:
                cookies = pickle.load(f)

            modify_live_cookie(cookies, driver)

            # Refresh to apply cookies and bypass login
            driver.refresh()
            time.sleep(5)

            logger.info("Logged in using saved cookies!")

            hashtag = get_live_streaming_hashtag()
            url = f"https://www.tiktok.com/live/{hashtag}"
            logger.info(f"Searching for live streams with url: {url}")
            driver.get(url)

            time.sleep(5)
            for _ in range(30):  # Adjust the range for more scrolls
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.PAGE_DOWN)
                time.sleep(random.uniform(2, 3))

            live_users = set()
            elements = driver.find_elements(
                By.CSS_SELECTOR, "a[href*='/@'][href*='/live']"
            )
            for element in elements:
                link = element.get_attribute("href")
                if "/live" in link:
                    username = link.split("/@")[-1].split("/")[0]  # Extract username
                    live_users.add(username)

            live_users = list(live_users)
            composed_live_streaming_urls = []
            for user in live_users:
                ls_url = f"https://www.tiktok.com/@{user}/live"
                composed_live_streaming_urls.append(ls_url)

            logger.debug(composed_live_streaming_urls)

            vlink_cdn_map = {}
            for v_link in composed_live_streaming_urls:
                cdn_info = collect_live_streaming_network_response(driver, v_link)
                if not cdn_info:
                    continue
                vlink_cdn_map[v_link] = cdn_info

            return composed_live_streaming_urls, vlink_cdn_map
        finally:
            driver.quit()

    async def download_video(self, video_url: str, cdn_info: dict) -> dict:
        video_downloader = yt_dlp.YoutubeDL(self.download_options)
        info_dict = await asyncio.to_thread(
            self._download_video_sync, video_downloader, video_url
        )
        info_dict = video_downloader.sanitize_info(info_dict)

        if info_dict is None:
            return {}

        info = {
            # Content metadata.
            "stream_id": cdn_info["stream_id"],
            "uploader_id": (
                info_dict["uploader_id"] if "uploader_id" in info_dict else None
            ),
            "title": info_dict["title"] if "title" in info_dict else None,
            "stream_epoch": info_dict["epoch"] if "epoch" in info_dict else None,
            "concurrent_view_count": (
                info_dict["concurrent_view_count"]
                if "concurrent_view_count" in info_dict
                else None
            ),
            "webpage_url": (
                info_dict["webpage_url"] if "webpage_url" in info_dict else None
            ),
            "original_url": (
                info_dict["url"] if "url" in info_dict else None
            ),  # this points to cdn url,
            "webpage_url_domain": (
                info_dict["webpage_url_domain"]
                if "webpage_url_domain" in info_dict
                else None
            ),
            # Media format.
            "ext": info_dict["ext"] if "ext" in info_dict else None,
            "vcodec": info_dict["vcodec"] if "vcodec" in info_dict else None,
            "format_id": info_dict["format_id"] if "format_id" in info_dict else None,
            "tbr": info_dict["tbr"] if "tbr" in info_dict else None,
            "dynamic_range": (
                info_dict["dynamic_range"] if "dynamic_range" in info_dict else None
            ),
            # Measurement location.
            "timezone": util.timezone,
            "city": util.city,
            "region": util.region,
            "country_code": util.country,
            # CDN response metadata.
            "network-cdn-url": cdn_info["cdn_url"],
            "cdn_host_name": get_hostname(cdn_info["cdn_url"]),
            "cdn_servers": cdn_info["cdn_servers"],
            "stream_category": cdn_info["stream_category"],
            "source": 1,
            "stream_type": 2,
        }

        return info

    @staticmethod
    def _download_video_sync(
        video_downloader: yt_dlp.YoutubeDL, video_url: str
    ) -> dict:
        logger.debug(f"current_url: {video_url}")
        try:
            with video_downloader as ydl:
                return ydl.extract_info(video_url, download=download_video)
        except Exception as e:
            logger.warning(f"Error downloading video: {e}")
            return None
