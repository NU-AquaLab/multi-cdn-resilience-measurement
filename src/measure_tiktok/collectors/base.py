"""Coordinate asynchronous metadata collection and batched uploads."""

import asyncio
import logging

from measure_tiktok.utils import common as util

logger = logging.getLogger(__name__)


class BaseUploader:
    """Buffer metadata records and send them in batches."""

    def __init__(self):
        self.queue = asyncio.Queue()

    async def flush(self):
        count = 25
        while not self.queue.empty():
            info_list = []
            for _ in range(count):
                try:
                    item = self.queue.get_nowait()
                    info_list.append(item)
                    self.queue.task_done()
                except asyncio.QueueEmpty:
                    break
            if info_list:
                await self.send(info_list)

    async def send(self, info: list[dict]):
        raise NotImplementedError

    async def record(self, info: dict):
        await self.queue.put(info)


class BaseDownloader:
    """Coordinate discovery, metadata extraction, and registered uploaders."""

    def __init__(self):
        util.init_timezone()
        self.uploaders: list[BaseUploader] = []

    def register_uploader(self, uploader: BaseUploader):
        self.uploaders.append(uploader)

    async def run(self):
        video_list, har_log = await self.get_video_list("", 50)
        try:
            tasks = [
                self.download_and_upload(url, har_log[url])
                for url in video_list
                if url in har_log
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    logger.warning(f"Task {i} failed: {res}")
        except Exception as e:
            logger.warning(f"Error in download_and_upload: {e}")

        for uploader in self.uploaders:
            if hasattr(uploader, "flush"):
                await uploader.flush()  # explicit flush at the end

    async def download_and_upload(self, video_url: str, har_log: dict):
        info = await self.download_video(video_url, har_log)
        upload_tasks = [uploader.record(info) for uploader in self.uploaders]
        await asyncio.gather(*upload_tasks)

    async def get_video_list(
        self, search_tag: str, max_count: int
    ) -> tuple[list[str], dict[str, dict]]:
        raise NotImplementedError

    async def download_video(self, video_url: str, har_log: dict) -> dict:
        raise NotImplementedError
