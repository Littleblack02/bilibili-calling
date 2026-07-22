# V2 feature flags and rollback

The four Ontology-backed V2 capabilities default to `true` with a 100% rollout:
temporal affinity, grounded RAG, profile sync and entity linking. Candidate
hydration remains opt-in because it changes candidate acquisition rather than
Ontology behavior. Recommendation batches persist the exact flag snapshot in
their context so evaluation and rollback remain attributable.

| Environment variable | Scope | Disabled behavior |
|---|---|---|
| `TEMPORAL_AFFINITY_V2_ENABLED` | absolute temporal affinity and deduplication | V1 temporal profile |
| `RAG_GROUNDED_V2_ENABLED` | thresholded retrieval, evidence contract and refusal | existing RAG path |
| `PROFILE_SYNC_V2_ENABLED` | sync batches, cursors and snapshot lifecycle | existing channel fetch |
| `ONTOLOGY_LINKER_V2_ENABLED` | candidate ranking, disambiguation and abstention | deterministic V1 linker |
| `CANDIDATE_HYDRATION_ENABLED` | direct UP recall and candidate completion | existing recall fields |

Set any individual variable to `false` to roll that capability back. Set
`V2_ROLLOUT_PERCENTAGE` below 100 only for an intentional staged rollout; a
value of 0 disables the enabled V2 capabilities for all sessions except the
hashed test allowlist.

Roll back one capability at a time, preserve the batch context and algorithm
version, then compare the same frozen evaluation split. A flag must not cause
V1 and V2 to write incompatible unversioned payloads.
