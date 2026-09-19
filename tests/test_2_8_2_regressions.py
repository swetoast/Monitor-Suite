from datetime import datetime, timedelta, timezone
from pathlib import Path

from monitor_suite_agent.smart_collector import configured_cache
from monitor_suite_agent.telemetry import (
    _clean_smart_devices,
    corrected_booted_at,
    read_cooling,
    read_network_metadata,
)


def test_unknown_operstate_is_preserved_in_public_contract(tmp_path: Path) -> None:
    interface = tmp_path / "wlan0"
    interface.mkdir()
    (interface / "operstate").write_text("unknown\n")
    assert read_network_metadata(tmp_path, "wlan0")["status"] == "unknown"


def test_bad_smart_device_does_not_discard_valid_devices() -> None:
    devices = _clean_smart_devices([
        {"device": "sda", "status": "healthy", "temperature_c": 30.0},
        {"device": "mmcblk0", "status": "unavailable", "temperature_c": None},
        {"device": "nvme0n1", "status": "healthy", "temperature_c": 28.0, "remaining_life_percent": 99.0},
    ])
    assert devices is not None
    assert [item["device"] for item in devices] == ["sda", "nvme0n1"]


def test_fan_only_cooling_reports_rpm(tmp_path: Path) -> None:
    fan = tmp_path / "fan1_input"
    fan.write_text("1450\n")
    assert read_cooling(None, fan) == {"state": "active", "fan_speed_rpm": 1450}
    fan.write_text("0\n")
    assert read_cooling(None, fan) == {"state": "idle", "fan_speed_rpm": 0}


def test_smart_collector_uses_shared_cache_environment(monkeypatch, tmp_path: Path) -> None:
    cache = tmp_path / "custom-smart.json"
    monkeypatch.setenv("MONITOR_SUITE_SMART_CACHE", str(cache))
    assert configured_cache() == cache


def test_boot_time_ignores_jitter_but_accepts_clock_sync_correction() -> None:
    initial_now = datetime(2026, 1, 1, 0, 1, 0, tzinfo=timezone.utc)
    initial = corrected_booted_at(None, 60.0, initial_now)
    assert initial == "2026-01-01T00:00:00Z"
    assert corrected_booted_at(initial, 61.2, initial_now + timedelta(seconds=1)) == initial
    synced_now = datetime(2026, 9, 19, 17, 0, 0, tzinfo=timezone.utc)
    corrected = corrected_booted_at(initial, 3600.0, synced_now)
    assert corrected == "2026-09-19T16:00:00Z"


def test_smart_service_template_keeps_strict_sandbox() -> None:
    unit = Path("deploy/monitor-suite-smart.service").read_text()
    assert "EnvironmentFile=/etc/monitor-suite-agent.env" in unit
    assert "ProtectSystem=strict" in unit
    assert "ProtectSystem=full" not in unit


def test_installer_rewrites_smart_service_config_path() -> None:
    installer = Path("install.sh").read_text()
    smart_sed = next(
        line for line in installer.splitlines()
        if 'SMART_SERVICE_NAME' in line and line.lstrip().startswith('sed -i')
    )
    assert 's|/etc/monitor-suite-agent.env|$CONFIG_FILE|g' in smart_sed
