import asyncio

from app.services.bilibili import BilibiliService
from app.services.recommendation.candidate_recalls import CandidateRecall, duration_seconds
from app.services.recommendation.recall_calibration import calibrate_recall_candidates


def test_duration_normalization_handles_bilibili_search_format():
    assert duration_seconds("12:34") == 754
    assert duration_seconds("1:02:03") == 3723
    assert duration_seconds(90) == 90
    assert duration_seconds("unknown") == 0


def test_dedup_merges_recall_sources_and_keeps_best_raw_score():
    recall = CandidateRecall()
    candidates = [
        {
            "bvid": "BV1", "title": "AI Agent", "mid": 1,
            "recall_source": "interest", "recall_tag": "AI", "raw_recall_score": 0.6,
        },
        {
            "bvid": "BV1", "title": "AI Agent", "mid": 1,
            "recall_source": "recent_interest", "recall_tag": "AI", "raw_recall_score": 0.9,
        },
        {
            "bvid": "BV2", "title": "音乐", "mid": 2,
            "recall_source": "trending", "raw_recall_score": 0.5,
        },
    ]
    result = recall._deduplicate_candidates(candidates)
    assert len(result) == 2
    merged = next(item for item in result if item["bvid"] == "BV1")
    assert merged["recall_sources"] == ["interest", "recent_interest"]
    assert merged["raw_recall_score"] == 0.9
    assert {row["source"] for row in merged["recall_evidence"]} == {
        "interest", "recent_interest"
    }


def test_uncalibrated_sources_use_explicit_priors_not_raw_scale():
    result = calibrate_recall_candidates([
        {"bvid": "TREND", "recall_source": "trending", "raw_recall_score": 1000},
        {"bvid": "QUERY", "recall_source": "context_query", "raw_recall_score": 0.01},
    ])
    by_bvid = {item["bvid"]: item for item in result}
    assert 0 <= by_bvid["TREND"]["calibrated_recall_score"] <= 1
    assert 0 <= by_bvid["QUERY"]["calibrated_recall_score"] <= 1
    assert by_bvid["QUERY"]["calibrated_recall_score"] > by_bvid["TREND"]["calibrated_recall_score"]
    assert by_bvid["QUERY"]["recall_score_calibrated"] is False


def test_up_video_request_is_wbi_signed_and_cached(monkeypatch):
    class Response:
        status_code = 200

        def json(self):
            return {"code": 0, "data": {"list": {
                "vlist": [{"bvid": "BV-direct", "mid": 42}],
                "page": {"count": 1},
            }}}

    class Client:
        def __init__(self):
            self.params = []

        async def get(self, _url, params=None):
            self.params.append(dict(params or {}))
            return Response()

    async def scenario():
        BilibiliService._up_videos_cache.clear()
        service = BilibiliService()
        service.client = Client()
        service._wbi_keys = ("7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45")
        monkeypatch.setattr("app.services.bilibili.time.time", lambda: 1_700_000_000)

        first = await service.get_up_videos(42, ps=5)
        second = await service.get_up_videos(42, ps=5)

        assert first["success"] and second["success"]
        assert len(service.client.params) == 1
        assert service.client.params[0]["mid"] == "42"
        assert service.client.params[0]["wts"] == "1700000000"
        assert service.client.params[0]["w_rid"] == "8674209c57dc49cf4ff105999669b256"

    asyncio.run(scenario())


def test_followed_up_recall_prefers_mid_direct_endpoint_and_uses_channel_prior():
    class Bili:
        def __init__(self):
            self.direct_calls = []

        async def get_up_videos(self, mid, **kwargs):
            self.direct_calls.append((mid, kwargs))
            return {"success": True, "videos": [{
                "bvid": "BV-direct", "title": "direct post", "mid": mid,
                "author": "same-name", "created": 1_700_000_000,
                "length": "03:00", "play": 100,
            }]}

        async def search_bilibili(self, **_kwargs):
            raise AssertionError("name search must not run when MID lookup succeeds")

    async def scenario():
        recall = CandidateRecall()
        bili = Bili()
        result = await recall._recall_by_followed_ups(
            bili,
            {"followed_ups": [{
                "mid": 42, "name": "same-name", "score": 0.1,
                "source": "special_followings",
            }]},
            limit=5,
        )
        assert [item["bvid"] for item in result] == ["BV-direct"]
        assert result[0]["mid"] == 42
        assert result[0]["follow_prior"] == 1.0
        assert bili.direct_calls[0][0] == 42

    asyncio.run(scenario())
