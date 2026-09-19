"""Configuration validation tests."""
import pytest
from monitor_suite_agent.config import Settings

def test_network_interface_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONITOR_SUITE_NETWORK_INTERFACE", "eth0")
    assert Settings.from_env().network_interface == "eth0"

@pytest.mark.parametrize("value", ["lo", "docker0", "br-test", "veth123", "bad name", "x" * 16])
def test_virtual_or_invalid_network_interface_is_rejected(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("MONITOR_SUITE_NETWORK_INTERFACE", value)
    with pytest.raises(ValueError, match="physical network interface"):
        Settings.from_env()


def test_smart_interval_defaults_to_fifteen_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONITOR_SUITE_SMART_INTERVAL", raising=False)
    assert Settings.from_env().smart_sample_interval_seconds == 900.0


def test_smart_interval_can_be_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONITOR_SUITE_SMART_INTERVAL", "1800")
    assert Settings.from_env().smart_sample_interval_seconds == 1800.0


@pytest.mark.parametrize(
    ("name", "attribute"),
    [
        ("MONITOR_SUITE_THERMAL_INTERVAL", "thermal_sample_interval_seconds"),
        ("MONITOR_SUITE_POWER_INTERVAL", "power_sample_interval_seconds"),
        ("MONITOR_SUITE_RAID_IDLE_INTERVAL", "raid_idle_interval_seconds"),
        ("MONITOR_SUITE_RAID_ACTIVE_INTERVAL", "raid_active_interval_seconds"),
        ("MONITOR_SUITE_SMART_RETRY_INTERVAL", "smart_retry_interval_seconds"),
    ],
)
def test_probe_intervals_are_configurable(
    monkeypatch: pytest.MonkeyPatch, name: str, attribute: str
) -> None:
    monkeypatch.setenv(name, "17")
    assert getattr(Settings.from_env(), attribute) == 17.0


@pytest.mark.parametrize(
    "name",
    [
        "MONITOR_SUITE_THERMAL_INTERVAL",
        "MONITOR_SUITE_POWER_INTERVAL",
        "MONITOR_SUITE_RAID_IDLE_INTERVAL",
        "MONITOR_SUITE_RAID_ACTIVE_INTERVAL",
        "MONITOR_SUITE_SMART_RETRY_INTERVAL",
    ],
)
def test_probe_intervals_reject_zero(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "0")
    with pytest.raises(ValueError, match="greater than zero"):
        Settings.from_env()
