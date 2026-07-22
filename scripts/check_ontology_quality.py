"""Run SHACL plus deterministic graph-quality checks for Ontology V2."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from rdflib import RDF, SKOS, URIRef


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.ontology.service import BILI, OntologyService  # noqa: E402


def main() -> int:
    ontology = OntologyService()
    validation = ontology.validate()
    label_owners: dict[str, set[str]] = defaultdict(set)
    for row in ontology.list_concepts():
        for label in [row["label"], *row["aliases"]]:
            label_owners[ontology.normalize_label(label)].add(row["concept_id"])
    normalized_conflicts = {
        label: sorted(owners) for label, owners in label_owners.items()
        if label and len(owners) > 1
    }
    tid_owners: dict[int, list[str]] = defaultdict(list)
    for row in ontology.list_concepts("category"):
        if row["bilibili_tid"] is not None:
            tid_owners[row["bilibili_tid"]].append(row["concept_id"])
    duplicate_tids = {
        str(tid): owners for tid, owners in tid_owners.items() if len(owners) > 1
    }
    dangling = []
    for predicate in (SKOS.broader, SKOS.related, BILI.requires):
        for subject, target in ontology.graph.subject_objects(predicate):
            if not isinstance(target, URIRef) or (
                target, RDF.type, SKOS.Concept
            ) not in ontology.graph:
                dangling.append({
                    "subject": str(subject), "predicate": str(predicate),
                    "target": str(target),
                })
    personal = [
        str(subject) for subject in ontology.graph.subjects(RDF.type, BILI.PersonalConcept)
    ]
    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ontology_version": ontology.VERSION,
        "module_count": len(ontology.module_paths),
        "concept_count": validation["concept_count"],
        "triple_count": validation["triple_count"],
        "shacl_conforms": validation["conforms"],
        "normalized_label_conflicts": normalized_conflicts,
        "duplicate_bilibili_tids": duplicate_tids,
        "dangling_relations": dangling,
        "public_personal_concepts": personal,
    }
    report["passes"] = (
        validation["conforms"]
        and 200 <= report["concept_count"] <= 400
        and report["module_count"] == 9
        and not normalized_conflicts
        and not duplicate_tids
        and not dangling
        and not personal
    )
    output = ROOT / "reports" / "evaluation" / "ontology-quality.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "concept_count": report["concept_count"],
        "triple_count": report["triple_count"],
        "shacl_conforms": report["shacl_conforms"],
        "passes": report["passes"],
    }, ensure_ascii=False))
    return 0 if report["passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
