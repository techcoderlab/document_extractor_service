# ─────────────────────────────────────────────────────
# Module   : app/core/http.py
# Layer    : Infrastructure
# Pillar   : P3 (Concurrency), P6 (Resilience)
# Complexity: O(1) time, O(1) space
# ─────────────────────────────────────────────────────

import httpx
import asyncio
from app.core.logger import logger  # Adjusted import path to match project structure

class HttpClient:
    """
    User's Custom HTTP Client with Retry, Backoff, and Smart Error Handling.
    """
    def __init__(self, timeout: float = 15.0, retries: int = 3, backoff: float = 0.5):
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        # Optimization: httpx.AsyncClient is created once per instance
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100)
        )
        
    def set_timeout(self, timeout: float):
        self.timeout = timeout
        return self

    def set_retries(self, retries: int):
        self.retries = retries
        return self

    def set_backoff(self, backoff: float):
        self.backoff = backoff
        return self

    async def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        last_exc = None
        
        # Use timeout from kwargs if present, otherwise use self.timeout
        request_timeout = kwargs.pop("timeout", self.timeout)
        
        for attempt in range(1, self.retries + 1):
            try:
                resp = await self._client.request(method, url, timeout=request_timeout, **kwargs)
                
                # --- THE FIX (YOUR LOGIC) ---
                # Raise error for 400 (Bad Request), 401 (Auth), etc. immediately
                resp.raise_for_status() 
                
                return resp
            except httpx.HTTPStatusError as e:
                # If it's a 4xx error (like Bad Token), don't retry! 
                # Log it and raise it immediately so the main loop catches it.
                if e.response.status_code < 500 and e.response.status_code != 429:
                    logger.error(f"HTTP Client Error {e.response.status_code}: {e.response.text}")
                    raise e
                
                # If it's a 500 error (Server error), we retry.
                last_exc = e
                logger.warning(f"HTTP {e.response.status_code} error on attempt {attempt}, retrying in {self.backoff * attempt}s... : {e}")
                await asyncio.sleep(self.backoff * attempt)
                
            except Exception as e:
                # Network errors, timeouts, etc.
                last_exc = e
                logger.warning(f"HTTP attempt {attempt} failed, retrying in {self.backoff * attempt}s... : {e}")
                await asyncio.sleep(self.backoff * attempt)
        
        # If we ran out of retries
        if last_exc:
            raise last_exc
        # Fallback if loop finished without exception (rare edge case)
        raise Exception("Request failed after max retries")

    async def get(self, url: str, **kwargs) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def close(self) -> None:
        await self._client.aclose()


# --- SINGLETON MANAGEMENT ---
# This ensures we reuse the SAME HttpClient instance across the whole app.

_client_instance: HttpClient | None = None

def get_client() -> HttpClient:
    """Returns the singleton instance of HttpClient."""
    global _client_instance
    if _client_instance is None:
        _client_instance = HttpClient()
    return _client_instance

async def close_client():
    """Closes the singleton instance connection pool."""
    global _client_instance
    if _client_instance:
        await _client_instance.close()
        _client_instance = None