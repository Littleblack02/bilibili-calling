"""Benchmark deterministic local ranking and preserve p95 evidence."""
from __future__ import annotations

from datetime import datetime, timedelta
import argparse
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.recommendation.profile_schema import RecommendationProfile
from app.services.recommendation.ranking import diversify, score_candidates


ROOT = Path(__file__).resolve().parents[1]
BASE = "https://bilibili.local/ontology/"
TOPICS = (
    ("RAG", "RAG"), ("LangGraph", "LangGraph"),
    ("Python", "Python编程"), ("MachineLearning", "机器学习"),
)


def percentile(values: list[float], p: float) -> float:
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * p))]


def benchmark(iterations: int = 40, candidates_count: int = 200) -> dict[str, object]:
    now = datetime.utcnow()
    profile = RecommendationProfile(
        long_term_interests={label: 0.7 for _, label in TOPICS},
        recent_interests={"RAG": 0.9, "LangGraph": 0.75},
        concept_absolute_affinities={BASE + concept: 0.75 for concept, _ in TOPICS},
        concept_relative_shares={BASE + concept: 0.25 for concept, _ in TOPICS},
        recent_concept_absolute_affinities={BASE + "RAG": 0.8, BASE + "LangGraph": 0.7},
        multi_interests=[{
            "concept_id": BASE + "ArtificialIntelligence", "label": "人工智能", "weight": 0.9,
            "concepts": [
                {"concept_id": BASE + concept, "weight": 0.75}
                for concept, _ in TOPICS
            ],
        }],
    )
    candidates = []
    for index in range(candidates_count):
        concept, label = TOPICS[index % len(TOPICS)]
        candidates.append({
            "bvid": f"BVPM{index:08d}", "title": f"{label} 工程实践 {index}",
            "recall_tag": label, "recall_category": "知识", "recall_source": "interest",
            "raw_recall_score": 0.55 + (index % 20) / 50,
            "calibrated_recall_score": 0.55 + (index % 20) / 50,
            "mid": index % 70, "play": 10000 + index * 100,
            "duration": 300 + index % 900, "pubdate": now - timedelta(days=index % 60),
            "description": "已补全简介", "tags": [label], "hydration_status": "success",
            "concept_ids": [BASE + concept],
            "concepts": [{
                "concept_id": BASE + concept,
                "label": label,
                "confidence": 0.98,
            }],
        })
    durations = []
    for _ in range(iterations):
        started = time.perf_counter()
        ranked = score_candidates(candidates, profile, now=now)
        output = diversify(ranked, limit=20)
        if len(output) != 20:
            raise RuntimeError("Ranking benchmark returned an incomplete list")
        durations.append((time.perf_counter() - started) * 1000)
    metrics = {
        "iterations": iterations, "hydrated_candidates": candidates_count,
        "average_ms": round(statistics.mean(durations), 6),
        "p95_ms": round(percentile(durations, 0.95), 6),
        "maximum_ms": round(max(durations), 6),
    }
    return {
        "schema_version": "1.0", "benchmark": "local_hydrated_candidate_ranking",
        "metrics": metrics, "threshold_p95_ms": 300.0,
        "passed": metrics["p95_ms"] <= 300.0,
        "limitations": "Local deterministic ranking only; excludes network hydration and remote LLM latency.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=40)
    parser.add_argument("--candidates", type=int, default=200)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "evaluation" / "local-performance.json")
    args = parser.parse_args()
    report = benchmark(args.iterations, args.candidates)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
