"""Offline regressions for collection, persistence, and moved network helpers."""

import asyncio
import json
from unittest.mock import Mock

import pytest

from measure_tiktok.collectors.base import BaseUploader
from measure_tiktok.collectors.live import TikTokLiveCollector
from measure_tiktok.collectors.vod import TikTokVODCollector
from measure_tiktok.fallback import live
from measure_tiktok.fallback.network import NetworkController
from measure_tiktok.storage import postgres
from measure_tiktok.utils import common


def test_metadata_batches_do_not_drop_final_partial_batch():
    class Recorder(BaseUploader):
        def __init__(self):
            super().__init__()
            self.batches = []

        async def send(self, records):
            self.batches.append(records)

    async def run():
        uploader = Recorder()
        for index in range(27):
            await uploader.record({"index": index})
        await uploader.flush()
        return uploader

    uploader = asyncio.run(run())
    assert [len(batch) for batch in uploader.batches] == [25, 2]
    assert [row["index"] for batch in uploader.batches for row in batch] == list(
        range(27)
    )
    assert uploader.queue.empty()


def test_missing_cache_header_does_not_crash_fallback_parser(monkeypatch):
    driver = Mock()
    driver.get_log.return_value = [
        {
            "message": json.dumps(
                {
                    "message": {
                        "method": "Network.responseReceived",
                        "params": {
                            "type": "Media",
                            "response": {
                                "url": "https://cdn.example/video/resource-id/",
                                "mimeType": "video/mp4",
                                "status": 200,
                                "headers": {},
                            },
                        },
                    }
                }
            )
        }
    ]
    monkeypatch.setattr(common.time, "sleep", lambda _: None)
    result = common.collect_network_response_vod_fallback(
        driver, "https://example.com", "resource-id"
    )
    assert result["resource_id"] == "resource-id"
    assert result["x-cache"] is None


def test_extractor_failure_returns_empty_metadata(monkeypatch):
    collector = object.__new__(TikTokVODCollector)
    collector.download_options = {}
    monkeypatch.setattr(
        collector, "_download_video_sync", Mock(side_effect=RuntimeError("failed"))
    )
    assert asyncio.run(collector.download_video("https://example.com", {})) == {}


def test_live_browser_is_closed_if_login_setup_fails(monkeypatch):
    from measure_tiktok.collectors import live as collector_module

    collector = object.__new__(TikTokLiveCollector)
    driver = Mock()
    driver.execute_cdp_cmd.side_effect = RuntimeError("browser failed")
    monkeypatch.setattr(collector_module.webdriver, "Chrome", Mock(return_value=driver))
    with pytest.raises(RuntimeError, match="browser failed"):
        asyncio.run(collector.get_video_list("", 10))
    driver.quit.assert_called_once()


@pytest.mark.parametrize("enabled", [False, True])
def test_live_fallback_database_writes_remain_opt_in(monkeypatch, enabled):
    db = Mock()
    connect = Mock(return_value=db)
    monkeypatch.setattr(live, "PostgresDB", connect)
    monkeypatch.setattr(live, "init_timezone", lambda: None)
    monkeypatch.setenv("LIVE_FALLBACK_WRITE_DB", "1" if enabled else "0")
    measurer = object.__new__(live.LiveFallbackMeasurer)
    measurer.write_into_db(
        "room",
        1,
        2,
        "gaming",
        "1K",
        1,
        ["192.0.2.1"],
        ["192.0.2.2"],
        "a.example",
        "b.example",
    )
    if enabled:
        db.insert.assert_called_once()
        assert db.insert.call_args.args[1][4] == 1000
        db.disconnect.assert_called_once()
    else:
        connect.assert_not_called()


def test_database_reads_config_when_connecting_and_propagates_failure(monkeypatch):
    monkeypatch.setenv("DB_NAME", "test_database")
    connect = Mock(side_effect=RuntimeError("cannot connect"))
    monkeypatch.setattr(postgres.psycopg2, "connect", connect)
    with pytest.raises(RuntimeError, match="cannot connect"):
        postgres.PostgresDB()
    assert connect.call_args.kwargs["dbname"] == "test_database"


@pytest.mark.parametrize(
    "platform,expected",
    [
        ("linux", "iptables -A OUTPUT -d 192.0.2.1 -j DROP\n"),
        ("mac", "block drop out quick to 192.0.2.1\n"),
    ],
)
def test_firewall_rule_generation_preserved_without_applying_rules(platform, expected):
    controller = object.__new__(NetworkController)
    assert controller.create_block_rule(["192.0.2.1"], platform) == expected
