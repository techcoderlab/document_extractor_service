# ─────────────────────────────────────────────────────
# Module   : app/domain/entities.py
# Layer    : Domain
# Pillar   : P1 (Architecture), P8 (Code Quality), P9 (Data Management)
# Complexity: O(1) time, O(n) space (where n is extracted fields)
# ─────────────────────────────────────────────────────

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from app.domain.value_objects import ImageMetadata, ConfidenceMetric

class ExtractedField(BaseModel):
    """Represents a single data point extracted from a document with its confidence."""
    key: str = Field(..., description="The key of the extracted field")
    value: Any = Field(..., description="The parsed value (string, int, date, etc.)")
    metrics: ConfidenceMetric = Field(..., description="Confidence and flagging data")

class ExtractionData(BaseModel):
    """
    Generic hierarchical data structure that works for ANY document type.
    - sections: Named groups of key-value fields (e.g., 'personal_info', 'shipping_details', 'header_info')
    - tables: Optional list of row-like data (line items, cargo manifests, transaction lists, etc.)
    """
    sections: Dict[str, Dict[str, ExtractedField]] = Field(default_factory=dict)
    tables: List[Dict[str, ExtractedField]] = Field(default_factory=list)

class TokenUsage(BaseModel):
    """Value object tracking LLM API token consumption for cost analysis."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

class ExtractionResult(BaseModel):
    """The strict schema enforced on the LLM output."""
    document_type: str = Field(...)
    overall_confidence: float = Field(..., ge=0.0, le=1.0)
    requires_human_review: bool = Field(...)
    data: ExtractionData = Field(...)
    
    token_usage: Optional[TokenUsage] = None

class ExtractionJob(BaseModel):
    """Aggregate Root representing the lifecycle of an extraction request."""
    job_id: UUID = Field(default_factory=uuid4)
    discord_user_id: str
    discord_channel_id: str
    discord_message_id: str
    image_meta: ImageMetadata
    provider: str
    model: str
    status: str = "PENDING"
    result: Optional[ExtractionResult] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

    def mark_processing(self) -> None:
        self.status = "PROCESSING"

    def mark_success(self, result: ExtractionResult) -> None:
        self.status = "SUCCESS"
        self.result = result
        self.completed_at = datetime.now(timezone.utc)

    def mark_failed(self, error_message: str) -> None:
        self.status = "FAILED"
        self.error_message = error_message
        self.completed_at = datetime.now(timezone.utc)