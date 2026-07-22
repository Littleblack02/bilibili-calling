# Required LLM recommendation contract

The recommendation endpoint uses the configured chat model twice and does not
claim model-backed recommendation unless both stages succeed.

## Runtime flow

1. Build or load the aggregate user profile, including temporal interests and
   Ontology concept affinities.
2. Ask the model to call the allow-listed `search_bilibili_videos` tool with
   one to five search queries. The application validates and executes those
   queries through `BilibiliService.search_bilibili`; the model never receives
   cookies and never accesses the network directly.
3. Merge the model-planned search results with deterministic interest, recent
   interest, category, followed-UP, dynamic, series and trending recall.
4. Apply eligibility, privacy and negative-feedback filters.
5. Produce the auditable Ontology/rule baseline score.
6. Require the model to score every candidate in the rerank set. Blend the
   validated model score with the baseline, diversify, and generate reasons.
7. Persist `llm_recall_plan` and `llm_rerank` metadata with the recommendation
   batch. Responses expose `llm_recall_applied` and `llm_rerank_applied`.

## Required configuration

```env
DASHSCOPE_API_KEY=replace_me
OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
LLM_MODEL=replace_me

RECOMMENDATION_LLM_RERANK_ENABLED=true
RECOMMENDATION_LLM_REQUIRED=true
RECOMMENDATION_LLM_ENABLE_THINKING=false
RECOMMENDATION_LLM_TOP_N=20
RECOMMENDATION_LLM_TIMEOUT_SECONDS=30
```

Both recommendation switches default to `true`. In required mode, missing
credentials, a missing tool call, invalid tool arguments, a timeout, malformed
JSON, incomplete candidate scores or out-of-range scores abort the request.
The HTTP endpoint returns 503 instead of silently returning a rule-only list.

Recommendation planning and JSON scoring are bounded structured tasks, so
DashScope hybrid-thinking models default to `enable_thinking=false` for lower
latency and tool-call compatibility. Other OpenAI-compatible providers do not
receive this provider-specific field. It can be re-enabled explicitly when the
selected DashScope model supports the desired tool-calling mode.

Set `RECOMMENDATION_LLM_REQUIRED=false` only for an explicit degraded-mode
deployment. That mode may fall back to deterministic recall/ranking and must
not be presented as a fully model-backed recommendation result.

## Ontology coverage and new content

The public Ontology is a versioned controlled vocabulary, not an exhaustive
copy of every current or future Bilibili topic. Known concepts receive graph
matching and explainable paths. New terminology that is not yet curated can
still participate through its Bilibili metadata, vector representation,
profile tags, the LLM recall planner and LLM candidate reranker; its
`ontology_match` remains zero until the concept is reviewed and added to a new
Ontology version.

This fallback prevents new content from breaking recommendation while keeping
the public Ontology deterministic and auditable. Unknown terms must not be
silently written into the public RDF graph by a model. A future curation queue
may collect unmatched high-frequency terms for human review, SHACL validation
and versioned publication.
