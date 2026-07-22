# Grounded RAG offline evaluation

**Result:** PASS

> Deterministic synthetic/editorial, local extractive regression only; this is not a live-domain or remote-LLM claim.

| Metric | Value |
|---|---:|
| retrieval_recall_at_5 | 0.980159 |
| retrieval_mrr_at_10 | 0.992063 |
| citation_correctness | 0.982143 |
| groundedness | 1.000000 |
| answerable_grounded_rate | 1.000000 |
| unanswerable_refusal_rate | 1.000000 |
| factual_hallucination_rate | 0.000000 |
| retrieval_latency_p50_ms | 31.645900 |
| retrieval_latency_p95_ms | 86.266900 |

## Acceptance gates

- [x] qa_count_120_to_200
- [x] recall_at_5_gte_085
- [x] mrr_at_10_gte_075
- [x] citation_correctness_gte_095
- [x] groundedness_gte_090
- [x] refusal_rate_gte_090
- [x] hallucination_rate_lte_005
- [x] local_retrieval_p95_lte_800ms
