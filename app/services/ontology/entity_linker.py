"""Deterministic cascade entity linker with explicit low-confidence rejection."""
from __future__ import annotations

from collections import Counter
import math
import re
from typing import Any, Callable

from rapidfuzz import fuzz


AMBIGUOUS_HINTS: dict[str, set[str]] = {
    "agent": {"ai", "llm", "langgraph", "langchain", "智能体", "工作流", "工具调用"},
    "java": {"编程", "代码", "spring", "jvm", "后端", "开发", "教程"},
    "ontology": {"知识图谱", "语义网", "rdf", "owl", "skos", "建模", "知识本体"},
}


def _tokens(text: str) -> set[str]:
    normalized = (text or "").casefold()
    latin = set(re.findall(r"[a-z0-9+#.]+", normalized))
    chinese_runs = re.findall(r"[\u4e00-\u9fff]+", normalized)
    chinese = set()
    for run in chinese_runs:
        chinese.add(run)
        for width in (2, 3, 4):
            chinese.update(run[index:index + width] for index in range(max(0, len(run) - width + 1)))
    return latin | chinese


def _char_vector(text: str) -> Counter[str]:
    compact = re.sub(r"\s+", "", (text or "").casefold())
    if len(compact) < 2:
        return Counter({compact: 1}) if compact else Counter()
    return Counter(compact[index:index + 2] for index in range(len(compact) - 1))


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(value * right.get(key, 0) for key, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


class EntityLinker:
    def __init__(
        self,
        concepts: list[dict[str, Any]],
        *,
        normalize: Callable[[str], str],
        accept_threshold: float,
        ambiguity_margin: float,
    ) -> None:
        self.concepts = [row for row in concepts if not row.get("deprecated")]
        self.normalize = normalize
        self.accept_threshold = accept_threshold
        self.ambiguity_margin = ambiguity_margin
        self.labels: list[tuple[str, str, dict[str, Any], bool]] = []
        for concept in self.concepts:
            for index, label in enumerate([concept["label"], *(concept.get("aliases") or [])]):
                normalized = normalize(label)
                if normalized:
                    self.labels.append((normalized, label, concept, index == 0))

    @staticmethod
    def _ascii_present(text: str, label: str) -> bool:
        return bool(re.search(
            rf"(?<![a-z0-9]){re.escape(label.casefold())}(?![a-z0-9])",
            text.casefold(),
        ))

    def link(
        self,
        text: str,
        *,
        context: dict[str, Any] | None = None,
        limit: int = 12,
    ) -> dict[str, Any]:
        original = text or ""
        normalized_text = self.normalize(original)
        if not normalized_text:
            return {"selected": [], "candidates": [], "rejected": True,
                    "rejection_reason": "empty_text", "stage": "reject"}

        context_text = " ".join(str(value) for value in (context or {}).values() if value)
        combined_context = f"{original} {context_text}".casefold()
        query_tokens = _tokens(combined_context)
        query_vector = _char_vector(combined_context)
        candidates: dict[str, dict[str, Any]] = {}

        def add(concept: dict[str, Any], label: str, stage: str, score: float, **scores: Any) -> None:
            row = candidates.get(concept["concept_id"])
            payload = {
                "concept_id": concept["concept_id"], "label": concept["label"],
                "concept_type": concept["concept_type"], "matched_label": label,
                "stage": stage, "confidence": round(max(0.0, min(1.0, score)), 6),
                "scores": scores,
            }
            if row is None or payload["confidence"] > row["confidence"]:
                candidates[concept["concept_id"]] = payload

        # Stage 1: exact preferred/alternative labels and explicit substrings.
        exact_ids: set[str] = set()
        for normalized, label, concept, preferred in self.labels:
            ascii_short = label.isascii() and len(normalized) <= 12
            present = self._ascii_present(original, label) if ascii_short else normalized in normalized_text
            if not present:
                continue
            exact = normalized == normalized_text
            score = 1.0 if exact and preferred else 0.98 if exact else 0.95 if preferred else 0.92
            add(concept, label, "exact_label", score, exact=exact, preferred=preferred)
            exact_ids.add(concept["concept_id"])

        # Stage 2: token overlap + RapidFuzz candidate generation.
        if not exact_ids:
            for normalized, label, concept, preferred in self.labels:
                label_tokens = _tokens(label)
                overlap = (
                    len(query_tokens & label_tokens) / len(label_tokens)
                    if label_tokens else 0.0
                )
                fuzzy = fuzz.WRatio(label.casefold(), original.casefold()) / 100.0
                score = 0.52 * fuzzy + 0.30 * overlap + (0.04 if preferred else 0.0)
                if score >= 0.55:
                    add(concept, label, "fuzzy_lexical", score,
                        fuzzy=round(fuzzy, 6), token_overlap=round(overlap, 6))

        # Stage 3: local vector candidates. This deterministic vector fallback
        # remains available when the optional remote embedding service is off.
        if not exact_ids:
            for _normalized, label, concept, preferred in self.labels:
                similarity = _cosine(query_vector, _char_vector(
                    " ".join([concept["label"], *(concept.get("aliases") or [])])
                ))
                if similarity >= 0.48:
                    add(concept, label, "local_vector", 0.58 + 0.30 * similarity,
                        vector_similarity=round(similarity, 6), preferred=preferred)

        # Stage 4: context-aware disambiguation and ambiguous-label rejection.
        ranked = sorted(candidates.values(), key=lambda row: row["confidence"], reverse=True)
        accepted: list[dict[str, Any]] = []
        ambiguous_rejections: list[str] = []
        for row in ranked:
            matched = row["matched_label"].casefold()
            hints = AMBIGUOUS_HINTS.get(matched)
            if hints:
                support = [hint for hint in hints if hint in combined_context]
                if not support:
                    ambiguous_rejections.append(row["concept_id"])
                    row["rejected_reason"] = "ambiguous_label_without_context"
                    continue
                row["confidence"] = round(min(1.0, row["confidence"] + 0.02 * len(support)), 6)
                row["context_hints"] = support
            if row["confidence"] >= self.accept_threshold:
                accepted.append(row)

        # Exact multi-entity texts may select all supported mentions. Approximate
        # matching selects one only when the top candidate has a safe margin.
        if exact_ids:
            exact_rows = [row for row in accepted if row["concept_id"] in exact_ids]
            # Longest-match suppression prevents “影视剪辑” from also emitting
            # the broad “影视” concept for the same lexical span.
            selected = [
                row for row in exact_rows
                if not any(
                    self.normalize(row["matched_label"])
                    != self.normalize(other["matched_label"])
                    and self.normalize(row["matched_label"])
                    in self.normalize(other["matched_label"])
                    for other in exact_rows
                )
            ][:limit]
        else:
            selected = accepted[:1]
            if len(accepted) > 1 and (
                accepted[0]["confidence"] - accepted[1]["confidence"]
                < self.ambiguity_margin
            ):
                selected = []

        if selected:
            return {
                "selected": selected,
                "candidates": ranked[:limit],
                "rejected": False,
                "rejection_reason": None,
                "stage": selected[0]["stage"],
            }
        reason = (
            "ambiguous_label_without_context" if ambiguous_rejections
            else "ambiguous_candidates" if accepted
            else "below_confidence_threshold" if ranked
            else "no_candidate"
        )
        return {
            "selected": [], "candidates": ranked[:limit], "rejected": True,
            "rejection_reason": reason, "stage": "reject",
        }
