from fastapi import APIRouter

from app.services.observability import metrics


router = APIRouter(prefix="/observability", tags=["可观测性"])


@router.get("/metrics")
async def get_metrics():
    """Return bounded process-local metrics without identifiers or secrets."""
    return metrics.snapshot()
