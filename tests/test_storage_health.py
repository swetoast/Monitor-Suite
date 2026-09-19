"""RAID and SMART reduction tests."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from monitor_suite_agent.telemetry import (
    discover_smart_devices,
    parse_smart_json,
    parse_smartctl_scan,
    read_raid_arrays,
    read_smart_devices,
    read_smart_cache,
    read_nvme_temperatures,
    merge_nvme_temperatures,
)


def smart_payload(*, passed=True, temperature=30, used=None, attributes=None, critical=0, media_errors=0):
    data = {
        "smart_support": {"available": True},
        "smart_status": {"passed": passed},
        "temperature": {"current": temperature},
        "ata_smart_attributes": {"table": attributes or []},
    }
    if used is not None:
        data["nvme_smart_health_information_log"] = {
            "percentage_used": used,
            "critical_warning": critical,
            "media_errors": media_errors,
        }
    return json.dumps(data)


def smart_runner(payload: str, scan="/dev/sda -d sat # test disk"):
    def run(arguments: list[str], _timeout: float) -> str | None:
        if arguments == ["smartctl", "--scan-open"]:
            return scan
        return payload
    return run


def make_array(root: Path, *, level="raid0", state="clean", expected=2, degraded=0, action="idle") -> None:
    md = root / "md0/md"
    (md / "dev-sda").mkdir(parents=True)
    (md / "dev-sdb").mkdir()
    (md / "level").write_text(level)
    (md / "array_state").write_text(state)
    (md / "raid_disks").write_text(str(expected))
    (md / "degraded").write_text(str(degraded))
    (md / "sync_action").write_text(action)
    (md / "dev-sda/state").write_text("in_sync")
    (md / "dev-sdb/state").write_text("in_sync")


def test_smart_reduction_exposes_only_approved_values() -> None:
    result = parse_smart_json(smart_payload(temperature=22, used=2), "nvme0n1")
    assert result == {
        "device": "nvme0n1",
        "status": "healthy",
        "temperature_c": 22,
        "remaining_life_percent": 98.0,
    }


def test_smart_warning_and_failure_classification() -> None:
    pending = [{"id": 197, "raw": {"value": 3}, "when_failed": ""}]
    assert parse_smart_json(smart_payload(attributes=pending), "sda")["status"] == "warning"
    assert parse_smart_json(smart_payload(passed=False), "sda")["status"] == "failed"
    assert parse_smart_json(smart_payload(used=1, media_errors=1), "nvme0n1")["status"] == "warning"


def test_smart_unavailable_is_not_exposed() -> None:
    assert parse_smart_json(json.dumps({"smart_support": {"available": False}}), "mmcblk0") is None
    assert parse_smart_json("not json", "sda") is None


def test_smartctl_scan_parser_preserves_endpoint_types() -> None:
    scan = "\n".join((
        "/dev/sda -d sat # ATA device",
        "/dev/nvme0 -d nvme # NVMe device",
    ))
    assert parse_smartctl_scan(scan) == [("/dev/sda", "sat"), ("/dev/nvme0", "nvme")]


def test_probe_nvme_controllers_map_to_block_namespaces(tmp_path: Path) -> None:
    for name in ("sda", "sdb", "nvme0n1", "nvme1n1"):
        (tmp_path / name / "device").mkdir(parents=True)
    scan = "\n".join((
        "/dev/sda -d sat # ATA device",
        "/dev/sdb -d sat # ATA device",
        "/dev/nvme0 -d nvme # NVMe device",
        "/dev/nvme1 -d nvme # NVMe device",
    ))
    result = discover_smart_devices(tmp_path, smart_runner("", scan), 2.0)
    assert result == [
        ("/dev/sda", "sat", "sda"),
        ("/dev/sdb", "sat", "sdb"),
        ("/dev/nvme0", "nvme", "nvme0n1"),
        ("/dev/nvme1", "nvme", "nvme1n1"),
    ]


def test_probe_devices_keep_own_health_and_temperature(tmp_path: Path) -> None:
    for name in ("sda", "sdb", "nvme0n1", "nvme1n1"):
        (tmp_path / name / "device").mkdir(parents=True)
    scan = "\n".join((
        "/dev/sda -d sat", "/dev/sdb -d sat",
        "/dev/nvme0 -d nvme", "/dev/nvme1 -d nvme",
    ))
    temperatures = {"/dev/sda": 29, "/dev/sdb": 28, "/dev/nvme0": 20, "/dev/nvme1": 32}
    calls = []
    def runner(arguments: list[str], _timeout: float) -> str:
        calls.append(arguments)
        if arguments == ["smartctl", "--scan-open"]:
            return scan
        return smart_payload(temperature=temperatures[arguments[-1]], used=2 if "nvme" in arguments[-1] else None)
    result = read_smart_devices(tmp_path, runner, 2.0)
    assert [(item["device"], item["temperature_c"]) for item in result] == [
        ("sda", 29), ("sdb", 28), ("nvme0n1", 20), ("nvme1n1", 32)
    ]
    assert [call for call in calls if call != ["smartctl", "--scan-open"]] == [
        ["smartctl", "-n", "standby", "-a", "-j", "-d", "sat", "/dev/sda"],
        ["smartctl", "-n", "standby", "-a", "-j", "-d", "sat", "/dev/sdb"],
        ["smartctl", "-n", "standby", "-a", "-j", "-d", "nvme", "/dev/nvme0"],
        ["smartctl", "-n", "standby", "-a", "-j", "-d", "nvme", "/dev/nvme1"],
    ]


def test_healthy_raid0_reports_no_redundancy_and_no_smart_status(tmp_path: Path) -> None:
    make_array(tmp_path)
    result = read_raid_arrays(tmp_path)[0]
    assert result["status"] == "healthy"
    assert result["redundancy"] == "none"
    assert result["active_members"] == 2
    assert "smart_status" not in result
    assert "_members" not in result


def test_recovery_state_takes_priority_over_degraded(tmp_path: Path) -> None:
    make_array(tmp_path, level="raid1", degraded=1, action="recover")
    (tmp_path / "md0/md/dev-sdb/state").write_text("spare,recovering")
    result = read_raid_arrays(tmp_path)[0]
    assert result["status"] == "recovering"
    assert result["active_members"] == 1
    assert result["redundancy"] == "reduced"


def test_resync_progress_is_reported(tmp_path: Path) -> None:
    make_array(tmp_path, level="raid1", action="resync")
    (tmp_path / "md0/md/sync_completed").write_text("25 / 100")
    result = read_raid_arrays(tmp_path)[0]
    assert result["status"] == "resyncing"
    assert result["progress_percent"] == 25.0


def test_newly_discovered_failed_collection_is_visible(tmp_path: Path) -> None:
    (tmp_path / "sda/device").mkdir(parents=True)
    result = read_smart_devices(tmp_path, smart_runner("not-json"), 2.0)
    assert result == [{"device": "sda", "status": "unavailable", "temperature_c": None}]


def test_known_disk_is_unavailable_when_collection_fails(tmp_path: Path) -> None:
    (tmp_path / "sda/device").mkdir(parents=True)
    previous = [{"device": "sda", "status": "healthy", "temperature_c": 30}]
    result = read_smart_devices(tmp_path, smart_runner("not-json"), 2.0, previous)
    assert result == [{"device": "sda", "status": "unavailable", "temperature_c": None}]


def test_smart_collection_uses_standby_mode(tmp_path: Path) -> None:
    (tmp_path / "sda/device").mkdir(parents=True)
    calls = []
    def runner(arguments: list[str], _timeout: float) -> str | None:
        calls.append(arguments)
        return "/dev/sda -d sat" if arguments == ["smartctl", "--scan-open"] else None
    read_smart_devices(tmp_path, runner, 2.0)
    assert calls == [
        ["smartctl", "--scan-open"],
        ["smartctl", "-n", "standby", "-a", "-j", "-d", "sat", "/dev/sda"],
    ]


def test_standby_disk_keeps_last_known_values(tmp_path: Path) -> None:
    (tmp_path / "sda/device").mkdir(parents=True)
    previous = [{"device": "sda", "status": "healthy", "temperature_c": 30}]
    standby = json.dumps({"smartctl": {"messages": [{"string": "Device is in STANDBY mode"}]}})
    result = read_smart_devices(tmp_path, smart_runner(standby), 2.0, previous)
    assert result == previous


PROBE_FIXTURE = Path(__file__).parent / "fixtures" / "drive_temperature_probe_pi5.json"


def test_privacy_scrubbed_drive_probe_returns_all_drive_temperatures(tmp_path: Path) -> None:
    fixture = json.loads(PROBE_FIXTURE.read_text())
    for name in fixture["block_devices"]:
        (tmp_path / name / "device").mkdir(parents=True)

    calls: list[list[str]] = []

    def runner(arguments: list[str], _timeout: float) -> str:
        calls.append(arguments)
        if arguments == ["smartctl", "--scan-open"]:
            return fixture["smartctl_scan"]
        return json.dumps(fixture["smart"][arguments[-1]])

    result = read_smart_devices(tmp_path, runner, 2.0)
    assert result == [
        {"device": "sda", "status": "healthy", "temperature_c": 29},
        {"device": "sdb", "status": "healthy", "temperature_c": 28},
        {
            "device": "nvme0n1",
            "status": "healthy",
            "temperature_c": 20,
            "remaining_life_percent": 98.0,
        },
        {
            "device": "nvme1n1",
            "status": "healthy",
            "temperature_c": 32,
            "remaining_life_percent": 75.0,
        },
    ]
    assert calls == [
        ["smartctl", "--scan-open"],
        ["smartctl", "-n", "standby", "-a", "-j", "-d", "sat", "/dev/sda"],
        ["smartctl", "-n", "standby", "-a", "-j", "-d", "sat", "/dev/sdb"],
        ["smartctl", "-n", "standby", "-a", "-j", "-d", "nvme", "/dev/nvme0"],
        ["smartctl", "-n", "standby", "-a", "-j", "-d", "nvme", "/dev/nvme1"],
    ]


def test_probe_fixture_preserves_sat_nonzero_exit_json_evidence() -> None:
    fixture = json.loads(PROBE_FIXTURE.read_text())
    for endpoint in ("/dev/sda", "/dev/sdb"):
        payload = fixture["smart"][endpoint]
        assert payload["smartctl"]["exit_status"] == 4
        assert payload["smart_status"]["passed"] is True
        assert isinstance(payload["temperature"]["current"], int)


def _write_smart_cache(path: Path, generated_at: datetime, devices: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({
        "schema_version": 1,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "devices": devices,
    }))


def test_current_smart_cache_is_accepted(tmp_path: Path) -> None:
    now = datetime(2026, 9, 19, 16, 0, tzinfo=timezone.utc)
    cache = tmp_path / "smart.json"
    expected = [
        {"device": "sda", "status": "healthy", "temperature_c": 29.0},
        {"device": "nvme0n1", "status": "healthy", "temperature_c": 20.0, "remaining_life_percent": 98.0},
    ]
    _write_smart_cache(cache, now, expected)
    devices, current = read_smart_cache(cache, 1800.0, now)
    assert current is True
    assert devices == expected


def test_stale_smart_cache_preserves_inventory_as_unavailable(tmp_path: Path) -> None:
    now = datetime(2026, 9, 19, 16, 0, tzinfo=timezone.utc)
    cache = tmp_path / "smart.json"
    _write_smart_cache(cache, now - timedelta(hours=1), [
        {"device": "sda", "status": "healthy", "temperature_c": 29}
    ])
    assert read_smart_cache(cache, 1800.0, now) == (
        [{"device": "sda", "status": "unavailable", "temperature_c": None}], False
    )


def test_missing_or_corrupt_smart_cache_uses_previous_inventory(tmp_path: Path) -> None:
    cache = tmp_path / "smart.json"
    previous = [{"device": "sdb", "status": "healthy", "temperature_c": 28}]
    expected = [{"device": "sdb", "status": "unavailable", "temperature_c": None}]
    assert read_smart_cache(cache, 1800.0, datetime.now(timezone.utc), previous) == (expected, False)
    cache.write_text("not json")
    assert read_smart_cache(cache, 1800.0, datetime.now(timezone.utc), previous) == (expected, False)


def test_future_and_wrong_schema_smart_cache_are_rejected(tmp_path: Path) -> None:
    now = datetime(2026, 9, 19, 16, 0, tzinfo=timezone.utc)
    cache = tmp_path / "smart.json"
    payload = [{"device": "sda", "status": "healthy", "temperature_c": 29}]
    _write_smart_cache(cache, now + timedelta(minutes=2), payload)
    assert read_smart_cache(cache, 1800.0, now) == (
        [{"device": "sda", "status": "unavailable", "temperature_c": None}], False
    )
    data = json.loads(cache.read_text())
    data["schema_version"] = 2
    cache.write_text(json.dumps(data))
    assert read_smart_cache(cache, 1800.0, now) == ([], False)


def test_invalid_smart_values_and_duplicate_devices_are_rejected(tmp_path: Path) -> None:
    now = datetime(2026, 9, 19, 16, 0, tzinfo=timezone.utc)
    cache = tmp_path / "smart.json"
    previous = [{"device": "sda", "status": "healthy", "temperature_c": 29}]
    _write_smart_cache(cache, now, [
        {"device": "sda", "status": "healthy", "temperature_c": float("nan")}
    ])
    assert read_smart_cache(cache, 1800.0, now, previous)[0][0]["status"] == "unavailable"
    _write_smart_cache(cache, now, previous + previous)
    assert read_smart_cache(cache, 1800.0, now, previous)[1] is False


def test_nvme_hwmon_temperature_maps_to_namespace_and_overrides_smart(tmp_path: Path) -> None:
    hwmon_root = tmp_path / "hwmon"
    block_root = tmp_path / "block"
    controller = tmp_path / "devices" / "pci" / "nvme" / "nvme0"
    controller.mkdir(parents=True)
    (block_root / "nvme0n1" / "device").mkdir(parents=True)
    hwmon = hwmon_root / "hwmon0"
    hwmon.mkdir(parents=True)
    (hwmon / "name").write_text("nvme")
    (hwmon / "temp1_input").write_text("19850")
    (hwmon / "device").symlink_to(controller, target_is_directory=True)
    temperatures = read_nvme_temperatures(hwmon_root, block_root)
    assert temperatures == {"nvme0n1": 19.85}
    assert merge_nvme_temperatures(
        [{"device": "nvme0n1", "status": "healthy", "temperature_c": 20}], temperatures
    ) == [{"device": "nvme0n1", "status": "healthy", "temperature_c": 19.85}]


def test_nvme_hwmon_temperature_survives_unavailable_smart() -> None:
    assert merge_nvme_temperatures([], {"nvme1n1": 31.85}) == [
        {"device": "nvme1n1", "status": "unavailable", "temperature_c": 31.85}
    ]
