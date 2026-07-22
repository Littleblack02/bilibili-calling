# V2 feature flags and rollback

All V2 switches default to `false`. Recommendation batches persist the exact
flag snapshot in their context so evaluation and rollback remain attributable.

| Environment variable | Scope | Disabled behavior |
|---|---|---|
| `TEMPORAL_AFFINITY_V2_ENABLED` | absolute temporal affinity and deduplication | V1 temporal profile |
| `RAG_GROUNDED_V2_ENABLED` | thresholded retrieval, evidence contract and refusal | existing RAG path |
| `PROFILE_SYNC_V2_ENABLED` | sync batches, cursors and snapshot lifecycle | existing channel fetch |
| `ONTOLOGY_LINKER_V2_ENABLED` | candidate ranking, disambiguation and abstention | deterministic V1 linker |
| `CANDIDATE_HYDRATION_ENABLED` | direct UP recall and candidate completion | existing recall fields |

Roll back one capability at a time, preserve the batch context and algorithm
version, then compare the same frozen evaluation split. A flag must not cause
V1 and V2 to write incompatible unversioned payloads.
