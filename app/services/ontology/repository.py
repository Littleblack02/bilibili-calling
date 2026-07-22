"""Persistence helpers for ontology-derived video annotations."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OntologyConcept, VideoConcept
from app.services.ontology.service import OntologyAnnotation, OntologyService


async def replace_video_annotations(
    db: AsyncSession,
    bvid: str,
    annotations: Iterable[OntologyAnnotation],
    ontology: OntologyService,
) -> int:
    rows = list(annotations)
    await db.execute(delete(VideoConcept).where(VideoConcept.bvid == bvid))
    for annotation in rows:
        existing = await db.execute(
            select(OntologyConcept).where(OntologyConcept.concept_id == annotation.concept_id)
        )
        concept = existing.scalar_one_or_none()
        details = ontology.concept(annotation.concept_id) or {}
        if concept is None:
            concept = OntologyConcept(
                concept_id=annotation.concept_id,
                pref_label=annotation.label,
                concept_type=annotation.concept_type,
                aliases=details.get("aliases", []),
                ontology_version=ontology.VERSION,
                is_active=True,
            )
            db.add(concept)
        else:
            concept.pref_label = annotation.label
            concept.concept_type = annotation.concept_type
            concept.aliases = details.get("aliases", concept.aliases or [])
            concept.ontology_version = ontology.VERSION
            concept.updated_at = datetime.utcnow()
        db.add(VideoConcept(
            bvid=bvid,
            concept_id=annotation.concept_id,
            relation_type=annotation.relation_type,
            confidence=annotation.confidence,
            evidence_text=annotation.evidence_text,
            extraction_source=annotation.source,
            ontology_version=ontology.VERSION,
        ))
    return len(rows)
