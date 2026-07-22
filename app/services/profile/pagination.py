"""Bounded page/cursor/offset collection with explicit capability outcomes."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import random
from typing import Any, Awaitable, Callable, Iterable

from app.services.profile.signals import parse_datetime


class ChannelError(RuntimeError):
    capability_status = "degraded"


class AuthRequired(ChannelError):
    capability_status = "auth_required"


class RateLimited(ChannelError):
    capability_status = "degraded"

    def __init__(self, message: str = "rate limited", retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class SchemaChanged(ChannelError):
    capability_status = "schema_changed"


@dataclass(frozen=True)
class Page:
    items: list[dict[str, Any]]
    has_more: bool
    next_cursor: Any = None


@dataclass
class PaginationResult:
    items: list[dict[str, Any]] = field(default_factory=list)
    page_count: int = 0
    cursor: dict[str, Any] = field(default_factory=dict)
    status: str = "success"
    capability_status: str = "working"
    error_summary: str | None = None
    full_snapshot: bool = False


def _nested(payload: Any, path: str) -> Any:
    value = payload
    for part in path.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


class ProfileChannelAdapter:
    """Convert raw response envelopes into one stable page contract."""

    def __init__(
        self,
        *,
        item_paths: Iterable[str],
        has_more_paths: Iterable[str] = ("data.has_more", "data.has_next", "data.page.has_more"),
        cursor_paths: Iterable[str] = ("data.next_cursor", "data.offset", "data.page.next"),
    ) -> None:
        self.item_paths = tuple(item_paths)
        self.has_more_paths = tuple(has_more_paths)
        self.cursor_paths = tuple(cursor_paths)

    def adapt(self, payload: Any) -> Page:
        if not isinstance(payload, dict):
            raise SchemaChanged("response is not a JSON object")
        code = payload.get("code", 0)
        if code not in (0, None):
            message = str(payload.get("message") or "non-zero API code")
            if code in {-101, -111, -400, 401, 403}:
                raise AuthRequired(message)
            if code in {-412, -509, 429}:
                raise RateLimited(message)
            raise ChannelError(f"API code {code}: {message}")
        items = None
        for path in self.item_paths:
            candidate = _nested(payload, path)
            if isinstance(candidate, list):
                items = candidate
                break
        if items is None:
            raise SchemaChanged(
                "none of the declared item paths contains a list: "
                + ", ".join(self.item_paths)
            )
        normalized = [item for item in items if isinstance(item, dict)]
        has_more = False
        has_explicit_more = False
        for path in self.has_more_paths:
            value = _nested(payload, path)
            if value is not None:
                has_explicit_more = True
                has_more = bool(value)
                break
        cursor = None
        for path in self.cursor_paths:
            value = _nested(payload, path)
            if value not in (None, ""):
                cursor = value
                break
        # If the API omits an explicit flag but provides a next cursor, the
        # cursor is authoritative.
        return Page(
            normalized,
            has_more if has_explicit_more else cursor is not None,
            cursor,
        )


FetchPage = Callable[[Any, int], Awaitable[Any]]


class BasePaginator:
    def __init__(
        self,
        *,
        page_size: int = 50,
        max_pages: int = 20,
        max_items: int = 1000,
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
        backoff_base_seconds: float = 0.5,
        rate_limit_seconds: float = 0.0,
        recent_window_days: float | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.page_size = max(1, page_size)
        self.max_pages = max(1, max_pages)
        self.max_items = max(1, max_items)
        self.timeout_seconds = max(0.1, timeout_seconds)
        self.max_retries = max(0, max_retries)
        self.backoff_base_seconds = max(0.0, backoff_base_seconds)
        self.rate_limit_seconds = max(0.0, rate_limit_seconds)
        self.recent_window_days = recent_window_days
        self.sleep = sleep
        self.jitter = jitter

    async def _fetch_with_retry(self, fetch: FetchPage, token: Any) -> Any:
        for attempt in range(self.max_retries + 1):
            try:
                return await asyncio.wait_for(
                    fetch(token, self.page_size), timeout=self.timeout_seconds
                )
            except AuthRequired:
                raise
            except RateLimited as exc:
                if attempt >= self.max_retries:
                    raise
                delay = (
                    exc.retry_after
                    if exc.retry_after is not None
                    else self.backoff_base_seconds * (2 ** attempt) + self.jitter() * 0.25
                )
                await self.sleep(max(0.0, delay))

    def _within_window(self, item: dict[str, Any], now: datetime) -> bool:
        if self.recent_window_days is None:
            return True
        value = next((
            item.get(field) for field in (
                "occurred_at", "view_at", "pubtime", "pubdate", "ctime"
            ) if item.get(field) is not None
        ), None)
        occurred_at = parse_datetime(value)
        # Unknown event time is retained but cannot be used as proof that a
        # complete recent window was reached.
        return occurred_at is None or occurred_at >= now - timedelta(days=self.recent_window_days)

    async def collect(
        self,
        fetch: FetchPage,
        adapter: ProfileChannelAdapter,
        *,
        initial: Any = None,
        now: datetime | None = None,
    ) -> PaginationResult:
        now = now or datetime.utcnow()
        result = PaginationResult(cursor=self._cursor_state(initial))
        token = self._initial_token(initial)
        exhausted = False
        try:
            for page_index in range(self.max_pages):
                raw = await self._fetch_with_retry(fetch, token)
                page = adapter.adapt(raw)
                result.page_count += 1
                in_window = [item for item in page.items if self._within_window(item, now)]
                result.items.extend(in_window[: max(0, self.max_items - len(result.items))])
                token = self._next_token(token, page, page_index)
                result.cursor = self._cursor_state(token)
                hit_item_cap = len(result.items) >= self.max_items
                hit_time_boundary = bool(
                    self.recent_window_days is not None
                    and page.items and len(in_window) < len(page.items)
                )
                if not page.has_more or hit_time_boundary:
                    exhausted = True
                    break
                if hit_item_cap:
                    break
                if self.rate_limit_seconds:
                    await self.sleep(self.rate_limit_seconds)
            result.full_snapshot = exhausted and self.recent_window_days is None
            return result
        except AuthRequired as exc:
            result.status = "auth_required"
            result.capability_status = "auth_required"
            result.error_summary = str(exc)[:500]
        except SchemaChanged as exc:
            result.status = "schema_error"
            result.capability_status = "schema_changed"
            result.error_summary = str(exc)[:500]
        except RateLimited as exc:
            result.status = "rate_limited"
            result.capability_status = "degraded"
            result.error_summary = str(exc)[:500]
        except asyncio.TimeoutError:
            result.status = "timed_out"
            result.capability_status = "degraded"
            result.error_summary = "channel request timed out"
        except ChannelError as exc:
            result.status = "failed"
            result.capability_status = exc.capability_status
            result.error_summary = str(exc)[:500]
        result.full_snapshot = False
        return result

    def _initial_token(self, initial: Any) -> Any:
        raise NotImplementedError

    def _next_token(self, current: Any, page: Page, page_index: int) -> Any:
        raise NotImplementedError

    def _cursor_state(self, token: Any) -> dict[str, Any]:
        raise NotImplementedError


class PageNumberPaginator(BasePaginator):
    def _initial_token(self, initial: Any) -> int:
        return int(initial or 1)

    def _next_token(self, current: int, page: Page, page_index: int) -> int:
        return current + 1

    def _cursor_state(self, token: Any) -> dict[str, Any]:
        return {"page": int(token or 1)}


class CursorPaginator(BasePaginator):
    def _initial_token(self, initial: Any) -> Any:
        return initial

    def _next_token(self, current: Any, page: Page, page_index: int) -> Any:
        return page.next_cursor

    def _cursor_state(self, token: Any) -> dict[str, Any]:
        return {"cursor": token}


class OffsetPaginator(BasePaginator):
    def _initial_token(self, initial: Any) -> int:
        return int(initial or 0)

    def _next_token(self, current: int, page: Page, page_index: int) -> int:
        return int(page.next_cursor) if page.next_cursor is not None else current + self.page_size

    def _cursor_state(self, token: Any) -> dict[str, Any]:
        return {"offset": int(token or 0)}
