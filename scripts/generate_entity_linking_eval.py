"""Build the locked, deidentified Ontology V2 entity-linking review set."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rdflib import Graph, RDF, SKOS


ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
OUTPUT = ROOT / "evaluation" / "entity_linking.jsonl"
LOCK = ROOT / "evaluation" / "entity_linking.lock.json"
BASE = "https://bilibili.local/ontology/"


def split_for(index: int) -> str:
    bucket = index % 10
    return "test" if bucket in {0, 1} else "dev" if bucket == 2 else "train"


def main() -> None:
    records = []
    index = 0
    domain_paths = sorted((ONTOLOGY / "domains").glob("*.ttl"))
    for path in domain_paths:
        domain = path.stem
        graph = Graph().parse(path, format="turtle")
        concepts = sorted(set(graph.subjects(RDF.type, SKOS.Concept)), key=str)
        for concept in concepts:
            label = next(iter(graph.objects(concept, SKOS.prefLabel)), None)
            if label is None:
                continue
            index += 1
            records.append({
                "schema_version": "1.0", "id": f"el-v2-{index:04d}",
                "split": split_for(index), "domain": domain,
                "text": f"专题：{label}", "expected_concepts": [str(concept)],
                "ambiguous": False, "should_abstain": False,
            })
            for alias in list(graph.objects(concept, SKOS.altLabel))[:1]:
                alias_text = str(alias)
                context = {
                    "Agent": "LangGraph Agent 工作流",
                    "Java": "Java Spring 后端开发教程",
                    "Ontology": "RDF OWL Ontology 知识建模",
                }.get(alias_text, f"专题：{alias_text}")
                index += 1
                records.append({
                    "schema_version": "1.0", "id": f"el-v2-{index:04d}",
                    "split": split_for(index), "domain": domain,
                    "text": context, "expected_concepts": [str(concept)],
                    "ambiguous": False, "should_abstain": False,
                })

    fuzzy_cases = [
        ("ai", "LangGraff 框架", "LangGraph"),
        ("ai", "Pythn 编程", "Python"),
        ("ai", "Machin Learnig", "MachineLearning"),
        ("ai", "Reinforcment Learning", "ReinforcementLearning"),
        ("game", "Minecraf 沙盒", "Minecraft"),
        ("game", "Genshin Impct", "GenshinImpact"),
        ("animation", "Animaton Production", "AnimationProduction"),
        ("animation", "Storybord 分镜", "Storyboarding"),
        ("music", "Eletronic Music", "ElectronicMusic"),
        ("music", "Compositon 作曲", "Composition"),
        ("film", "Cinematograhy", "Cinematography"),
        ("film", "Screenwritng", "Screenwriting"),
        ("knowledge", "Mathematic", "Mathematics"),
        ("knowledge", "Psychlogy", "Psychology"),
        ("knowledge", "Informtion Retrieval", "InformationRetrieval"),
        ("life", "Photograhy", "Photography"),
        ("life", "Gardning", "Gardening"),
        ("life", "Basketbal", "Basketball"),
        ("life", "Skincar", "Skincare"),
        ("life", "Personal Finace", "PersonalFinance"),
    ]
    for domain, text, identifier in fuzzy_cases:
        index += 1
        records.append({
            "schema_version": "1.0", "id": f"el-v2-{index:04d}",
            "split": "test", "domain": domain, "text": text,
            "expected_concepts": [BASE + identifier],
            "ambiguous": False, "should_abstain": False,
        })

    abstentions = [
        ("ai", "Agent"), ("ai", "Java"), ("ai", "Ontology"),
        ("life", "智能家居开箱"), ("knowledge", "人体的本体感觉"),
        ("game", "Go 入门"), ("film", "今天心情很好"),
        ("music", "普通聊天没有主题"), ("animation", "随机字符串 xyzqv"),
        ("life", "天气不错出去走走"),
    ]
    neutral = [
        "未收录品牌型号", "纯数字 123456", "这是一句测试空话", "无明确主题的闲聊",
        "尚未定义的新名词", "路边看到一棵树", "今天按时起床", "请帮我随便看看",
        "一个没有上下文的词", "未知缩写 QXZ",
    ]
    domains = ["ai", "game", "animation", "music", "film", "knowledge", "life"]
    for number in range(40):
        abstentions.append((domains[number % len(domains)], f"{neutral[number % len(neutral)]} 样例{number + 1}"))
    for domain, text in abstentions:
        index += 1
        records.append({
            "schema_version": "1.0", "id": f"el-v2-{index:04d}",
            "split": split_for(index), "domain": domain, "text": text,
            "expected_concepts": [], "ambiguous": True, "should_abstain": True,
        })

    payload = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in records)
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    LOCK.write_text(json.dumps({
        "schema_version": "1.0", "sha256": digest, "count": len(records),
        "split_counts": {split: sum(row["split"] == split for row in records)
                         for split in ("train", "dev", "test")},
        "review_basis": "Ontology V2 curated concepts, one preferred-label case, at most one alias case, and explicit rejection cases.",
        "privacy": "synthetic and contains no account identifiers",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"count": len(records), "sha256": digest}, ensure_ascii=False))


if __name__ == "__main__":
    main()
