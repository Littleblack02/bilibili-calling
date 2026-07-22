import asyncio
import json
from pathlib import Path

from app.config import settings
from app.services.bilibili import BilibiliService
from app.services.profile.pagination import ProfileChannelAdapter


SUPPORTED = {
    "favorites", "bangumi", "cinema", "history", "watchlater", "followings",
    "special_followings", "whisper_followings", "subscribed_tags",
    "favorite_collections", "favorite_topics", "favorite_articles",
    "favorite_courses", "favorite_notes", "courses", "fan_medals", "manga",
    "live_history", "dynamic_feed",
}


def _fixtures():
    path = Path(__file__).parent / "fixtures" / "profile_channels.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_declared_supported_channel_has_a_deidentified_contract_fixture():
    fixture = _fixtures()
    capabilities = BilibiliService.profile_channel_capabilities()
    assert set(capabilities["supported"]) == SUPPORTED
    assert set(fixture["channels"]) == SUPPORTED
    assert fixture["deidentified"] is True
    assert all(row["status"] == "working" for row in capabilities["supported"].values())
    assert all(row["status"] == "unavailable" for row in capabilities["unavailable"].values())

    adapter = ProfileChannelAdapter(item_paths=("data.items",))
    for channel, payload in fixture["channels"].items():
        page = adapter.adapt(payload)
        assert len(page.items) == 1, channel


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class PagingClient:
    def __init__(self):
        self.calls = []

    async def get(self, _url, params=None):
        self.calls.append(dict(params or {}))
        page = params["page_num"]
        count = 16 if page == 1 else 1
        return FakeResponse({"code": 0, "data": {
            "topic_list": [{"id": f"{page}-{index}"} for index in range(count)]
        }})

    async def aclose(self):
        return None


class CoreChannelClient:
    def __init__(self):
        self.calls = []

    async def get(self, url, params=None):
        params = dict(params or {})
        self.calls.append((url, params))
        if url.endswith("/x/space/bangumi/follow/list"):
            page = params["pn"]
            count = 20 if page == 1 else 1
            return FakeResponse({"code": 0, "data": {"list": [
                {"season_id": page * 100 + index, "media_id": page * 100 + index,
                 "title": f"season-{page}-{index}", "new_ep": {"index": 1}}
                for index in range(count)
            ]}})
        if url.endswith("/x/relation/followings"):
            page = params["pn"]
            count = 50 if page == 1 else 1
            return FakeResponse({"code": 0, "data": {"list": [
                {"mid": page * 100 + index, "uname": f"up-{page}-{index}"}
                for index in range(count)
            ], "total": 51}})
        if url.endswith("/x/v2/history/toview"):
            return FakeResponse({"code": 0, "data": {"list": []}})
        if url.endswith("/x/v2/history"):
            return FakeResponse({"code": -101, "message": "not logged in"})
        raise AssertionError(url)

    async def aclose(self):
        return None


def test_real_channel_method_collects_multiple_fixture_pages_and_records_status(monkeypatch):
    async def scenario():
        monkeypatch.setattr(settings, "profile_sync_v2_enabled", True)
        service = BilibiliService()
        service.client = PagingClient()
        items = await service.get_favorite_topics()
        assert len(items) == 17
        assert [call["page_num"] for call in service.client.calls] == [1, 2]
        status = service.profile_channel_statuses()["favorite_topics"]
        assert status["status"] == "success"
        assert status["page_count"] == 2
        assert status["full_snapshot"] is True
    asyncio.run(scenario())


def test_core_snapshot_channels_paginate_and_record_exhaustion(monkeypatch):
    async def scenario():
        monkeypatch.setattr(settings, "profile_sync_v2_enabled", True)
        service = BilibiliService()
        service.client = CoreChannelClient()

        bangumi = await service.get_user_bangumi(42)
        followings = await service.get_all_followings(42)

        assert len(bangumi) == 21
        assert len(followings) == 51
        statuses = service.profile_channel_statuses()
        assert statuses["bangumi"]["full_snapshot"] is True
        assert statuses["bangumi"]["page_count"] == 2
        assert statuses["followings"]["full_snapshot"] is True
        assert statuses["followings"]["page_count"] == 2

    asyncio.run(scenario())


def test_core_empty_snapshot_is_distinct_from_auth_failure(monkeypatch):
    async def scenario():
        monkeypatch.setattr(settings, "profile_sync_v2_enabled", True)
        service = BilibiliService()
        service.client = CoreChannelClient()

        assert await service.get_watchlater_list() == []
        assert await service.get_watch_history(pn=1, ps=10) == []

        statuses = service.profile_channel_statuses()
        assert statuses["watchlater"]["status"] == "success"
        assert statuses["watchlater"]["full_snapshot"] is True
        assert statuses["history"]["status"] == "auth_required"
        assert statuses["history"]["full_snapshot"] is False

    asyncio.run(scenario())


def test_auth_failure_stops_queued_same_account_channels(monkeypatch):
    async def scenario():
        monkeypatch.setattr(settings, "profile_sync_v2_enabled", True)
        service = BilibiliService()
        calls = []

        channels = [
            ("subscribed_tags", "get_subscribed_tags"),
            ("favorite_collections", "get_favorite_collections"),
            ("favorite_topics", "get_favorite_topics"),
            ("favorite_articles", "get_favorite_articles"),
            ("favorite_courses", "get_favorite_courses"),
            ("favorite_notes", "get_favorite_notes"),
            ("courses", "get_user_courses"),
            ("special_followings", "get_special_followings"),
            ("whisper_followings", "get_whisper_followings"),
            ("fan_medals", "get_fan_medals"),
            ("manga", "get_followed_manga"),
            ("live_history", "get_live_watch_history"),
            ("dynamic_feed", "get_dynamic_feed"),
        ]

        for index, (channel, method_name) in enumerate(channels):
            async def fake(*_args, _index=index, _channel=channel):
                calls.append(_channel)
                if _index == 0:
                    service._record_profile_channel_status(
                        _channel, status="auth_required",
                        capability_status="auth_required",
                        error_summary="expired test credential",
                    )
                else:
                    service._record_profile_channel_status(
                        _channel, status="success", capability_status="working",
                        full_snapshot=True,
                    )
                return []
            monkeypatch.setattr(service, method_name, fake)

        await service.get_extended_profile_channels(42)
        statuses = service.profile_channel_statuses()
        assert len(calls) <= 4
        assert statuses["subscribed_tags"]["status"] == "auth_required"
        assert all(channel in statuses for channel, _method in channels)
        assert sum(
            row["status"] == "auth_required" for row in statuses.values()
        ) >= len(channels) - 3

    asyncio.run(scenario())
