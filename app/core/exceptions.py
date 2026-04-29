# ─────────────────────────────────────────────────────
# Module   : app/core/exceptions.py
# Layer    : Domain / Application
# Pillar   : P6 (Resilience), P8 (Code Quality)
# Complexity: O(1) time, O(1) space
# ─────────────────────────────────────────────────────

# ── Discord User-Facing Error Messages ─────────────────────────────
# Defined as constants per P8 requirement, never inlined in handlers.

ERROR_FILE_TOO_LARGE = "❌ **Image too large** ({size:.1f} MB / 5 MB limit).\nTry a closer shot or lower resolution."
ERROR_UNSUPPORTED_TYPE = "❌ **Unsupported file type** (`{mime}`).\nAccepted: JPEG, PNG, WEBP, GIF."
ERROR_PROVIDER_OFFLINE = "❌ **{provider} is unavailable** right now.\nTry `--provider ollama` for local processing."
ERROR_EXTRACTION_FAILED = "❌ **Extraction failed.**\nThe image may be too blurry or low-contrast. Try `--ocr local` for handwritten docs."
ERROR_SHEET_WRITE_FAILED = "⚠️ **Extraction succeeded but Sheets logging failed.** Results returned but not saved."

# ── Typed Exception Hierarchy ──────────────────────────────────────

class BaseAppException(Exception):
    """Base exception for all domain and application errors."""
    def __init__(self, message: str, context: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}

class ValidationError(BaseAppException):
    """Raised when input validation fails (maps to 400)."""
    pass

class UnauthorizedError(BaseAppException):
    """Raised for authentication failures (maps to 401)."""
    pass

class NotFoundError(BaseAppException):
    """Raised when a requested resource or schema is missing (maps to 404)."""
    pass

class ProviderNotAvailableError(BaseAppException):
    """Raised when a requested LLM provider is not configured or offline (maps to 503)."""
    pass

class ExternalServiceError(BaseAppException):
    """Raised when an external dependency (Sheets API, LLM API) fails (maps to 502/503)."""
    pass

class RateLimitError(BaseAppException):
    """Raised when an external service rate limit is hit and backoff exhausted (maps to 429)."""
    pass

class SheetPersistenceError(BaseAppException):
    """Raised when saving extraction results to Google Sheets fails."""
    pass