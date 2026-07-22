"""Evaluate Ontology V2 linking with micro metrics and abstention accuracy."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.evaluation.schemas import EntityLinkingExample  # noqa: E402
from app.services.ontology.service import OntologyService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("train", "dev", "test", "all"), default="test")
    parser.add_argument("--input", type=Path, default=ROOT / "evaluation" / "entity_linking.jsonl")
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "evaluation" / "entity-linking.json")
    args = parser.parse_args()

    examples = [EntityLinkingExample.model_validate_json(line) for line in
                args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.split != "all":
        examples = [row for row in examples if row.split == args.split]
    ontology = OntologyService()
    tp = fp = fn = 0
    abstain_total = abstain_correct = 0
    failures = []
    stage_counts: dict[str, int] = {}
    for example in examples:
        result = ontology.link_text_v2(example.text)
        predicted = {row["concept_id"] for row in result["selected"]}
        expected = set(example.expected_concepts)
        tp += len(predicted & expected)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
        stage_counts[result["stage"]] = stage_counts.get(result["stage"], 0) + 1
        if example.should_abstain:
            abstain_total += 1
            abstain_correct += int(result["rejected"] and not predicted)
        if predicted != expected:
            failures.append({
                "id": example.id, "text": example.text,
                "expected": sorted(expected), "predicted": sorted(predicted),
                "reason": result["rejection_reason"],
            })
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    report = {
        "schema_version": "1.0", "generated_at": datetime.now(timezone.utc).isoformat(),
        "ontology_version": ontology.VERSION, "split": args.split,
        "example_count": len(examples), "tp": tp, "fp": fp, "fn": fn,
        "precision": round(precision, 6), "recall": round(recall, 6), "f1": round(f1, 6),
        "abstention_accuracy": round(abstain_correct / abstain_total, 6) if abstain_total else None,
        "abstention_count": abstain_total, "stage_counts": stage_counts,
        "thresholds": {"precision": 0.92, "recall": 0.85, "f1": 0.88,
                       "abstention_accuracy": 0.90},
        "passes": precision >= 0.92 and recall >= 0.85 and f1 >= 0.88
                  and (not abstain_total or abstain_correct / abstain_total >= 0.90),
        "failures": failures[:100],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "example_count", "precision", "recall", "f1", "abstention_accuracy", "passes"
    )}, ensure_ascii=False))
    return 0 if report["passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
