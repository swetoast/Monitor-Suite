"""Public route and schema contract tests."""

from pathlib import Path

from monitor_suite_agent.app import app
from monitor_suite_agent.models import RaspberryPiHealth
from monitor_suite_agent.telemetry import build_health, read_network_metadata


def test_routes_are_intentionally_small() -> None:
    paths = {route.path for route in app.routes}
    assert "/status" in paths
    assert "/health" in paths
    assert "/docs" not in paths
    assert "/openapi.json" not in paths
    assert "/telemetry" not in paths
    assert "/power_usage" not in paths


def test_no_removed_public_fields_in_source() -> None:
    source = __import__("pathlib").Path("monitor_suite_agent/telemetry.py").read_text()
    assert '"issues"' not in source
    assert '"pmic_rails"' not in source
    assert '"raw_throttling"' not in source


def test_storage_health_public_field_names_are_intentional() -> None:
    source = __import__("pathlib").Path("monitor_suite_agent/telemetry.py").read_text()
    for approved in (
        '"raid_level"', '"active_members"', '"expected_members"',
        '"failed_members"', '"redundancy"',
        '"temperature_c"', '"remaining_life_percent"',
    ):
        assert approved in source
    assert '"smart_status"' in source  # physical-drive SMART field remains
    raid_source = source[source.index('def read_raid_arrays'):source.index('def _smart_attributes')]
    assert '"smart_status"' not in raid_source
    assert '"_members"' not in raid_source
    for excluded in (
        '"serial_number"', '"wwn"', '"power_on_hours"',
        '"unsafe_shutdowns"', '"load_cycle_count"',
    ):
        assert excluded not in source


def test_firmware_health_values_always_match_public_model() -> None:
    unavailable = build_health(None)
    assert RaspberryPiHealth.model_validate(unavailable).status == "unavailable"

    flags = {
        "under_voltage_now": False,
        "frequency_capped_now": True,
        "throttled_now": False,
        "soft_temperature_limit_now": False,
    }
    assert RaspberryPiHealth.model_validate(build_health(flags)).status == "warning"
    flags["under_voltage_now"] = True
    assert RaspberryPiHealth.model_validate(build_health(flags)).status == "critical"


def test_missing_network_metadata_uses_public_unavailable_value(tmp_path: Path) -> None:
    assert read_network_metadata(tmp_path, None)["status"] == "unavailable"
