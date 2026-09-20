"""Environment-based runtime configuration."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
from pathlib import Path
import re


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _port(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None else default
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not 1 <= value <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return value


def _optional_positive_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None else default
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _boolean(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _api_key(host: str) -> str | None:
    raw = os.getenv("MONITOR_SUITE_API_KEY")
    value = raw.strip() if raw else None
    if value is not None and (
        not value.isascii()
        or not value.isprintable()
        or any(character.isspace() for character in value)
    ):
        raise ValueError("MONITOR_SUITE_API_KEY must use printable ASCII without internal whitespace")
    if value is not None and len(value) < 32:
        raise ValueError("MONITOR_SUITE_API_KEY must be at least 32 characters")
    if not _is_loopback_host(host) and value is None:
        raise ValueError("MONITOR_SUITE_API_KEY is required when binding beyond loopback")
    return value


def _trusted_proxies(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values or "*" in values:
        raise ValueError(f"{name} must contain explicit trusted IP addresses or networks")
    for value in values:
        try:
            ipaddress.ip_network(value, strict=False)
        except ValueError as exc:
            raise ValueError(f"{name} contains an invalid IP address or network") from exc
    return ",".join(values)


_INTERFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")


def _optional_interface(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    value = raw.strip()
    if not _INTERFACE_RE.fullmatch(value) or value == "lo" or value.startswith(("docker", "br-", "veth")):
        raise ValueError(f"{name} must name a physical network interface")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated daemon settings."""

    host: str = "127.0.0.1"
    port: int = 5000
    sample_interval_seconds: float = 1.0
    slow_sample_interval_seconds: float = 30.0
    thermal_sample_interval_seconds: float = 2.0
    power_sample_interval_seconds: float = 5.0
    raid_idle_interval_seconds: float = 30.0
    raid_active_interval_seconds: float = 2.0
    smart_cache_file: Path = Path("/run/monitor-suite-agent/smart.json")
    smart_cache_max_age_seconds: float = 1800.0
    power_cache_file: Path = Path("/run/monitor-suite-agent/power.json")
    power_cache_max_age_seconds: float = 15.0
    command_timeout_seconds: float = 2.0
    stale_after_seconds: float = 5.0
    idle_power_override_w: float | None = None
    full_load_power_override_w: float | None = None
    network_interface: str | None = None
    api_key: str | None = None
    enable_docs: bool = False
    trusted_proxies: str | None = None
    limit_concurrency: int = 32
    backlog: int = 64
    keep_alive_seconds: int = 5

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables."""
        host = os.getenv("MONITOR_SUITE_HOST", "127.0.0.1").strip()
        if not host:
            raise ValueError("MONITOR_SUITE_HOST must not be empty")
        idle = _optional_positive_float("MONITOR_SUITE_IDLE_W")
        full = _optional_positive_float("MONITOR_SUITE_FULL_LOAD_W")
        if (idle is None) != (full is None):
            raise ValueError("MONITOR_SUITE_IDLE_W and MONITOR_SUITE_FULL_LOAD_W must be set together")
        if idle is not None and full is not None and full <= idle:
            raise ValueError("MONITOR_SUITE_FULL_LOAD_W must exceed MONITOR_SUITE_IDLE_W")
        sample = _positive_float("MONITOR_SUITE_SAMPLE_INTERVAL", 1.0)
        slow = _positive_float("MONITOR_SUITE_SLOW_SAMPLE_INTERVAL", 30.0)
        stale = _positive_float("MONITOR_SUITE_STALE_AFTER", max(5.0, sample * 5.0))
        return cls(
            host=host,
            port=_port("MONITOR_SUITE_PORT", 5000),
            sample_interval_seconds=sample,
            slow_sample_interval_seconds=slow,
            thermal_sample_interval_seconds=_positive_float("MONITOR_SUITE_THERMAL_INTERVAL", 2.0),
            power_sample_interval_seconds=_positive_float("MONITOR_SUITE_POWER_INTERVAL", 5.0),
            raid_idle_interval_seconds=_positive_float("MONITOR_SUITE_RAID_IDLE_INTERVAL", 30.0),
            raid_active_interval_seconds=_positive_float("MONITOR_SUITE_RAID_ACTIVE_INTERVAL", 2.0),
            smart_cache_file=Path(os.getenv("MONITOR_SUITE_SMART_CACHE", "/run/monitor-suite-agent/smart.json")),
            smart_cache_max_age_seconds=_positive_float("MONITOR_SUITE_SMART_CACHE_MAX_AGE", 1800.0),
            power_cache_file=Path(os.getenv("MONITOR_SUITE_POWER_CACHE", "/run/monitor-suite-agent/power.json")),
            power_cache_max_age_seconds=_positive_float("MONITOR_SUITE_POWER_CACHE_MAX_AGE", 15.0),
            command_timeout_seconds=_positive_float("MONITOR_SUITE_COMMAND_TIMEOUT", 2.0),
            stale_after_seconds=stale,
            idle_power_override_w=idle,
            full_load_power_override_w=full,
            network_interface=_optional_interface("MONITOR_SUITE_NETWORK_INTERFACE"),
            api_key=_api_key(host),
            enable_docs=_boolean("MONITOR_SUITE_ENABLE_DOCS", False),
            trusted_proxies=_trusted_proxies("MONITOR_SUITE_TRUSTED_PROXIES"),
            limit_concurrency=_positive_int("MONITOR_SUITE_LIMIT_CONCURRENCY", 32),
            backlog=_positive_int("MONITOR_SUITE_BACKLOG", 64),
            keep_alive_seconds=_positive_int("MONITOR_SUITE_KEEP_ALIVE", 5),
        )
