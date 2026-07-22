"""Generate the deterministic synthetic/editorial Grounded-RAG gold set."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from rdflib import Graph, Namespace, RDF, SKOS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.ontology import get_ontology_service


ROOT = Path(__file__).resolve().parents[1]
BILI = Namespace("https://bilibili.local/ontology/")
DOMAINS = ("ai", "game", "animation", "music", "film", "knowledge", "life")


def _concepts(domain: str) -> list[dict[str, object]]:
    graph = Graph().parse(ROOT / "ontology" / "domains" / f"{domain}.ttl")
    rows = []
    for subject in sorted(set(graph.subjects(RDF.type, SKOS.Concept)), key=str):
        if not str(subject).startswith(str(BILI)) or not list(graph.objects(subject, SKOS.broader)):
            continue
        labels = list(graph.objects(subject, SKOS.prefLabel))
        if not labels:
            continue
        topic = next((str(label) for label in labels if label.language == "zh"), str(labels[0]))
        aliases = sorted({str(label) for label in graph.objects(subject, SKOS.altLabel)})
        rows.append({"concept_id": str(subject), "topic": topic, "aliases": aliases})
    return rows


def generate(output_dir: Path) -> dict[str, object]:
    concepts = []
    seen_ids: set[str] = set()
    seen_labels: set[str] = set()
    for domain in DOMAINS:
        selected = []
        for row in _concepts(domain):
            concept_id = str(row["concept_id"])
            label = str(row["topic"]).casefold()
            if concept_id in seen_ids or label in seen_labels:
                continue
            selected.append(row)
            seen_ids.add(concept_id)
            seen_labels.add(label)
            if len(selected) == 6:
                break
        if len(selected) != 6:
            raise RuntimeError(f"Unable to select six unique concepts for {domain}")
        concepts.extend(selected)
    ontology = get_ontology_service()
    alias_counts: dict[str, int] = {}
    for concept in concepts:
        for alias in set(concept["aliases"]):
            alias_counts[str(alias).casefold()] = alias_counts.get(str(alias).casefold(), 0) + 1
    chunks: list[dict[str, object]] = []
    questions: list[dict[str, object]] = []
    for concept_index, concept in enumerate(concepts):
        bvids = [f"BVQA{concept_index * 3 + slot + 1:08d}" for slot in range(3)]
        topic = str(concept["topic"])
        concept_id = str(concept["concept_id"])
        texts = [
            f"{topic}的证据核对流程包括确认来源、记录版本、再执行步骤，并明确避免跳过验证。",
            f"{topic}实践片段在六十秒记录输入，在九十秒核对输出，时间点必须随引用一起保存。",
            f"{topic}复盘片段要求比较预期和实际、保留可追溯引用，并记录差异产生的原因。",
        ]
        for slot, (bvid, content) in enumerate(zip(bvids, texts)):
            chunks.append({
                "schema_version": "1.0", "bvid": bvid,
                "title": f"{topic}实践课程·第{slot + 1}段", "chunk_index": slot,
                "start_time": float(slot * 60), "end_time": float(slot * 60 + 45),
                "concept_ids": [concept_id], "content": content,
            })

        mention = topic
        aliases = []
        for alias in concept["aliases"]:
            linked = ontology.link_text_v2(str(alias), limit=3).get("selected") or []
            if (
                alias_counts.get(str(alias).casefold()) == 1
                and linked and linked[0]["concept_id"] == concept_id
            ):
                aliases.append(str(alias))
        if aliases:
            # Keep the canonical label as disambiguating context. The alias is
            # still exercised, without turning a broad short alias (for
            # example AI) into an inherently under-specified gold question.
            mention = f"{aliases[concept_index % len(aliases)]}（{topic}）"
        base = concept_index * 3
        split = ("train", "dev", "test")[concept_index % 3]
        questions.extend([
            {
                "schema_version": "1.0", "id": f"qa-rag-{base + 1:03d}", "split": split,
                "question": f"{topic}的证据核对流程为什么要确认来源、记录版本并避免跳过验证？",
                "answerable": True, "expected_bvids": [bvids[0]], "expected_chunk_indexes": [0],
                "expected_citation_ids": [f"{bvids[0]}#0"],
                "key_facts": ["确认来源", "记录版本", "避免跳过验证"],
                "question_type": "negation" if concept_index % 2 else "direct",
            },
            {
                "schema_version": "1.0", "id": f"qa-rag-{base + 2:03d}", "split": split,
                "question": f"资料在什么时间点讲到{mention}记录输入和核对输出？",
                "answerable": True, "expected_bvids": [bvids[1]], "expected_chunk_indexes": [1],
                "expected_citation_ids": [f"{bvids[1]}#1"],
                "key_facts": ["六十秒", "九十秒", "时间点"],
                "question_type": "synonym" if aliases else "timestamp",
            },
            {
                "schema_version": "1.0", "id": f"qa-rag-{base + 3:03d}", "split": split,
                "question": f"结合{topic}的实践和复盘片段，怎样记录输入、核对输出并比较预期和实际？",
                "answerable": True, "expected_bvids": [bvids[1], bvids[2]],
                "expected_chunk_indexes": [1, 2],
                "expected_citation_ids": [f"{bvids[1]}#1", f"{bvids[2]}#2"],
                "key_facts": ["记录输入", "核对输出", "比较预期和实际"],
                "question_type": "cross_video",
            },
        ])

    # 24 questions mention a known topic but request facts absent from every
    # chunk, covering the dangerous "topic match but no answer" case.
    for index in range(24):
        concept = concepts[index % len(concepts)]
        questions.append({
            "schema_version": "1.0", "id": f"qa-rag-{127 + index:03d}",
            "split": "test", "question": f"资料是否给出了{concept['topic']}讲解者的身份证号码和家庭住址？",
            "answerable": False, "expected_bvids": [], "expected_chunk_indexes": [],
            "expected_citation_ids": [], "key_facts": [], "question_type": "unanswerable",
        })

    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, rows in (("rag_chunks.jsonl", chunks), ("rag_qa.jsonl", questions)):
        (output_dir / filename).write_text(
            "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
            encoding="utf-8",
        )
    lock = {
        "schema_version": "1.0",
        "dataset_kind": "deterministic_synthetic_editorial",
        "questions": len(questions), "answerable": sum(row["answerable"] for row in questions),
        "unanswerable": sum(not row["answerable"] for row in questions), "gold_chunks": len(chunks),
        "benchmark_chunk_count": 10000,
        "sha256": {
            name: hashlib.sha256((output_dir / name).read_bytes()).hexdigest()
            for name in ("rag_chunks.jsonl", "rag_qa.jsonl")
        },
        "limitations": "Synthetic extractive regression fixture; no remote LLM and no live user knowledge base.",
    }
    (output_dir / "rag.lock.json").write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return lock


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evaluation")
    args = parser.parse_args()
    print(json.dumps(generate(args.output_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
