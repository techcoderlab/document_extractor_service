# ─────────────────────────────────────────────────────
# Module   : app/core/middleware.py
# Layer    : Presentation
# Pillar   : P2 (Security), P7 (Observability)
# Complexity: O(1) time, O(1) space
# ─────────────────────────────────────────────────────

import uuid
from fastapi import Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import structlog

from app.core.config import settings
from app.core.logger import logger

# 10 MB absolute upper limit for the multipart payload (headers + file). 
# This is a secondary guard; the Discord bot primarily enforces the 5MB file limit.
MAX_REQ_BODY_SIZE = 10 * 1024 * 1024 

class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Enforces a strict upper bound on request body size to prevent DoS attacks."""
    
    async def dispatch(self, request: Request, call_next) -> Response: # type: ignore
        content_length = request.headers.get('content-length')
        if content_length and int(content_length) > MAX_REQ_BODY_SIZE:
            logger.warning("Request rejected: Payload too large", size=content_length)
            return JSONResponse(
                status_code=413, 
                content={"detail": "Payload Too Large"}
            )
        return await call_next(request)

class TraceIDMiddleware(BaseHTTPMiddleware):
    """
    Injects a W3C traceparent-like trace_id into the structlog context 
    and HTTP response headers for request tracking across services.
    """
    
    async def dispatch(self, request: Request, call_next) -> Response: # type: ignore
        trace_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        
        # Bind the trace_id to the structured logger context for this request lifecycle
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(trace_id=trace_id)
        
        response = await call_next(request)
        response.headers["X-Request-ID"] = trace_id
        return response

def setup_middlewares(app) -> None: # type: ignore
    """Registers all application middlewares in correct order."""
    
    # CORS: Restrict to bot network / internal APIs only
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost", "http://localhost:8000", settings.API_BASE_URL],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(TraceIDMiddleware)