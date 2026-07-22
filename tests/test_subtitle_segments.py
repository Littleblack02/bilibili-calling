import json

from app.services.bilibili import BilibiliService


def test_bilibili_native_subtitle_json_preserves_timestamps():
    service = object.__new__(BilibiliService)
    raw = json.dumps({"body": [
        {"from": 1.25, "to": 3.5, "content": "第一段"},
        {"from": 3.5, "to": 8.0, "content": "第二段"},
    ]}, ensure_ascii=False)
    segments = service._parse_subtitle_segments(raw, "subtitle.json")
    assert segments == [
        {"start_time": 1.25, "end_time": 3.5, "text": "第一段"},
        {"start_time": 3.5, "end_time": 8.0, "text": "第二段"},
    ]


def test_srt_parser_preserves_range_and_text():
    service = object.__new__(BilibiliService)
    raw = "1\n00:00:02,000 --> 00:00:04,500\nRAG 索引\n\n2\n00:01:00,000 --> 00:01:03,000\n向量检索\n"
    segments = service._parse_subtitle_segments(raw, "video.srt")
    assert segments[0] == {"start_time": 2.0, "end_time": 4.5, "text": "RAG 索引"}
    assert segments[1]["start_time"] == 60.0
    assert service._parse_srt(raw) == "RAG 索引\n向量检索"
