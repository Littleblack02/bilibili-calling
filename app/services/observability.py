"""Dependency-free bounded metrics and privacy-safe request correlation."""
from __future__ import annotations

from collections import defaultdict, deque
from contextvars import ContextVar
import hashlib
import math
from threading import RLock
from typing import Any


request_id_var: ContextVar[str] = ContextVar("request_id", default="background")
session_hash_var: ContextVar[str] = ContextVar("session_hash", default="anonymous")
batch_id_var: ContextVar[str] = ContextVar("batch_id", default="none")


def safe_hash(value: str | None) -> str:
    if not value:
        return "anonymous"
    return hashlib.sha256(("observability-v1:" + str(value)).encode()).hexdigest()[:16]


def correlation() -> dict[str, str]:
    return {
        "request_id": request_id_var.get(),
        "session_hash": session_hash_var.get(),
        "batch_id": batch_id_var.get(),
    }


class MetricsRegistry:
    def __init__(self, max_observations: int = 2048) -> None:
        self._lock = RLock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._observations: dict[tuple[str, tuple[tuple[str, str], ...]], deque[float]] = defaultdict(
            lambda: deque(maxlen=max_observations)
        )

    @staticmethod
    def _key(name: str, labels: dict[str, Any]) -> tuple[str, tuple[tuple[str, str], ...]]:
        safe_labels = tuple(sorted(
            (str(key)[:50], str(value)[:100])
            for key, value in labels.items()
            if key not in {"session_id", "cookie", "sessdata", "bili_jct"}
        ))
        return name, safe_labels

    def inc(self, name: str, value: float = 1.0, **labels: Any) -> None:
        with self._lock:
            self._counters[self._key(name, labels)] += float(value)

    def observe(self, name: str, value: float, **labels: Any) -> None:
        numeric = float(value)
        if not math.isfinite(numeric):
            return
        with self._lock:
            self._observations[self._key(name, labels)].append(numeric)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = [
                {"name": name, "labels": dict(labels), "value": value}
                for (name, labels), value in sorted(self._counters.items())
            ]
            observations = []
            for (name, labels), values in sorted(self._observations.items()):
                ordered = sorted(values)
                count = len(ordered)
                observations.append({
                    "name": name, "labels": dict(labels), "count": count,
                    "average": sum(ordered) / count if count else 0.0,
                    "p95": ordered[min(count - 1, math.ceil(count * 0.95) - 1)] if count else 0.0,
                    "maximum": ordered[-1] if count else 0.0,
                })
            return {"counters": counters, "observations": observations, "correlation": correlation()}

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._observations.clear()


metrics = MetricsRegistry()
