# Temporal affinity V2 calibration and evidence semantics

V2 separates two questions that V1 conflated:

- `concept_absolute_affinities`: is there enough current evidence that the user
  is interested? `1 - exp(-raw_score / tau)` keeps weak singleton evidence weak.
- `concept_relative_shares`: among supported interests, which ones are stronger?
  This is `raw_score / sum(raw_scores)` and is never used alone to create
  confidence.

`TEMPORAL_AFFINITY_TAU=1.5` means 1.5 units of deduplicated evidence map to
0.632 absolute affinity. This is an explicit initial calibration point, not a
hidden normalizer. Tune it only on the frozen dev split and record the selected
value with the evaluation result.

Signals use five semantic groups: `exposure`, `consumed`, `intent`,
`durable_interest`, and `creator_affinity`. Exposure has zero positive affinity.
For one content identity, repeats within a group collapse to their maximum;
other correlated groups combine as strongest evidence plus discounted noisy-OR.
The discount is configured by `TEMPORAL_SECONDARY_SIGNAL_DISCOUNT` (default
0.25). This makes repeated synchronization idempotent and prevents a single
view/favorite sequence from being treated as independent evidence many times.

`profile_evidence_mass` records total deduplicated strength.
`profile_recency_confidence` is gated by known-time recent evidence. Unknown
timestamps never enter recent affinity. Recommendation reasons label evidence
as historical when evidence exists but recency confidence is below 0.15.

V2 is independently reversible with `TEMPORAL_AFFINITY_V2_ENABLED=false`.
Profile JSON includes `schema_version` and the actual calibration parameters so
V1 and V2 results remain attributable during rollout.
