import asyncio

from app.services.recommendation.candidate_hydration import CandidateHydrator


class Ontology:
    def resolve_text(self, _text):
        class Match:
            concept_id = "https://example.org/Agent"
            label = "Agent"
            confidence = 0.94
        return [Match()]


class Bili:
    def __init__(self):
        self.info_calls = []
        self.tag_calls = []

    async def get_video_info(self, bvid):
        self.info_calls.append(bvid)
        return {"success": True, "data": {
            "bvid": bvid, "aid": 1, "cid": 2,
            "title": "Agent 实战", "desc": "LangGraph workflow",
            "tname": "知识", "tid": 36, "pubdate": 1_700_000_000,
            "duration": 600, "pic": "https://example.test/cover.jpg",
            "owner": {"mid": 42, "name": "UP"},
            "dimension": {"width": 1920, "height": 1080},
            "stat": {"view": 1000, "like": 100, "coin": 20,
                     "favorite": 30, "reply": 10, "danmaku": 8, "share": 4},
        }}

    async def get_video_tags(self, bvid):
        self.tag_calls.append(bvid)
        return {"success": True, "tags": [{"tag_name": "AI"}]}


def test_hydration_fetches_each_bvid_once_and_records_field_provenance():
    async def scenario():
        bili = Bili()
        hydrator = CandidateHydrator(persist=False, ontology=Ontology())
        candidates = [
            {"bvid": "BV1", "recall_source": "interest"},
            {"bvid": "BV1", "recall_source": "trending"},
        ]
        first = await hydrator.hydrate_candidates(bili, candidates)
        second = await hydrator.hydrate_candidates(bili, candidates[:1])

        assert bili.info_calls == ["BV1"]
        assert bili.tag_calls == ["BV1"]
        assert len(first) == 2 and len(second) == 1
        assert first[0]["title"] == "Agent 实战"
        assert first[0]["tags"] == ["AI"]
        assert first[0]["concept_ids"] == ["https://example.org/Agent"]
        assert first[0]["hydration_coverage"] >= 0.90
        assert first[0]["hydration_field_meta"]["play"]["source"] == "bilibili_view"
        assert second[0]["hydration_cache_hit"] is True

    asyncio.run(scenario())
