"""Export the reviewed public Ontology into a browser-safe demo snapshot."""
from __future__ import annotations

import json
from pathlib import Path
import sys

from rdflib import URIRef
from rdflib.namespace import SKOS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.ontology import get_ontology_service
from app.services.ontology.service import BILI


def main() -> None:
    ontology = get_ontology_service()
    concepts = []
    for concept in ontology.list_concepts():
        if concept.get("deprecated"):
            continue
        concepts.append({
            "id": concept["concept_id"],
            "label": concept["label"],
            "aliases": concept.get("aliases") or [],
            "type": concept["concept_type"],
        })

    relations = []
    supported = (
        (SKOS.broader, "broader"),
        (SKOS.related, "related"),
        (BILI.requires, "requires"),
    )
    known = {row["id"] for row in concepts}
    for predicate, name in supported:
        for subject, target in ontology.graph.subject_objects(predicate):
            if not isinstance(subject, URIRef) or not isinstance(target, URIRef):
                continue
            if str(subject) in known and str(target) in known:
                relations.append({
                    "from": str(subject),
                    "relation": name,
                    "to": str(target),
                })

    payload = {
        "version": ontology.VERSION,
        "tripleCount": len(ontology.graph),
        "concepts": sorted(concepts, key=lambda row: (row["type"], row["label"])),
        "relations": sorted(
            relations,
            key=lambda row: (row["from"], row["relation"], row["to"]),
        ),
    }
    output = PROJECT_ROOT / "frontend" / "lib" / "demo-ontology.json"
    output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(
        f"Wrote {len(concepts)} concepts and {len(relations)} relations to {output}"
    )


if __name__ == "__main__":
    main()
