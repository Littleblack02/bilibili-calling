# Temporal recommendation offline evaluation

**Result:** PASS

> This is a deterministic synthetic/editorial regression fixture. It does not prove live Bilibili uplift.

| Variant | NDCG@10 | Recall@20 | HitRate@10 | MRR@10 | Coverage | Novelty | ILD | Topic coverage |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline_v1 | 0.0398 | 0.0774 | 0.3095 | 0.0432 | 0.8353 | 0.4421 | 0.0336 | 0.1171 |
| full_v2 | 0.5707 | 0.6944 | 1.0000 | 0.7768 | 0.3065 | 0.3529 | 0.8055 | 1.0000 |
| no_time | 0.4838 | 0.7054 | 1.0000 | 0.5345 | 0.3214 | 0.3484 | 0.8288 | 1.0000 |
| no_ontology | 0.4885 | 0.6905 | 1.0000 | 0.6167 | 0.2778 | 0.3365 | 0.8539 | 0.9940 |
| no_clusters | 0.5223 | 0.6944 | 1.0000 | 0.7123 | 0.2817 | 0.3244 | 0.8710 | 1.0000 |
| no_hydration | 0.0202 | 0.0675 | 0.1548 | 0.0192 | 0.3591 | 0.2949 | 0.7867 | 1.0000 |
| no_dynamic | 0.8072 | 0.9782 | 1.0000 | 0.7907 | 0.2083 | 0.3450 | 0.8544 | 0.9683 |
| weights_relevance | 0.3246 | 0.4633 | 0.8095 | 0.6802 | 0.7054 | 0.4647 | 0.1967 | 0.5397 |
| weights_diversity | 0.6216 | 0.6944 | 1.0000 | 0.8056 | 0.1478 | 0.3136 | 0.9176 | 1.0000 |

## Acceptance gates

- [x] ndcg_relative_gain_gte_10pct
- [x] recall_relative_gain_gte_8pct
- [x] hit_rate_relative_gain_gte_8pct
- [x] ild_not_lower
- [x] topic_coverage_relative_gain_gte_10pct

95% confidence intervals and all bucket results are preserved in the JSON report.
