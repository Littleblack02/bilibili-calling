# Candidate Pipeline V2

Enable the merge/hydration path with `CANDIDATE_HYDRATION_ENABLED=true`.
The V1 path remains available while offline evaluation is incomplete.

## Pipeline

1. Recall channels emit a BVID, source attribution and raw source-local score.
2. Duplicate BVIDs are merged. Every source remains in `recall_evidence`.
3. Raw scores are never compared directly across channels. If a learned,
   time-split piecewise calibration curve exists it is used; otherwise the
   channel receives a conservative explicit prior and
   `recall_score_calibrated=false` is returned.
4. With the V2 flag enabled, non-trace recall metadata is moved into a fallback
   envelope. The ranking path receives lightweight IDs until hydration.
5. Hydration requests each unique BVID once, concurrently and with a timeout.
   It combines the view response, archive tags, an existing local summary and
   deterministic ontology concepts. It records per-field source and fetch time.
6. Successful core metadata is written through to `VideoCache`; complete
   in-process hydration objects use a TTL cache. Missing remote fields remain
   missing and never receive invented zero/default values.
7. Eligibility filtering, rule ranking, optional LLM assistance and diversity
   run only after hydration.

## Followed-UP recall

`get_up_videos(mid=...)` now signs `/x/space/wbi/arc/search` with the complete
WBI image/sub-image key mix, timestamp, parameter sanitization, URL encoding and
MD5 `w_rid`. Recent submissions are cached by `(mid, page, size, order)`.
The direct MID endpoint is authoritative. Name search runs only when the direct
request reports failure, and fallback results must still have the exact MID;
an empty successful direct result does not trigger name search.

Follow priors are explicit and auditable:

| Relationship | Prior |
| --- | ---: |
| special following | 1.00 |
| ordinary following | 0.72 |
| weak/whisper following | 0.45 |
| unknown following subtype | 0.60 |

## Hydrated contract

The contract includes title, description, tags, category/tid, optional UGC
collection, creator/MID, publication time, duration, cover/dimensions,
view/like/coin/favorite/comment/danmaku/share statistics, an existing cached
summary, ontology concept IDs, `hydration_coverage`, `hydration_status`, and
`hydration_field_meta`. Optional summary/collection fields are not fabricated.

The automatic fixture verifies at least 90% coverage of the twelve critical
ranking fields and proves that a duplicate BVID performs one remote hydration.
This fixture is not a claim that a live Bilibili account or every historical
video returns all optional fields; live behavior remains a smoke-test item.

## Configuration and rollback

- `UP_VIDEO_CACHE_TTL_SECONDS=900`
- `CANDIDATE_HYDRATION_CACHE_TTL_SECONDS=1800`
- `CANDIDATE_HYDRATION_CONCURRENCY=8`
- `CANDIDATE_HYDRATION_TIMEOUT_SECONDS=12`

Set `CANDIDATE_HYDRATION_ENABLED=false` to restore the existing partial-metadata
candidate path. UP MID direct recall and score attribution remain safe to use;
the name-search fallback is retained for availability.
