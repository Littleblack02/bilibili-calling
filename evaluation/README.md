# V2 evaluation fixtures

These JSONL files define the versioned, deidentified data contracts used by
the entity-linking, grounded-RAG, and temporal recommendation evaluators.
Entity-linking and recommendation fixtures are deterministic synthetic/editorial
regression sets. They prove reproducibility and engineering behavior, not live
Bilibili accuracy or causal online uplift.

- Direct session IDs, usernames, cookies, CSRF values, emails and phone numbers
  are forbidden. Stable joins use one-way SHA-256 hashes with an external salt.
- Recommendation records are ordered by `event_time`. Evaluators must choose a
  cutoff timestamp and never randomly move future interactions into training.
- `recommendation_items.jsonl` is a fixed candidate catalog whose publication
  timestamps precede the cutoff. Future events are used only as held-out labels.
- Once the test split is reviewed and frozen, tuning uses only train/dev labels.
- Validate locally with `python scripts/validate_evaluation_data.py`.
- Rebuild and evaluate recommendations with
  `python scripts/generate_recommendation_eval.py` and
  `python scripts/evaluate_recommendation.py`.
- Rebuild and evaluate the 150-question Grounded-RAG fixture with
  `python scripts/generate_rag_eval.py` and `python scripts/evaluate_rag.py`.

Target reviewed sizes are at least 300 entity-linking examples and 120–200 QA
examples. Real Bilibili fixtures must be recorded, minimized, and scrubbed before
commit; credentials and direct identifiers are never allowed in this directory.
