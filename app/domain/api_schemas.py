# ─────────────────────────────────────────────────────
# Module   : app/domain/api_schemas.py
# Layer    : Domain / Presentation
# Pillar   : P8 (Code Quality)
# Complexity: O(1) time, O(1) space
# ─────────────────────────────────────────────────────

from typing import List, Optional, Any, Dict
from pydantic import BaseModel, HttpUrl, Field, ConfigDict

class DocumentItem(BaseModel):
    """Represents a single document to be extracted."""
    id: str = Field(..., description="Unique identifier for the document")
    file_url: Optional[HttpUrl] = Field(default=None, description="Direct download URL")
    base64_content: Optional[str] = Field(default=None, description="Base64 encoded string")
    mime_type: str = Field(default="image/jpeg")

class BatchExtractionRequest(BaseModel):
    """
    P8 Code Quality: Robust Schema for API requests.
    Using ConfigDict to ensure 'extract' and 'schema' aliases work correctly.
    """
    # Maps user "extract" to internal "extract_type"
    extract_type: str = Field(
        default="document", 
        alias="extract"
    )
    
    # Maps user "schema" to internal "custom_schema"
    custom_schema: Optional[Dict[str, Any]] = Field(
        default=None, 
        alias="schema"
    )
    
    provider: str = Field(default="gemini")
    model: str = Field(default="gemini-2.5-flash-lite")
    prompt: Optional[str] = Field(default=None)
    documents: List[DocumentItem] = Field(..., max_length=50)

    # CRITICAL FIX for 422: Tell Pydantic to allow the Aliases in JSON payloads
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=None,
        arbitrary_types_allowed=True
    )

class BatchExtractionResponse(BaseModel):
    results: List[Dict[str, Any]]