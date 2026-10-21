"""Collect TikTok VOD metadata and browser CDN responses."""

import asyncio
import logging
import os
import pickle
import random
import time

import yt_dlp
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

import measure_tiktok.utils.common as util
from measure_tiktok.collectors.base import BaseDownloader
from measure_tiktok.config import get_cookie_path
from measure_tiktok.utils.common import (
    collect_network_response,
    download_video,
    modify_cookie,
)

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
)
ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
# Avoid headers that trigger cross-origin preflight requests.
SAFE_EXTRA_HEADERS = {
    "accept": ACCEPT,
    "accept-language": "en-US,en;q=0.9",
    "sec-ch-ua": '"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"',
    "sec-ch-ua-platform": '"macOS"',
}


class TikTokVODCollector(BaseDownloader):
    """Discover VOD links and combine browser and yt-dlp metadata."""

    def __init__(self):
        super().__init__()
        self.download_options = {
            "quiet": True,
            "ignoreerrors": True,
        }

    async def get_video_list(
        self, search_tag: str, max_count: int = 10
    ) -> tuple[list[str], dict[str, dict]]:
        options = Options()
        if binary := os.getenv("CHROME_BINARY"):
            options.binary_location = binary
        options.add_argument("--window-size=1280,720")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        # Interactive login needs a visible browser.
        if os.getenv("HEADLESS", "0") == "1":
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--incognito")
        options.add_argument(f"--user-agent={USER_AGENT}")
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

        driver = webdriver.Chrome(options=options)

        try:
            # Capture network events without adding preflight-triggering headers.
            driver.execute_cdp_cmd("Network.enable", {})
            driver.execute_cdp_cmd("Network.setCacheDisabled", {"cacheDisabled": True})
            driver.execute_cdp_cmd(
                "Network.setExtraHTTPHeaders", {"headers": SAFE_EXTRA_HEADERS}
            )

            # Apply browser compatibility overrides before loading page scripts.
            stealth_js = r"""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            """
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument", {"source": stealth_js}
            )

            # Strip cache-control and pragma headers to avoid CORS preflight requests.
            patch_fetch_xhr = r"""
            (function() {
              const origFetch = window.fetch;
              window.fetch = function(resource, init) {
                if (init && init.headers) {
                  try {
                    if (init.headers instanceof Headers) {
                      init.headers.delete('cache-control');
                      init.headers.delete('pragma');
                    } else {
                      const fixed = {};
                      for (const [k,v] of Object.entries(init.headers)) {
                        if (k.toLowerCase() !== 'cache-control' && k.toLowerCase() !== 'pragma') {
                          fixed[k] = v;
                        }
                      }
                      init.headers = fixed;
                    }
                  } catch(e){}
                }
                if (!init) init = {};
                if (!('cache' in init)) init.cache = 'no-store';
                return origFetch.call(this, resource, init);
              };

              const origOpen = XMLHttpRequest.prototype.open;
              XMLHttpRequest.prototype.open = function() {
                this.__suppress = true;
                return origOpen.apply(this, arguments);
              };
              const origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
              XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
                if (this.__suppress && ['cache-control','pragma'].includes(String(name).toLowerCase())) {
                  return;
                }
                return origSetHeader.apply(this, arguments);
              };
            })();
            """
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument", {"source": patch_fetch_xhr}
            )

            driver.get(
                "https://www.tiktok.com/"
            )  # must be on domain before adding cookies/localStorage
            time.sleep(1)

            # Open TikTok login page
            driver.get("https://www.tiktok.com/login")
            # Wait for manual login (solve CAPTCHA if needed)
            input("Log in manually, then press Enter to continue...")

            # Save cookies after login
            get_cookie_path().parent.mkdir(parents=True, exist_ok=True)
            with get_cookie_path().open("wb") as f:
                pickle.dump(driver.get_cookies(), f)

            logger.info("Cookies saved! You can now use them for future sessions.")

            with get_cookie_path().open("rb") as f:
                cookies = pickle.load(f)
            modify_cookie(cookies, driver)

            # refresh to ensure logged-in state is applied
            driver.refresh()
            time.sleep(random.uniform(2, 3))
            logger.info("Logged in using saved session")

            url = "https://www.tiktok.com/explore"
            driver.get(url)
            time.sleep(random.uniform(2, 4))

            # Scroll to load additional videos.
            for _ in range(random.randint(4, 8)):
                driver.find_element(By.TAG_NAME, "body").send_keys(Keys.PAGE_DOWN)
                time.sleep(random.uniform(1.1, 2.8))

            video_elements = driver.find_elements(By.CSS_SELECTOR, "a[href*='/video/']")
            video_links = [
                e.get_attribute("href")
                for e in video_elements
                if e.get_attribute("href")
            ]
            video_links = list(dict.fromkeys(video_links))  # dedupe & preserve order
            max_count = min(30, len(video_links))
            video_links = video_links[:max_count]
            logger.info(f"Found {len(video_links)} video links on explore page")

            vlink_cdn_map = {}
            for v_link in video_links:
                try:
                    cdn_info = collect_network_response(driver, v_link)
                    if cdn_info:
                        vlink_cdn_map[v_link] = cdn_info
                    time.sleep(random.uniform(0.8, 1.8))
                except Exception as e:
                    logger.warning("%s %s", "Error collecting network response:", e)
                    continue

            return video_links, vlink_cdn_map

        finally:
            driver.quit()

    async def download_video(self, video_url: str, cdn_info: dict) -> dict:
        try:
            video_downloader = yt_dlp.YoutubeDL(self.download_options)
            info_dict = await asyncio.to_thread(
                self._download_video_sync, video_downloader, video_url
            )
            info_dict = video_downloader.sanitize_info(info_dict)
        except Exception as e:
            logger.warning("Video metadata extraction failed: %s", e)
            return {}

        if info_dict is None:
            info_dict = {}

        info = {
            # Content metadata.
            "uploader_id": (
                info_dict["uploader_id"] if "uploader_id" in info_dict else None
            ),
            "duration": info_dict["duration"] if "duration" in info_dict else None,
            "title": info_dict["title"] if "title" in info_dict else None,
            "upload_timestamp": (
                info_dict["timestamp"] if "timestamp" in info_dict else None
            ),
            "view_count": (
                info_dict["view_count"] if "view_count" in info_dict else None
            ),
            "like_count": (
                info_dict["like_count"] if "like_count" in info_dict else None
            ),
            "comment_count": (
                info_dict["comment_count"] if "comment_count" in info_dict else None
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
            "upload_date": (
                info_dict["upload_date"] if "upload_date" in info_dict else None
            ),
            # Media format.
            "ext": info_dict["ext"] if "ext" in info_dict else None,
            "vcodec": info_dict["vcodec"] if "vcodec" in info_dict else None,
            "acodec": info_dict["acodec"] if "acodec" in info_dict else None,
            "format_id": info_dict["format_id"] if "format_id" in info_dict else None,
            "tbr": info_dict["tbr"] if "tbr" in info_dict else None,
            "filesize": info_dict["filesize"] if "filesize" in info_dict else None,
            "width": info_dict["width"] if "width" in info_dict else None,
            "height": info_dict["height"] if "height" in info_dict else None,
            "fps": None,
            "dynamic_range": (
                info_dict["dynamic_range"] if "dynamic_range" in info_dict else None
            ),
            # Measurement location.
            "timezone": util.timezone,
            "city": util.city,
            "region": util.region,
            "country_code": util.country,
            # CDN response metadata.
            "x-cache": cdn_info["x-cache"],
            "x-cache-remote": cdn_info["x-cache-remote"],
            "x-parent-response": cdn_info["x-parent-response"],
            "x-origin-response": cdn_info["x-origin-response"],
            "timing": cdn_info["timing"],
            "network-cdn-url": cdn_info["url"],
            "cname": None,
            "source": 1,
            "stream_type": 1,
        }

        return info

    @staticmethod
    def _download_video_sync(
        video_downloader: yt_dlp.YoutubeDL, video_url: str
    ) -> dict:
        with video_downloader as ydl:
            return ydl.extract_info(video_url, download=download_video)
