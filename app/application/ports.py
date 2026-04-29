# ─────────────────────────────────────────────────────
# Module   : app/application/ports.py
# Layer    : Application
# Pillar   : P1 (Architecture)
# Complexity: O(1) time, O(1) space
# ─────────────────────────────────────────────────────

from app.domain.entities import ExtractionJob

async def save_extraction_to_sheets(job: ExtractionJob) -> None:
    """
    Dependency Inversion Port.
    To be fully implemented by the Infrastructure layer in subsequent steps.
    """
    raise NotImplementedError("Sheets persistence infrastructure is not yet initialized.")