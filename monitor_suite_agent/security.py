"""HTTP authentication for the monitoring API."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    request: Request, supplied_key: str | None = Security(_API_KEY_HEADER)
) -> None:
    """Require the configured API key, using constant-time comparison."""
    expected = request.app.state.settings.api_key
    if expected is None:
        return
    if supplied_key is None or not secrets.compare_digest(supplied_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
