"""Privileged RAPL collector and cache tests."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from monitor_suite_agent.power_collector import (
    calculate_rapl_watts,
    discover_package_zone,
    sample_package_power,
    write_cache,
)
from monitor_suite_agent.telemetry import read_power_cache


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def test_discovers_semantic_package_zone_only(tmp_path: Path) -> None:
    _write(tmp_path / "intel-rapl:0/name", "package-0\n")
    _write(tmp_path / "intel-rapl:0/energy_uj", "100\n")
    _write(tmp_path / "intel-rapl:0/intel-rapl:0:0/name", "core\n")
    _write(tmp_path / "intel-rapl:0/intel-rapl:0:0/energy_uj", "50\n")
    assert discover_package_zone(tmp_path) == tmp_path / "intel-rapl:0"


def test_rapl_power_calculation_and_wrap() -> None:
    assert calculate_rapl_watts(1_000_000, 6_000_000, 1.0, 10_000_000) == 5.0
    assert calculate_rapl_watts(9_000_000, 1_000_000, 1.0, 10_000_000) == 2.0
    assert calculate_rapl_watts(1, 2, 0.0, 10) is None


def test_samples_package_power(tmp_path: Path) -> None:
    zone = tmp_path / "intel-rapl:0"
    _write(zone / "max_energy_range_uj", "10000000\n")
    _write(zone / "energy_uj", "1000000\n")
    times = iter((5.0, 6.0))

    def sleeper(seconds: float) -> None:
        assert seconds == 1.0
        _write(zone / "energy_uj", "6000000\n")

    assert sample_package_power(zone, monotonic=lambda: next(times), sleeper=sleeper) == 5.0


def test_power_cache_round_trip_and_staleness(tmp_path: Path) -> None:
    cache = tmp_path / "power.json"
    write_cache(cache, 7.25)
    data = json.loads(cache.read_text())
    now = datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00"))
    power, current = read_power_cache(cache, 15.0, now)
    assert current is True
    assert power == {
        "value_w": 7.25,
        "source": "rapl_package",
        "input_voltage_v": None,
        "domain": "package",
    }
    power, current = read_power_cache(cache, 15.0, now + timedelta(seconds=16))
    assert current is False
    assert power["source"] == "unavailable"


def test_power_cache_rejects_extra_or_invalid_fields(tmp_path: Path) -> None:
    cache = tmp_path / "power.json"
    now = datetime.now(timezone.utc).replace(microsecond=0)
    payload = {
        "schema_version": 1,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "value_w": 5.0,
        "source": "rapl_package",
        "domain": "package",
        "raw_energy_uj": 123,
    }
    cache.write_text(json.dumps(payload))
    power, current = read_power_cache(cache, 15.0, now)
    assert current is False
    assert power["source"] == "unavailable"
