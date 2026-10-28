# ─────────────────────────────────────────────────────
# Module   : app/core/security.py
# Layer    : Infrastructure
# Pillar   : P2 (Security)
# Complexity: O(1) time, O(1) space (one DNS lookup per URL)
# ─────────────────────────────────────────────────────

import asyncio
import hmac
import ipaddress
import socket
from urllib.parse import urlsplit

from fastapi import Header, HTTPException, status

from app.core.config import settings


async def require_api_key(x_api_key: str = Header(default="", alias="X-API-Key")) -> None:
    """
    P2 Security: every batch call must carry the shared key in the X-API-Key header.
    If no key is configured the API stays closed instead of running open.
    """
    if not settings.API_SECRET_KEY:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "API key is not configured on the server")

    # Constant-time comparison so response timing doesn't leak the key
    if not hmac.compare_digest(x_api_key.encode(), settings.API_SECRET_KEY.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key")


async def assert_public_url(url: str) -> None:
    """
    P2 Security (SSRF guard): only fetch http(s) URLs whose host resolves to public addresses.
    Blocks loopback, private LAN ranges, link-local (cloud metadata) and other reserved addresses.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Only http and https URLs are allowed")

    try:
        infos = await asyncio.get_running_loop().getaddrinfo(parts.hostname, parts.port or None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError(f"Could not resolve host: {parts.hostname}") from e

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ValueError("URL points to a private or reserved network address")
