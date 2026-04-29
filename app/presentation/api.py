# ─────────────────────────────────────────────────────
# Module   : app/presentation/api.py
# Layer    : Presentation
# Pillar   : P1 (Architecture)
# Complexity: O(1) time, O(1) space
# ─────────────────────────────────────────────────────

from fastapi import APIRouter
from app.domain.api_schemas import BatchExtractionRequest, BatchExtractionResponse
from app.application.orchestrator import process_batch_documents

# Isolate document extraction endpoints into a dedicated router
api_router = APIRouter(prefix="/api/v1/extract", tags=["Document Extraction"])

@api_router.post("/batch", response_model=BatchExtractionResponse)
async def extract_batch(request: BatchExtractionRequest):
    """
    Ingests an array of image documents (URLs or Base64), fetches them securely, 
    and returns LLM-extracted structured JSON per the provided prompt rules.
    """
    result = await process_batch_documents(request)
    return result