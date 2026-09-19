"""Privileged, networkless SMART collector for Monitor Suite Agent."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .telemetry import Paths, read_smart_devices, run_smartctl

DEFAULT_CACHE = Path("/run/monitor-suite-agent/smart.json")


def configured_cache() -> Path:
    """Return the cache path shared with the API service configuration."""
    return Path(os.getenv("MONITOR_SUITE_SMART_CACHE", str(DEFAULT_CACHE)))


def _previous_devices(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        devices = data.get("devices", [])
        return devices if isinstance(devices, list) else []
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return []


def write_cache(path: Path, devices: list[dict[str, Any]]) -> None:
    """Atomically write the sanitized SMART cache."""
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "devices": devices,
    }
    descriptor, temporary_name = tempfile.mkstemp(prefix=".smart-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o640)
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def collect(cache: Path = DEFAULT_CACHE, timeout: float = 10.0) -> int:
    devices = read_smart_devices(
        Paths().block_root, run_smartctl, timeout, _previous_devices(cache)
    )
    write_cache(cache, devices)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect sanitized SMART health data")
    parser.add_argument("--cache", type=Path, default=configured_cache())
    parser.add_argument("--timeout", type=float, default=10.0)
    arguments = parser.parse_args()
    return collect(arguments.cache, arguments.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
