"""Ontology semantic layer used by RAG, profiling, recommendation and agents."""

from app.services.ontology.service import (
    ConceptMatch,
    OntologyAnnotation,
    OntologyService,
    get_ontology_service,
)

__all__ = [
    "ConceptMatch",
    "OntologyAnnotation",
    "OntologyService",
    "get_ontology_service",
]
