"""Ontology inspection and entity-linking API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import VideoConcept
from app.services.ontology import get_ontology_service


router = APIRouter(prefix="/ontology", tags=["Ontology"])


class ResolveRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    expand: bool = True
    max_hops: int = Field(default=1, ge=0, le=2)


@router.get("/health")
async def ontology_health():
    report = get_ontology_service().validate()
    if not report["conforms"]:
        raise HTTPException(status_code=503, detail=report)
    return report


@router.get("/concepts")
async def list_concepts(
    concept_type: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
):
    ontology = get_ontology_service()
    concepts = ontology.list_concepts(concept_type=concept_type)[:limit]
    return {"version": ontology.VERSION, "count": len(concepts), "concepts": concepts}


@router.post("/resolve")
async def resolve_concepts(request: ResolveRequest):
    ontology = get_ontology_service()
    matches = ontology.resolve_text(request.text)
    expanded = (
        ontology.expand_concepts(
            [match.concept_id for match in matches],
            max_hops=request.max_hops,
        )
        if request.expand else []
    )
    return {
        "version": ontology.VERSION,
        "matches": [match.as_dict() for match in matches],
        "expanded": expanded,
        "query_variants": ontology.expand_query(request.text),
    }

@router.get("/videos/{bvid}")
async def video_concepts(bvid: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(VideoConcept)
        .where(VideoConcept.bvid == bvid)
        .order_by(VideoConcept.confidence.desc())
    )
    rows = list(result.scalars())
    return {
        "bvid": bvid,
        "concepts": [{
            "concept_id": row.concept_id,
            "relation_type": row.relation_type,
            "confidence": row.confidence,
            "evidence_text": row.evidence_text,
            "ontology_version": row.ontology_version,
        } for row in rows],
    }
