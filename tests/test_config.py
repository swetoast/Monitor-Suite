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



@pytest.mark.parametrize(
    ("name", "attribute"),
    [
        ("MONITOR_SUITE_THERMAL_INTERVAL", "thermal_sample_interval_seconds"),
        ("MONITOR_SUITE_POWER_INTERVAL", "power_sample_interval_seconds"),
        ("MONITOR_SUITE_RAID_IDLE_INTERVAL", "raid_idle_interval_seconds"),
        ("MONITOR_SUITE_RAID_ACTIVE_INTERVAL", "raid_active_interval_seconds"),
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
    ],
)
def test_probe_intervals_reject_zero(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "0")
    with pytest.raises(ValueError, match="greater than zero"):
        Settings.from_env()


def test_non_ascii_or_whitespace_api_key_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MONITOR_SUITE_HOST", "0.0.0.0")
    for value in ("a" * 31 + "å", "a" * 16 + " " + "a" * 16, "a" * 16 + "\t" + "a" * 16):
        monkeypatch.setenv("MONITOR_SUITE_API_KEY", value)
        with pytest.raises(ValueError, match="printable ASCII"):
            Settings.from_env()


def test_api_key_surrounding_whitespace_is_trimmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MONITOR_SUITE_HOST", "0.0.0.0")
    monkeypatch.setenv("MONITOR_SUITE_API_KEY", "  " + "a" * 32 + "\n")
    assert Settings.from_env().api_key == "a" * 32


def test_explicit_virtual_interface_is_rejected_by_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for value in ("wg0", "tun0", "tailscale0", "virbr0", "vxlan0"):
        monkeypatch.setenv("MONITOR_SUITE_NETWORK_INTERFACE", value)
        with pytest.raises(ValueError, match="physical network interface"):
            Settings.from_env()


def test_explicit_cellular_interface_is_accepted_by_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MONITOR_SUITE_NETWORK_INTERFACE", "wwan0")
    assert Settings.from_env().network_interface == "wwan0"


@pytest.mark.parametrize("value", ["inf", "-inf", "nan"])
def test_non_finite_positive_float_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("MONITOR_SUITE_SAMPLE_INTERVAL", value)
    with pytest.raises(ValueError, match="finite number greater than zero"):
        Settings.from_env()


@pytest.mark.parametrize("value", ["inf", "nan"])
def test_non_finite_optional_power_overrides_are_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("MONITOR_SUITE_FULL_LOAD_W", value)
    with pytest.raises(ValueError, match="finite number greater than zero"):
        Settings.from_env()


@pytest.mark.parametrize("value", ["0.0.0.0/0", "::/0"])
def test_trust_everyone_proxy_network_is_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("MONITOR_SUITE_TRUSTED_PROXIES", value)
    with pytest.raises(ValueError, match="must not trust every IP address"):
        Settings.from_env()
