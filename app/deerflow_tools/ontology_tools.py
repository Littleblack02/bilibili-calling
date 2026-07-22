"""Ontology tools exposed to the DeerFlow lead agent."""
from __future__ import annotations

import json

from langchain.tools import tool

from app.services.ontology import get_ontology_service


@tool("resolve_concept", parse_docstring=True)
def resolve_concept_tool(text: str, max_hops: int = 1) -> str:
    """Resolve user language into canonical Bilibili-domain concepts and relations.

    Use before searching when the question contains aliases, a broad topic, or
    asks how two learning concepts are related.

    Args:
        text: User query or content to resolve.
        max_hops: Relation expansion depth, 0 to 2. Default 1.

    Returns:
        JSON containing canonical matches, related concepts and relation paths.
    """
    ontology = get_ontology_service()
    matches = ontology.resolve_text(text)
    expanded = ontology.expand_concepts(
        [match.concept_id for match in matches],
        max_hops=max(0, min(2, max_hops)),
    )
    return json.dumps({
        "ontology_version": ontology.VERSION,
        "matches": [match.as_dict() for match in matches],
        "expanded": expanded,
        "query_variants": ontology.expand_query(text),
    }, ensure_ascii=False, indent=2)

@tool("explain_concept_relation", parse_docstring=True)
def explain_concept_relation_tool(source: str, target: str) -> str:
    """Explain the ontology relation path between two concepts.

    Args:
        source: First concept name or alias.
        target: Second concept name or alias.

    Returns:
        JSON with the best bounded ontology relation path.
    """
    ontology = get_ontology_service()
    source_matches = ontology.resolve_text(source, limit=1)
    target_matches = ontology.resolve_text(target, limit=1)
    if not source_matches or not target_matches:
        return json.dumps({"found": False, "reason": "concept_not_resolved"}, ensure_ascii=False)
    target_id = target_matches[0].concept_id
    expanded = ontology.expand_concepts([source_matches[0].concept_id], max_hops=2)
    relation = next((row for row in expanded if row["concept_id"] == target_id), None)
    return json.dumps({
        "found": relation is not None,
        "source": source_matches[0].as_dict(),
        "target": target_matches[0].as_dict(),
        "relation": relation,
    }, ensure_ascii=False, indent=2)
