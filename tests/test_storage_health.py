"""RAID and SMART reduction tests."""

import json
from pathlib import Path

from monitor_suite_agent.telemetry import apply_member_smart, parse_smart_json, read_raid_arrays


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


def test_clean_raid0_and_member_smart(tmp_path: Path) -> None:
    make_array(tmp_path)
    arrays = read_raid_arrays(tmp_path)
    apply_member_smart(arrays, [
        {"device": "sda", "status": "healthy"},
        {"device": "sdb", "status": "healthy"},
    ])
    assert arrays == [{
        "name": "md0", "status": "healthy", "raid_level": "RAID0",
        "active_members": 2, "expected_members": 2, "failed_members": 0,
        "redundancy": "none", "smart_status": "healthy",
    }]


def test_raid0_missing_member_is_failed(tmp_path: Path) -> None:
    make_array(tmp_path, degraded=1)
    (tmp_path / "md0/md/dev-sdb/state").write_text("faulty")
    assert read_raid_arrays(tmp_path)[0]["status"] == "failed"


def test_active_operation_progress(tmp_path: Path) -> None:
    make_array(tmp_path, level="raid1", action="resync")
    (tmp_path / "md0/md/sync_completed").write_text("25 / 100")
    result = read_raid_arrays(tmp_path)[0]
    assert result["status"] == "resyncing"
    assert result["progress_percent"] == 25.0


def test_known_disk_remains_stable_when_collection_temporarily_fails(tmp_path: Path) -> None:
    disk = tmp_path / "sda"
    (disk / "device").mkdir(parents=True)
    previous = [{"device": "sda", "status": "healthy", "temperature_c": 30}]
    from monitor_suite_agent.telemetry import read_smart_devices
    result = read_smart_devices(tmp_path, lambda _args, _timeout: None, 2.0, previous)
    assert result == [{"device": "sda", "status": "unavailable", "temperature_c": None}]


def test_smart_collection_does_not_wake_standby_disks(tmp_path: Path) -> None:
    disk = tmp_path / "sda"
    (disk / "device").mkdir(parents=True)
    calls = []
    from monitor_suite_agent.telemetry import read_smart_devices
    read_smart_devices(tmp_path, lambda args, _timeout: calls.append(args) or None, 2.0)
    assert calls == [["smartctl", "-n", "standby", "-a", "-j", "/dev/sda"]]


def test_warning_is_not_hidden_by_unavailable_member() -> None:
    arrays = [{"_members": ["sda", "sdb"], "smart_status": "unavailable"}]
    apply_member_smart(arrays, [
        {"device": "sda", "status": "warning"},
        {"device": "sdb", "status": "unavailable"},
    ])
    assert arrays[0]["smart_status"] == "warning"


def test_recovery_state_takes_priority_over_degraded(tmp_path: Path) -> None:
    make_array(tmp_path, level="raid1", degraded=1, action="recover")
    (tmp_path / "md0/md/dev-sdb/state").write_text("spare,recovering")
    result = read_raid_arrays(tmp_path)[0]
    assert result["status"] == "recovering"
    assert result["active_members"] == 1
    assert result["redundancy"] == "reduced"


def test_standby_disk_keeps_last_known_values(tmp_path: Path) -> None:
    disk = tmp_path / "sda"
    (disk / "device").mkdir(parents=True)
    previous = [{"device": "sda", "status": "healthy", "temperature_c": 30}]
    standby = json.dumps({
        "smartctl": {"messages": [{"string": "Device is in STANDBY mode"}]}
    })
    from monitor_suite_agent.telemetry import read_smart_devices
    result = read_smart_devices(tmp_path, lambda _args, _timeout: standby, 2.0, previous)
    assert result == previous
