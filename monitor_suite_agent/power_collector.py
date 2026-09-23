"""Privileged, networkless RAPL collector for Monitor Suite Agent."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Callable

DEFAULT_CACHE = Path("/run/monitor-suite-agent/power.json")
DEFAULT_POWERCAP_ROOT = Path("/sys/class/powercap")


def configured_cache() -> Path:
    return Path(os.getenv("MONITOR_SUITE_POWER_CACHE", str(DEFAULT_CACHE)))


def _powercap_zones(powercap_root: Path) -> list[Path]:
    """Return unique powercap zones without following recursive device aliases."""
    try:
        first_level = sorted(powercap_root.iterdir())
    except OSError:
        return []

    candidates = list(first_level)
    for entry in first_level:
        try:
            if entry.is_dir():
                candidates.extend(sorted(entry.iterdir()))
        except OSError:
            continue

    zones: list[Path] = []
    seen: set[tuple[int, int]] = set()
    for candidate in candidates:
        if not (candidate / "name").is_file() or not (candidate / "energy_uj").is_file():
            continue
        try:
            stat = candidate.stat()
        except OSError:
            continue
        identity = (stat.st_dev, stat.st_ino)
        if identity in seen:
            continue
        seen.add(identity)
        zones.append(candidate)
    return zones


def discover_package_zone(powercap_root: Path) -> Path | None:
    """Find a readable package domain across class and control-type layouts."""
    for zone in _powercap_zones(powercap_root):
        try:
            name = (zone / "name").read_text(encoding="ascii").strip().lower()
            int((zone / "energy_uj").read_text(encoding="ascii").strip())
        except (OSError, UnicodeError, ValueError):
            continue
        if name.startswith("package-"):
            return zone
    return None


def _read_nonnegative_int(path: Path) -> int | None:
    try:
        value = int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    return value if value >= 0 else None


def calculate_rapl_watts(
    first_uj: int,
    second_uj: int,
    elapsed_seconds: float,
    max_energy_range_uj: int,
) -> float | None:
    """Calculate wrap-safe average package power from two energy readings."""
    if elapsed_seconds <= 0 or max_energy_range_uj <= 0:
        return None
    delta = second_uj - first_uj
    if delta < 0:
        delta += max_energy_range_uj
    if delta < 0 or delta > max_energy_range_uj:
        return None
    watts = delta / 1_000_000.0 / elapsed_seconds
    return round(watts, 3) if 0 <= watts <= 10_000 else None


def sample_package_power(
    zone: Path,
    sample_seconds: float = 1.0,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> float | None:
    energy_path = zone / "energy_uj"
    maximum = _read_nonnegative_int(zone / "max_energy_range_uj")
    first = _read_nonnegative_int(energy_path)
    if maximum is None or first is None:
        return None
    started = monotonic()
    sleeper(sample_seconds)
    second = _read_nonnegative_int(energy_path)
    elapsed = monotonic() - started
    if second is None:
        return None
    return calculate_rapl_watts(first, second, elapsed, maximum)


def write_cache(path: Path, value_w: float) -> None:
    """Atomically write the sanitized package-power cache."""
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "value_w": value_w,
        "source": "rapl_package",
        "domain": "package",
    }
    descriptor, temporary_name = tempfile.mkstemp(prefix=".power-", dir=path.parent)
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


def collect(
    cache: Path = DEFAULT_CACHE,
    powercap_root: Path = DEFAULT_POWERCAP_ROOT,
    sample_seconds: float = 1.0,
) -> int:
    zone = discover_package_zone(powercap_root)
    value_w = sample_package_power(zone, sample_seconds) if zone else None
    if value_w is None:
        try:
            cache.unlink()
        except FileNotFoundError:
            pass
        return 0
    write_cache(cache, value_w)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect sanitized RAPL package power")
    parser.add_argument("--cache", type=Path, default=configured_cache())
    parser.add_argument("--powercap-root", type=Path, default=DEFAULT_POWERCAP_ROOT)
    parser.add_argument("--sample-seconds", type=float, default=1.0)
    args = parser.parse_args()
    return collect(args.cache, args.powercap_root, args.sample_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
