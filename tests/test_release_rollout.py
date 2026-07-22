import json

from pydantic import SecretStr

from app.config import settings
from scripts.check_release_gates import REQUIRED, check


def test_rollout_is_stable_and_test_allowlist_uses_hashes(monkeypatch):
    monkeypatch.setattr(settings, "temporal_affinity_v2_enabled", True)
    monkeypatch.setattr(settings, "v2_rollout_percentage", 0)
    monkeypatch.setattr(settings, "v2_test_session_hashes", SecretStr(""))
    assert not settings.v2_feature_flags("session-a")["temporal_affinity_v2"]
    state = settings.v2_rollout_state("session-a")
    monkeypatch.setattr(settings, "v2_test_session_hashes", SecretStr(str(state["session_hash"])))
    assert settings.v2_feature_flags("session-a")["temporal_affinity_v2"]
    assert not settings.v2_feature_flags("session-b")["temporal_affinity_v2"]
    monkeypatch.setattr(settings, "v2_rollout_percentage", 100)
    assert settings.v2_feature_flags("session-b")["temporal_affinity_v2"]


def test_release_gate_fails_closed_on_missing_or_failed_report(tmp_path):
    assert not check(tmp_path)["passed"]
    for filename in REQUIRED.values():
        (tmp_path / filename).write_text(json.dumps({"passed": True}), encoding="utf-8")
    assert check(tmp_path)["passed"]
    (tmp_path / "rag.json").write_text(json.dumps({"passed": False}), encoding="utf-8")
    assert not check(tmp_path)["passed"]
