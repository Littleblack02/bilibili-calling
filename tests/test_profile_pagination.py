import asyncio

from app.services.profile.pagination import (
    AuthRequired,
    CursorPaginator,
    OffsetPaginator,
    PageNumberPaginator,
    ProfileChannelAdapter,
    RateLimited,
)


ADAPTER = ProfileChannelAdapter(
    item_paths=("data.items",),
    has_more_paths=("data.has_more",),
    cursor_paths=("data.next",),
)


def test_page_number_paginator_collects_all_pages_and_marks_full_snapshot():
    calls = []

    async def fetch(page, size):
        calls.append((page, size))
        return {"code": 0, "data": {
            "items": [{"id": page}], "has_more": page < 3,
        }}

    result = asyncio.run(PageNumberPaginator(page_size=20).collect(fetch, ADAPTER))
    assert [item["id"] for item in result.items] == [1, 2, 3]
    assert calls == [(1, 20), (2, 20), (3, 20)]
    assert result.full_snapshot
    assert result.cursor == {"page": 4}


def test_cursor_and_offset_paginators_persist_next_position():
    async def cursor_fetch(cursor, _size):
        if cursor is None:
            return {"code": 0, "data": {"items": [{"id": 1}], "has_more": True, "next": "abc"}}
        return {"code": 0, "data": {"items": [{"id": 2}], "has_more": False}}

    cursor = asyncio.run(CursorPaginator().collect(cursor_fetch, ADAPTER))
    assert [item["id"] for item in cursor.items] == [1, 2]
    assert cursor.cursor == {"cursor": None}

    async def offset_fetch(offset, size):
        return {"code": 0, "data": {
            "items": [{"id": offset}], "has_more": offset == 0, "next": offset + size,
        }}

    offset = asyncio.run(OffsetPaginator(page_size=10).collect(offset_fetch, ADAPTER))
    assert [item["id"] for item in offset.items] == [0, 10]
    assert offset.cursor == {"offset": 20}


def test_429_retries_with_backoff_and_auth_stops_immediately():
    attempts = 0
    sleeps = []

    async def no_sleep(delay):
        sleeps.append(delay)

    async def flaky(_page, _size):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RateLimited(retry_after=0.01)
        return {"code": 0, "data": {"items": [{"id": 1}], "has_more": False}}

    paginator = PageNumberPaginator(max_retries=3, sleep=no_sleep)
    result = asyncio.run(paginator.collect(flaky, ADAPTER))
    assert result.status == "success"
    assert attempts == 3
    assert sleeps == [0.01, 0.01]

    auth_attempts = 0
    async def unauthorized(_page, _size):
        nonlocal auth_attempts
        auth_attempts += 1
        raise AuthRequired("cookie expired")

    auth = asyncio.run(paginator.collect(unauthorized, ADAPTER))
    assert auth.status == "auth_required"
    assert auth.capability_status == "auth_required"
    assert auth_attempts == 1


def test_adapter_surfaces_schema_change_and_nonzero_codes():
    async def html(_page, _size):
        return "<html>gateway</html>"
    changed = asyncio.run(PageNumberPaginator().collect(html, ADAPTER))
    assert changed.status == "schema_error"
    assert changed.capability_status == "schema_changed"

    async def missing(_page, _size):
        return {"code": 0, "data": {"unexpected": []}}
    missing_result = asyncio.run(PageNumberPaginator().collect(missing, ADAPTER))
    assert missing_result.status == "schema_error"

    async def coded(_page, _size):
        return {"code": -101, "message": "账号未登录"}
    auth = asyncio.run(PageNumberPaginator().collect(coded, ADAPTER))
    assert auth.status == "auth_required"

    async def slow(_page, _size):
        await asyncio.sleep(0.2)
        return {"code": 0, "data": {"items": [], "has_more": False}}
    timed_out = asyncio.run(
        PageNumberPaginator(timeout_seconds=0.01).collect(slow, ADAPTER)
    )
    assert timed_out.status == "timed_out"
