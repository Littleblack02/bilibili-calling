from app.config import settings


def test_v2_feature_flags_are_explicit_and_auditable():
    snapshot = settings.v2_feature_flags()
    assert snapshot == {
        "temporal_affinity_v2": settings.temporal_affinity_v2_enabled,
        "rag_grounded_v2": settings.rag_grounded_v2_enabled,
        "profile_sync_v2": settings.profile_sync_v2_enabled,
        "ontology_linker_v2": settings.ontology_linker_v2_enabled,
        "candidate_hydration": settings.candidate_hydration_enabled,
    }
    assert all(isinstance(value, bool) for value in snapshot.values())
