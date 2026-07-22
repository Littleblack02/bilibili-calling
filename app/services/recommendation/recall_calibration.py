"""Put heterogeneous recall-channel scores onto an auditable common scale."""
from __future__ import annotations

import math
from typing import Any


SOURCE_PRIORS: dict[str, float] = {
    "context_query": 0.90,
    "recent_interest": 0.82,
    "series_update": 0.76,
    "followed_up": 0.74,
    "interest": 0.70,
    "vector_rediscovery": 0.68,
    "dynamic_following": 0.62,
    "category": 0.54,
    "trending": 0.44,
}


def _finite(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _interpolate(points: list[tuple[float, float]], raw: float) -> float:
    points = sorted((float(x), float(y)) for x, y in points)
    if not points:
        return 0.0
    if raw <= points[0][0]:
        return points[0][1]
    if raw >= points[-1][0]:
        return points[-1][1]
    for (left_x, left_y), (right_x, right_y) in zip(points, points[1:]):
        if left_x <= raw <= right_x:
            width = right_x - left_x
            ratio = 0.0 if width <= 0 else (raw - left_x) / width
            return left_y + ratio * (right_y - left_y)
    return points[-1][1]


def calibrate_recall_candidates(
    candidates: list[dict[str, Any]],
    learned_curves: dict[str, list[tuple[float, float]]] | None = None,
) -> list[dict[str, Any]]:
    """Calibrate source evidence without comparing raw channel scales.

    A learned monotonic curve can be supplied per channel once time-split
    exposure/click/favorite data is sufficient. Until then a conservative
    explicit source prior is used and the result is marked uncalibrated.
    """
    learned_curves = learned_curves or {}
    calibrated_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        evidence = candidate.get("recall_evidence")
        if not isinstance(evidence, list) or not evidence:
            sources = candidate.get("recall_sources") or [
                candidate.get("recall_source", "unknown")
            ]
            evidence = [{
                "source": source,
                "raw_score": candidate.get("raw_recall_score"),
            } for source in sources]

        scored_evidence: list[dict[str, Any]] = []
        for row in evidence:
            source = str(row.get("source") or "unknown")
            raw = _finite(row.get("raw_score"))
            curve = learned_curves.get(source)
            if curve:
                score = _interpolate(curve, raw)
                method = "learned_piecewise"
                calibrated = True
            else:
                prior = SOURCE_PRIORS.get(source, 0.50)
                # Raw values only make a small within-source confidence
                # adjustment; they never establish cross-source scale.
                bounded_raw = max(0.0, raw) / (1.0 + max(0.0, raw))
                score = prior * (0.85 + 0.15 * bounded_raw)
                method = "explicit_prior"
                calibrated = False
            scored_evidence.append({
                **row,
                "source": source,
                "raw_score": raw,
                "calibrated_score": round(max(0.0, min(1.0, score)), 6),
                "calibration_method": method,
                "calibrated": calibrated,
            })

        scores = sorted(
            (row["calibrated_score"] for row in scored_evidence), reverse=True
        )
        best = scores[0] if scores else 0.0
        corroboration = 1.0 - math.prod(1.0 - score for score in scores[1:])
        combined = min(1.0, best + 0.10 * corroboration)
        calibrated_candidates.append({
            **candidate,
            "recall_evidence": scored_evidence,
            "calibrated_recall_score": round(combined, 6),
            "recall_score_calibrated": bool(scored_evidence) and all(
                row["calibrated"] for row in scored_evidence
            ),
        })
    return calibrated_candidates
