"""Run Monitor Suite Agent with Uvicorn."""

from __future__ import annotations

import logging

import uvicorn

from .config import Settings


def main() -> None:
    """Run the production ASGI server."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    uvicorn.run(
        "monitor_suite_agent.app:app",
        host=settings.host,
        port=settings.port,
        workers=1,
        proxy_headers=settings.trusted_proxies is not None,
        forwarded_allow_ips=settings.trusted_proxies or "",
        limit_concurrency=settings.limit_concurrency,
        backlog=settings.backlog,
        timeout_keep_alive=settings.keep_alive_seconds,
    )


if __name__ == "__main__":
    main()
