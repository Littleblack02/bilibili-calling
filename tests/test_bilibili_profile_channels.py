from app.services.bilibili import BilibiliService


def test_channel_extractor_handles_known_response_shapes():
    assert BilibiliService._extract_channel_items(
        {"code": 0, "data": {"topic_list": [{"id": 1}]}},
        ("topic_list", "list"),
    ) == [{"id": 1}]
    assert BilibiliService._extract_channel_items(
        {"data": {"nested": {"items": [{"id": 2}]}}},
        ("nested.items",),
    ) == [{"id": 2}]


def test_capability_matrix_is_honest_about_unavailable_histories():
    capabilities = BilibiliService.profile_channel_capabilities()
    assert capabilities["supported"]["history"]["available"] is True
    assert capabilities["supported"]["dynamic_feed"]["available"] is True
    assert capabilities["unavailable"]["video_like_history"]["available"] is False
    assert capabilities["unavailable"]["video_coin_history"]["available"] is False
