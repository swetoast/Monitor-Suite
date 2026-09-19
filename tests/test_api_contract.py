"""Public route and schema contract tests."""

from monitor_suite_agent.app import app


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
    for excluded in (
        '"serial_number"', '"wwn"', '"power_on_hours"',
        '"unsafe_shutdowns"', '"load_cycle_count"',
    ):
        assert excluded not in source
