"""Network exposure and API authentication tests."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from monitor_suite_agent.app import create_app
from monitor_suite_agent.config import Settings
from monitor_suite_agent.security import require_api_key


def test_remote_bind_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONITOR_SUITE_HOST", "0.0.0.0")
    monkeypatch.delenv("MONITOR_SUITE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="required when binding beyond loopback"):
        Settings.from_env()


def test_remote_bind_accepts_strong_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONITOR_SUITE_HOST", "0.0.0.0")
    monkeypatch.setenv("MONITOR_SUITE_API_KEY", "a" * 32)
    settings = Settings.from_env()
    assert settings.api_key == "a" * 32


def test_short_api_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONITOR_SUITE_API_KEY", "too-short")
    with pytest.raises(ValueError, match="at least 32 characters"):
        Settings.from_env()


def test_docs_are_disabled_by_default() -> None:
    paths = {route.path for route in create_app(Settings()).routes}
    assert "/docs" not in paths
    assert "/openapi.json" not in paths


def test_docs_can_be_enabled_explicitly() -> None:
    paths = {route.path for route in create_app(Settings(enable_docs=True)).routes}
    assert "/docs" in paths
    assert "/openapi.json" in paths


def test_api_key_authentication_accepts_correct_key() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=Settings(api_key="a" * 32))))
    assert asyncio.run(require_api_key(request, "a" * 32)) is None


def test_api_key_authentication_rejects_missing_or_wrong_key() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=Settings(api_key="a" * 32))))
    for supplied in (None, "b" * 32):
        with pytest.raises(HTTPException) as error:
            asyncio.run(require_api_key(request, supplied))
        assert error.value.status_code == 401


def test_wildcard_trusted_proxy_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONITOR_SUITE_TRUSTED_PROXIES", "*")
    with pytest.raises(ValueError, match="explicit trusted"):
        Settings.from_env()


def test_explicit_trusted_proxy_network_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONITOR_SUITE_TRUSTED_PROXIES", "127.0.0.1,10.0.0.0/24")
    assert Settings.from_env().trusted_proxies == "127.0.0.1,10.0.0.0/24"
