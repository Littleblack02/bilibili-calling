# Grounded RAG V2

V2 is enabled by default. Set `RAG_GROUNDED_V2_ENABLED=false` to restore the
existing search and answer path.

Every original or ontology-expanded query uses a score-bearing vector-store
method. Scores are standardized to relevance in `[0,1]`, then filtered by
independent thresholds:

- original query: 0.35
- synonym/preferred-label expansion: 0.45
- broader/narrower expansion: 0.55
- related/requires/requiredBy expansion: 0.65

The original query has the highest fusion weight. Empty post-threshold results
stay empty. Metadata records the query, tier, rank, raw score semantics,
standardized relevance, threshold, graph path, weighted RRF and final score.

At most 30 fused chunks enter the deterministic local reranker. It reports
relevance, query coverage and evidence completeness and has no network, token or
credential dependency. `RAG_RERANKER_ENABLED=false` disables it; exceptions
fall back to fusion order.

Subtitle JSON, SRT and ASS are parsed into timestamped segments. V2 packs these
into 45-second windows and links concepts against each chunk body without
injecting the video title. Citations contain `bvid`, `chunk_index`, time range,
concept IDs and a supporting excerpt.

Generation is fail-closed: each factual statement is instructed to cite a
retrieved `[BVID#chunk_index]`. Missing or unknown citations cause the response
to become `收藏知识库证据不足`; V2 never fills missing evidence with general
knowledge. The API returns `grounded`, `retrieval_confidence`, `answerability`,
`citations`, `ontology_matches`, and citation-verification status. Retrieval is
restricted to BVIDs from the authenticated user's selected folders.
