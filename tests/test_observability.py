from app.services.observability import MetricsRegistry, safe_hash


def test_metrics_are_bounded_and_strip_sensitive_label_keys():
    registry = MetricsRegistry(max_observations=3)
    registry.inc("profile_channel_outcomes_total", channel="history", status="success")
    registry.inc("unsafe", session_id="raw-session", cookie="secret", outcome="ignored")
    for value in (1, 2, 3, 4):
        registry.observe("latency_ms", value, route="/test")
    snapshot = registry.snapshot()
    unsafe = next(row for row in snapshot["counters"] if row["name"] == "unsafe")
    assert unsafe["labels"] == {"outcome": "ignored"}
    latency = next(row for row in snapshot["observations"] if row["name"] == "latency_ms")
    assert latency["count"] == 3
    assert latency["maximum"] == 4
    assert safe_hash("session") != "session"
