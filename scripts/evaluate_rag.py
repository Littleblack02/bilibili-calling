"""Evaluate Grounded RAG retrieval, citations, refusal and local latency."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.documents import Document

from app.evaluation.schemas import RagChunkExample, RagQaExample
from app.services.rag_grounded import (
    GroundedRetriever, build_grounded_context, citation_id,
    grounded_refusal, verify_answer_citations,
)


ROOT = Path(__file__).resolve().parents[1]


def _tokens(text: str) -> set[str]:
    normalized = (text or "").casefold()
    latin = set(re.findall(r"[a-z0-9_]+", normalized))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    return latin | set(chinese) | {
        chinese[index:index + 2] for index in range(max(0, len(chinese) - 1))
    }


class LocalLexicalVectorStore:
    """A deterministic score-bearing local index used by the offline harness."""

    def __init__(self, documents: list[Document]):
        self.documents = documents
        self.tokens = [_tokens(document.page_content) for document in documents]
        self.index: dict[str, set[int]] = defaultdict(set)
        for index, tokens in enumerate(self.tokens):
            for token in tokens:
                self.index[token].add(index)

    def similarity_search_with_relevance_scores(
        self, query: str, k: int = 5, filter: dict[str, Any] | None = None
    ) -> list[tuple[Document, float]]:
        query_tokens = _tokens(query)
        candidates: set[int] = set()
        for token in query_tokens:
            candidates.update(self.index.get(token, set()))
        allowed = None
        if filter and isinstance(filter.get("bvid"), dict):
            allowed = set(filter["bvid"].get("$in") or [])
        scored = []
        for index in candidates:
            document = self.documents[index]
            if allowed is not None and document.metadata.get("bvid") not in allowed:
                continue
            overlap = len(query_tokens & self.tokens[index])
            coverage = overlap / len(query_tokens) if query_tokens else 0.0
            precision = overlap / len(self.tokens[index]) if self.tokens[index] else 0.0
            score = min(1.0, 0.84 * coverage + 0.16 * min(1.0, precision * 2.0))
            scored.append((document, score))
        scored.sort(key=lambda row: (-row[1], citation_id(row[0])))
        return scored[:k]


def _load(path: Path, schema: Any) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [schema.model_validate_json(line).model_dump(mode="json") for line in stream if line.strip()]


def _documents(rows: list[dict[str, Any]], benchmark_chunks: int) -> list[Document]:
    documents = [Document(
        page_content=row["content"],
        metadata={
            "bvid": row["bvid"], "title": row["title"],
            "chunk_index": row["chunk_index"], "start_time": row["start_time"],
            "end_time": row["end_time"], "concept_ids": json.dumps(row["concept_ids"]),
        },
    ) for row in rows]
    for index in range(len(documents), benchmark_chunks):
        documents.append(Document(
            page_content=f"合成背景干扰片段 {index}：设备巡检批次只记录无关校验码 D{index:05d}。",
            metadata={
                "bvid": f"BVDX{index:08d}", "title": "背景干扰资料",
                "chunk_index": 0, "start_time": 0.0, "end_time": 30.0,
                "concept_ids": "[]",
            },
        ))
    return documents


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1)]


def _answer(question: str, docs: list[Document], support_floor: float = 0.28) -> dict[str, Any]:
    if not docs:
        return grounded_refusal("no_result_above_threshold")
    max_coverage = max(float(doc.metadata.get("rerank_query_coverage", 0.0)) for doc in docs)
    if max_coverage < support_floor:
        return grounded_refusal("query_evidence_coverage_below_threshold")
    evidence_limit = 2 if any(marker in question for marker in ("结合", "分别", "对比")) else 1
    eligible = [
        doc for doc in docs
        if float(doc.metadata.get("rerank_query_coverage", 0.0)) >= max(support_floor, max_coverage - 0.16)
    ]
    # Greedily cover new query terms. For multi-chunk questions this avoids
    # citing a second near-duplicate when another chunk supplies the missing
    # half of the requested evidence.
    selected: list[Document] = []
    uncovered = _tokens(question)
    while eligible and len(selected) < evidence_limit:
        best = max(
            eligible,
            key=lambda doc: (
                len(_tokens(doc.page_content) & uncovered),
                float(doc.metadata.get("rerank_score", 0.0)),
                citation_id(doc),
            ),
        )
        selected.append(best)
        uncovered -= _tokens(best.page_content)
        eligible.remove(best)
    _, citations = build_grounded_context(selected)
    answer = " ".join(
        f"{document.page_content} [{citation['citation_id']}]"
        for document, citation in zip(selected, citations)
    )
    verification = verify_answer_citations(answer, citations)
    if not verification["valid"]:
        return grounded_refusal(f"citation_{verification['reason']}")
    return {
        "answer": answer, "grounded": True, "answerability": "answerable",
        "citations": citations, "sources": citations,
        "citation_verification": verification,
    }


def evaluate(data_dir: Path, benchmark_chunks: int = 10000) -> dict[str, Any]:
    qa_path = data_dir / "rag_qa.jsonl"
    chunk_path = data_dir / "rag_chunks.jsonl"
    questions = _load(qa_path, RagQaExample)
    chunk_rows = _load(chunk_path, RagChunkExample)
    documents = _documents(chunk_rows, benchmark_chunks)
    retriever = GroundedRetriever(LocalLexicalVectorStore(documents))
    retrieval_recalls = []
    reciprocal_ranks = []
    cited_expected = 0
    cited_total = 0
    grounded_facts = 0
    total_facts = 0
    answerable_count = 0
    grounded_answerable = 0
    unanswerable_count = 0
    correct_refusals = 0
    hallucinations = 0
    latencies = []
    by_type: dict[str, list[dict[str, float]]] = defaultdict(list)
    examples = []

    for row in questions:
        started = time.perf_counter()
        docs = retriever.search(row["question"], k=10)
        latencies.append((time.perf_counter() - started) * 1000)
        result = _answer(row["question"], docs[:10])
        ranked_ids = [citation_id(document) for document in docs]
        expected = set(row["expected_citation_ids"])
        if row["answerable"]:
            answerable_count += 1
            found = len(expected & set(ranked_ids[:5]))
            recall = found / len(expected) if expected else 0.0
            retrieval_recalls.append(recall)
            first = next((index + 1 for index, value in enumerate(ranked_ids[:10]) if value in expected), None)
            reciprocal_ranks.append(1.0 / first if first else 0.0)
            used = {citation["citation_id"] for citation in result.get("citations", [])}
            cited_expected += len(used & expected)
            cited_total += len(used)
            answer_text = result.get("answer", "")
            facts = row["key_facts"]
            grounded = sum(1 for fact in facts if fact in answer_text)
            grounded_facts += grounded
            total_facts += len(facts)
            if result.get("grounded"):
                grounded_answerable += 1
            else:
                hallucinations += 1
            by_type[row["question_type"]].append({"recall": recall, "rr": 1.0 / first if first else 0.0})
        else:
            unanswerable_count += 1
            if not result.get("grounded") and result.get("answerability") == "insufficient_evidence":
                correct_refusals += 1
            else:
                hallucinations += 1
        if len(examples) < 12:
            examples.append({
                "id": row["id"], "type": row["question_type"], "answerable": row["answerable"],
                "retrieved": ranked_ids[:5], "expected": sorted(expected),
                "grounded": bool(result.get("grounded")),
                "answerability": result.get("answerability"),
            })

    metrics = {
        "retrieval_recall_at_5": sum(retrieval_recalls) / len(retrieval_recalls),
        "retrieval_mrr_at_10": sum(reciprocal_ranks) / len(reciprocal_ranks),
        "citation_correctness": cited_expected / cited_total if cited_total else 0.0,
        "groundedness": grounded_facts / total_facts if total_facts else 0.0,
        "answerable_grounded_rate": grounded_answerable / answerable_count if answerable_count else 0.0,
        "unanswerable_refusal_rate": correct_refusals / unanswerable_count if unanswerable_count else 0.0,
        "factual_hallucination_rate": hallucinations / len(questions),
        "retrieval_latency_p50_ms": _percentile(latencies, 0.50),
        "retrieval_latency_p95_ms": _percentile(latencies, 0.95),
    }
    gates = {
        "qa_count_120_to_200": 120 <= len(questions) <= 200,
        "recall_at_5_gte_085": metrics["retrieval_recall_at_5"] >= 0.85,
        "mrr_at_10_gte_075": metrics["retrieval_mrr_at_10"] >= 0.75,
        "citation_correctness_gte_095": metrics["citation_correctness"] >= 0.95,
        "groundedness_gte_090": metrics["groundedness"] >= 0.90,
        "refusal_rate_gte_090": metrics["unanswerable_refusal_rate"] >= 0.90,
        "hallucination_rate_lte_005": metrics["factual_hallucination_rate"] <= 0.05,
        "local_retrieval_p95_lte_800ms": metrics["retrieval_latency_p95_ms"] <= 800.0,
    }
    return {
        "schema_version": "1.0", "generated_at": __import__("datetime").datetime.now().astimezone().isoformat(),
        "dataset_kind": "deterministic_synthetic_editorial",
        "claim_scope": "Local lexical/extractive Grounded-RAG engineering regression; no remote LLM or live collection.",
        "dataset": {
            "questions": len(questions), "answerable": answerable_count,
            "unanswerable": unanswerable_count, "gold_chunks": len(chunk_rows),
            "benchmark_chunks": len(documents),
            "qa_sha256": hashlib.sha256(qa_path.read_bytes()).hexdigest(),
            "chunks_sha256": hashlib.sha256(chunk_path.read_bytes()).hexdigest(),
        },
        "metrics": {key: round(value, 6) for key, value in metrics.items()},
        "by_question_type": {
            key: {
                "count": len(values),
                "recall_at_5": round(sum(value["recall"] for value in values) / len(values), 6),
                "mrr_at_10": round(sum(value["rr"] for value in values) / len(values), 6),
            } for key, values in sorted(by_type.items())
        },
        "acceptance_gates": gates, "passed": all(gates.values()), "examples": examples,
        "limitations": [
            "Synthetic/editorial content does not estimate live-domain quality.",
            "Answer metrics use a deterministic extractive path; remote generative-LLM quality is not claimed.",
            "Latency covers the local sparse score-bearing index and GroundedRetriever, not Chroma or remote LLM time.",
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    m = report["metrics"]
    lines = [
        "# Grounded RAG offline evaluation", "",
        f"**Result:** {'PASS' if report['passed'] else 'FAIL'}", "",
        "> Deterministic synthetic/editorial, local extractive regression only; this is not a live-domain or remote-LLM claim.", "",
        "| Metric | Value |", "|---|---:|",
    ]
    for key, value in m.items():
        lines.append(f"| {key} | {value:.6f} |")
    lines.extend(["", "## Acceptance gates", ""])
    lines.extend(f"- [{'x' if value else ' '}] {key}" for key, value in report["acceptance_gates"].items())
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "evaluation")
    parser.add_argument("--benchmark-chunks", type=int, default=10000)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "evaluation" / "rag.json")
    args = parser.parse_args()
    report = evaluate(args.data_dir, args.benchmark_chunks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.with_suffix(".md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "metrics": report["metrics"]}, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
