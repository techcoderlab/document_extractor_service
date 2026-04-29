# ─────────────────────────────────────────────────────
# Module   : app/domain/value_objects.py
# Layer    : Domain
# Pillar   : P1 (Architecture), P2 (Security), P8 (Code Quality)
# Complexity: O(1) time, O(1) space
# ─────────────────────────────────────────────────────

import hashlib
from pydantic import BaseModel, Field, field_validator

class ImageMetadata(BaseModel):
    """
    Immutable value object representing the metadata of an uploaded image.
    Strictly excludes raw byte payloads to enforce P2 (Security).
    """
    # DATA: PUBLIC
    size_bytes: int = Field(..., description="Size of the original image in bytes")
    mime_type: str = Field(..., description="MIME type of the image (e.g., image/jpeg)")
    
    # DATA: INTERNAL
    sha256_hash: str = Field(..., description="SHA-256 hash of the original image bytes before any processing")

    @field_validator("size_bytes")
    def validate_size_limit(cls, v: int) -> int:
        """Domain-level guard against oversized files. 5MB hard limit."""
        if v > 5 * 1024 * 1024:
            raise ValueError(f"Image size {v} bytes exceeds 5MB domain limit")
        return v

    @classmethod
    def from_bytes(cls, raw_bytes: bytes, mime_type: str) -> "ImageMetadata":
        """Factory method to compute hash and size securely without retaining bytes."""
        file_hash = hashlib.sha256(raw_bytes).hexdigest()
        return cls(
            size_bytes=len(raw_bytes),
            mime_type=mime_type,
            sha256_hash=file_hash
        )

class ConfidenceMetric(BaseModel):
    """
    Value object representing the LLM's confidence in an extracted field.
    Enforces the mandatory 'confidence/flagged' schema rule.
    """
    # DATA: INTERNAL
    confidence: float = Field(
        ..., 
        ge=0.0, 
        le=1.0, 
        description="Probability score from 0.0 (uncertain) to 1.0 (certain)"
    )
    flagged: bool = Field(
        ..., 
        description="True if the LLM detects ambiguity, illegible text, or anomalies"
    )
    reason: str | None = Field(
        default=None, 
        description="Optional explanation if flagged is True"
    )