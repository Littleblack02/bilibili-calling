"""Strict time-split temporal recommendation evaluation with ablations and CIs."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import random
from statistics import mean
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.schemas import RecommendationEventExample, RecommendationItemExample
from app.services.ontology import get_ontology_service


ROOT = Path(__file__).resolve().parents[1]
POSITIVE = {"viewed", "favorite", "watch_later", "like", "click"}
EVENT_VALUE = {"favorite": 3.0, "like": 2.0, "watch_later": 1.5, "viewed": 1.0, "click": 0.5}
HALF_LIFE = {"favorite": 90.0, "like": 45.0, "watch_later": 30.0, "viewed": 14.0, "click": 7.0}
VARIANTS: dict[str, dict[str, Any]] = {
    "baseline_v1": {"temporal": False, "ontology": False, "clusters": False, "hydration": False, "dynamic": False, "diversity": 0.0},
    "full_v2": {"temporal": True, "ontology": True, "clusters": True, "hydration": True, "dynamic": True, "diversity": 0.25},
    "no_time": {"temporal": False, "ontology": True, "clusters": True, "hydration": True, "dynamic": True, "diversity": 0.25},
    "no_ontology": {"temporal": True, "ontology": False, "clusters": True, "hydration": True, "dynamic": True, "diversity": 0.25},
    "no_clusters": {"temporal": True, "ontology": True, "clusters": False, "hydration": True, "dynamic": True, "diversity": 0.25},
    "no_hydration": {"temporal": True, "ontology": True, "clusters": True, "hydration": False, "dynamic": True, "diversity": 0.25},
    "no_dynamic": {"temporal": True, "ontology": True, "clusters": True, "hydration": True, "dynamic": False, "diversity": 0.25},
    "weights_relevance": {"temporal": True, "ontology": True, "clusters": True, "hydration": True, "dynamic": True, "diversity": 0.03, "interest_weight": 1.35, "quality_weight": 0.28},
    "weights_diversity": {"temporal": True, "ontology": True, "clusters": True, "hydration": True, "dynamic": True, "diversity": 0.45, "interest_weight": 1.05, "quality_weight": 0.40},
}


def _dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _load_jsonl(path: Path, schema: Any) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                rows.append(schema.model_validate_json(line).model_dump(mode="json"))
    return rows


def _ndcg(ranking: list[str], relevant: set[str], k: int) -> float:
    dcg = sum((1.0 / math.log2(index + 2)) for index, item in enumerate(ranking[:k]) if item in relevant)
    ideal = sum(1.0 / math.log2(index + 2) for index in range(min(k, len(relevant))))
    return dcg / ideal if ideal else 0.0


def _ild(rows: list[dict[str, Any]]) -> float:
    if len(rows) < 2:
        return 0.0
    distances = []
    for left_index, left in enumerate(rows):
        for right in rows[left_index + 1:]:
            if left["concept_id"] == right["concept_id"]:
                distances.append(0.0)
            elif left["domain"] == right["domain"]:
                distances.append(0.55)
            else:
                distances.append(1.0)
    return mean(distances)


class Evaluator:
    def __init__(self, items: list[dict[str, Any]], events: list[dict[str, Any]], cutoff: datetime, seed: int):
        self.items = items
        self.events = events
        self.cutoff = cutoff
        self.seed = seed
        self.ontology = get_ontology_service()
        self.topic_concepts: dict[str, str | None] = {}
        self.by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in events:
            self.by_session[event["session_hash"]].append(event)
        self.total_concepts = len({row["concept_id"] for row in items})
        self._validate_protocol()

    def _validate_protocol(self) -> None:
        if not self.items or not self.events:
            raise ValueError("Recommendation evaluation requires items and events")
        if any(_dt(item["published_at"]) >= self.cutoff for item in self.items):
            raise ValueError("Candidate published at or after cutoff (future catalog leakage)")
        for session, rows in self.by_session.items():
            ordered = [_dt(row["event_time"]) for row in rows]
            if not any(value < self.cutoff for value in ordered):
                raise ValueError(f"Session {session} has no history before cutoff")
            if not any(value >= self.cutoff and row["event_type"] in POSITIVE for value, row in zip(ordered, rows)):
                raise ValueError(f"Session {session} has no future target")

    def _concept(self, topic: str | None) -> str | None:
        topic = str(topic or "")
        if topic not in self.topic_concepts:
            result = self.ontology.link_text_v2(topic, limit=3)
            selected = result.get("selected") or []
            self.topic_concepts[topic] = selected[0]["concept_id"] if selected else None
        return self.topic_concepts[topic]

    def _rank(self, history: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
        affinity: dict[str, float] = defaultdict(float)
        creator_affinity: dict[str, float] = defaultdict(float)
        for event in history:
            if event["event_type"] not in POSITIVE:
                continue
            value = EVENT_VALUE.get(event["event_type"], 0.0)
            if config["temporal"]:
                age = max(0.0, (self.cutoff - _dt(event["event_time"])).total_seconds() / 86400)
                half_life = HALF_LIFE.get(event["event_type"], 30.0)
                value *= 0.05 + 0.95 * (2 ** (-age / half_life))
            key = self._concept(event.get("topic")) if config["ontology"] else str(event.get("topic") or "").casefold()
            if key:
                affinity[key] += value
            if event.get("up_mid_hash"):
                creator_affinity[event["up_mid_hash"]] += value

        if not affinity:
            affinity["__cold_start__"] = 0.0
        ordered_affinity = sorted(affinity.items(), key=lambda row: (-row[1], row[0]))
        allowed = {ordered_affinity[0][0]} if not config["clusters"] else {row[0] for row in ordered_affinity[:3]}
        maximum = max(value for _, value in ordered_affinity) or 1.0
        creator_max = max(creator_affinity.values(), default=1.0) or 1.0
        seen = {event["bvid"] for event in history if event["event_type"] in POSITIVE}
        scored = []
        for item in self.items:
            if item["bvid"] in seen:
                continue
            item_key = item["concept_id"] if config["ontology"] else str(item["topic"]).casefold()
            interest = affinity.get(item_key, 0.0) / maximum if item_key in allowed else 0.0
            score = interest * float(config.get("interest_weight", 1.15))
            score += float(item["popularity"]) * 0.08
            if config["hydration"]:
                score += float(item["quality"]) * float(config.get("quality_weight", 0.42))
                score += (1.0 - float(item["popularity"])) * 0.04
            if config["dynamic"]:
                score += creator_affinity.get(item["up_mid_hash"], 0.0) / creator_max * 0.30
                if item["recall_source"] in {"followed_up", "dynamic_feed"}:
                    score += 0.035
            scored.append({**item, "score": score})

        selected: list[dict[str, Any]] = []
        remaining = scored
        while remaining and len(selected) < 20:
            used_domains = {row["domain"] for row in selected}
            counts: dict[str, int] = defaultdict(int)
            for row in selected:
                counts[row["concept_id"]] += 1
            best = max(
                remaining,
                key=lambda row: (
                    row["score"]
                    - float(config["diversity"]) * counts[row["concept_id"]]
                    + (0.025 if row["domain"] not in used_domains else 0.0),
                    row["bvid"],
                ),
            )
            selected.append(best)
            remaining.remove(best)
        return selected

    def evaluate_variant(self, config: dict[str, Any]) -> tuple[dict[str, float], list[dict[str, Any]]]:
        sessions: list[dict[str, Any]] = []
        for session_hash in sorted(self.by_session):
            all_rows = self.by_session[session_hash]
            history = [row for row in all_rows if _dt(row["event_time"]) < self.cutoff]
            relevant = {
                row["bvid"] for row in all_rows
                if _dt(row["event_time"]) >= self.cutoff and row["event_type"] in POSITIVE
            }
            ranked_rows = self._rank(history, config)
            ranking = [row["bvid"] for row in ranked_rows]
            hits20 = len(set(ranking[:20]) & relevant)
            first = next((index + 1 for index, bvid in enumerate(ranking) if bvid in relevant), None)
            latest = max(_dt(row["event_time"]) for row in history)
            age = (self.cutoff - latest).total_seconds() / 86400
            activity = len([row for row in history if row["event_type"] in POSITIVE])
            target_domains = [row["domain"] for row in self.items if row["bvid"] in relevant]
            target_concepts = {row["concept_id"] for row in self.items if row["bvid"] in relevant}
            recommended_concepts = {row["concept_id"] for row in ranked_rows}
            sessions.append({
                "session_hash": session_hash,
                "recall_at_20": hits20 / len(relevant),
                "ndcg_at_10": _ndcg(ranking, relevant, 10),
                "mrr_at_10": (1.0 / first) if first and first <= 10 else 0.0,
                "hit_rate_at_10": 1.0 if set(ranking[:10]) & relevant else 0.0,
                "novelty": mean(1.0 - float(row["popularity"]) for row in ranked_rows),
                "ild": _ild(ranked_rows),
                # Coverage is measured over held-out relevant topics. Randomly
                # scattering irrelevant categories must not score as useful
                # topic coverage.
                "topic_coverage": len(recommended_concepts & target_concepts) / len(target_concepts),
                "recommended": ranking,
                "activity_bucket": "low" if activity <= 8 else ("medium" if activity <= 11 else "high"),
                "freshness_bucket": "recent" if age <= 7 else ("aging" if age <= 25 else "stale"),
                "domain_bucket": sorted(target_domains)[0],
            })
        metrics = self._aggregate(sessions)
        metrics["coverage"] = len({bvid for row in sessions for bvid in row["recommended"]}) / len(self.items)
        return metrics, sessions

    @staticmethod
    def _aggregate(rows: list[dict[str, Any]]) -> dict[str, float]:
        fields = ("recall_at_20", "ndcg_at_10", "mrr_at_10", "hit_rate_at_10", "novelty", "ild", "topic_coverage")
        return {field: mean(float(row[field]) for row in rows) if rows else 0.0 for field in fields}

    def bootstrap_ci(self, rows: list[dict[str, Any]], iterations: int = 500) -> dict[str, list[float]]:
        rng = random.Random(self.seed)
        fields = ("recall_at_20", "ndcg_at_10", "mrr_at_10", "hit_rate_at_10", "novelty", "ild", "topic_coverage")
        samples = {field: [] for field in fields}
        for _ in range(iterations):
            sample = [rows[rng.randrange(len(rows))] for _ in rows]
            aggregate = self._aggregate(sample)
            for field in fields:
                samples[field].append(aggregate[field])
        result = {}
        for field, values in samples.items():
            values.sort()
            result[field] = [values[int(iterations * 0.025)], values[min(iterations - 1, int(iterations * 0.975))]]
        return result

    def buckets(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for field in ("activity_bucket", "freshness_bucket", "domain_bucket"):
            groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                groups[row[field]].append(row)
            output[field] = {
                key: {"sessions": len(values), **self._aggregate(values)}
                for key, values in sorted(groups.items())
            }
        return output


def _relative(current: float, baseline: float) -> float:
    return ((current - baseline) / baseline) if baseline > 0 else (math.inf if current > 0 else 0.0)


def evaluate(data_dir: Path, cutoff: datetime, seed: int = 20260721, bootstrap: int = 500) -> dict[str, Any]:
    items_path = data_dir / "recommendation_items.jsonl"
    events_path = data_dir / "recommendation_events.jsonl"
    items = _load_jsonl(items_path, RecommendationItemExample)
    events = _load_jsonl(events_path, RecommendationEventExample)
    evaluator = Evaluator(items, events, cutoff, seed)
    variants = {}
    session_rows = {}
    for name, config in VARIANTS.items():
        metrics, rows = evaluator.evaluate_variant(config)
        variants[name] = {
            "config": config,
            "metrics": {key: round(value, 6) for key, value in metrics.items()},
            "confidence_interval_95": {
                key: [round(bound, 6) for bound in bounds]
                for key, bounds in evaluator.bootstrap_ci(rows, bootstrap).items()
            },
        }
        session_rows[name] = rows
    baseline = variants["baseline_v1"]["metrics"]
    full = variants["full_v2"]["metrics"]
    gains = {
        "ndcg_at_10": _relative(full["ndcg_at_10"], baseline["ndcg_at_10"]),
        "recall_at_20": _relative(full["recall_at_20"], baseline["recall_at_20"]),
        "hit_rate_at_10": _relative(full["hit_rate_at_10"], baseline["hit_rate_at_10"]),
        "topic_coverage": _relative(full["topic_coverage"], baseline["topic_coverage"]),
    }
    gates = {
        "ndcg_relative_gain_gte_10pct": gains["ndcg_at_10"] >= 0.10,
        "recall_relative_gain_gte_8pct": gains["recall_at_20"] >= 0.08,
        "hit_rate_relative_gain_gte_8pct": gains["hit_rate_at_10"] >= 0.08,
        "ild_not_lower": full["ild"] >= baseline["ild"],
        "topic_coverage_relative_gain_gte_10pct": gains["topic_coverage"] >= 0.10,
    }
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now().astimezone().isoformat(),
        "dataset_kind": "deterministic_synthetic_editorial",
        "claim_scope": "Offline engineering regression only; not live traffic and not causal online uplift.",
        "protocol": {
            "cutoff": cutoff.isoformat(),
            "seed": seed,
            "bootstrap_iterations": bootstrap,
            "sessions": len(evaluator.by_session),
            "candidate_count": len(items),
            "candidate_set_sha256": hashlib.sha256(items_path.read_bytes()).hexdigest(),
            "future_behavior_used_for_profile": False,
            "candidates_published_before_cutoff": True,
        },
        "variants": variants,
        "relative_gains": {key: round(value, 6) for key, value in gains.items()},
        "acceptance_gates": gates,
        "passed": all(gates.values()),
        "buckets_full_v2": evaluator.buckets(session_rows["full_v2"]),
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Temporal recommendation offline evaluation",
        "",
        f"**Result:** {'PASS' if report['passed'] else 'FAIL'}",
        "",
        "> This is a deterministic synthetic/editorial regression fixture. It does not prove live Bilibili uplift.",
        "",
        "| Variant | NDCG@10 | Recall@20 | HitRate@10 | MRR@10 | Coverage | Novelty | ILD | Topic coverage |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in report["variants"].items():
        metric = row["metrics"]
        lines.append(
            f"| {name} | {metric['ndcg_at_10']:.4f} | {metric['recall_at_20']:.4f} | "
            f"{metric['hit_rate_at_10']:.4f} | {metric['mrr_at_10']:.4f} | {metric['coverage']:.4f} | "
            f"{metric['novelty']:.4f} | {metric['ild']:.4f} | {metric['topic_coverage']:.4f} |"
        )
    lines.extend(["", "## Acceptance gates", ""])
    for name, passed in report["acceptance_gates"].items():
        lines.append(f"- [{'x' if passed else ' '}] {name}")
    lines.extend(["", "95% confidence intervals and all bucket results are preserved in the JSON report.", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "evaluation")
    parser.add_argument("--cutoff", default="2026-06-01T00:00:00+00:00")
    parser.add_argument("--seed", type=int, default=20260721)
    parser.add_argument("--bootstrap", type=int, default=500)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "evaluation" / "recommendation.json")
    args = parser.parse_args()
    report = evaluate(args.data_dir, _dt(args.cutoff), args.seed, args.bootstrap)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "metrics": report["variants"]["full_v2"]["metrics"], "relative_gains": report["relative_gains"]}, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
