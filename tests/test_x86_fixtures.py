"""Acceptance checks for privacy-scrubbed x86 evidence fixtures."""

from pathlib import Path
import re

from monitor_suite_agent.telemetry import read_amd64_cooling, read_cpu_temperature_c

FIXTURES = Path(__file__).parent / "fixtures"


def _values(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            result[key] = value
    return result


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def test_generic_x86_fixture_has_correct_exact_counts() -> None:
    values = _values(FIXTURES / "monitor_suite_x86_fixture.txt")
    assert values["format_version"] == "4"
    assert values["pwm_input_count"] == "5"
    assert values["physical_disk_count"] == "2"
    assert values["powercap_energy_counter_count"] == "0"


def test_desktop_fan_fixture_drives_expected_public_cooling(tmp_path: Path) -> None:
    values = _values(FIXTURES / "monitor_suite_amd64_fan_fixture.txt")
    hwmon = tmp_path / "hwmon"
    readings = [
        int(value)
        for key, value in sorted(values.items())
        if re.fullmatch(r"provider_[0-9]+_fan_[0-9]+_input_rpm", key)
    ]
    for index, rpm in enumerate(readings, start=1):
        _write(hwmon / f"hwmon0/fan{index}_input", str(rpm))

    assert read_amd64_cooling(hwmon) == {
        "state": "active",
        "fan_speed_rpm": 836,
        "fan_count": 6,
        "active_fan_count": 5,
    }


def test_x86_fixture_drives_package_temperature_selection(tmp_path: Path) -> None:
    values = _values(FIXTURES / "monitor_suite_x86_fixture.txt")
    thermal = tmp_path / "thermal"
    hwmon = tmp_path / "hwmon"
    _write(thermal / "thermal_zone0/type", values["zone_1_type"])
    _write(thermal / "thermal_zone0/temp", values["zone_1_temp_millic"])
    _write(thermal / "thermal_zone1/type", values["zone_2_type"])
    _write(thermal / "thermal_zone1/temp", values["zone_2_temp_millic"])
    assert read_cpu_temperature_c(thermal, hwmon) == 30.0


def test_x86_fixtures_contain_no_unique_or_network_identifiers() -> None:
    forbidden_keys = re.compile(
        r"(?im)^(?:hostname|username|ip_address|mac_address|serial|uuid|wwn|asset_tag)="
    )
    ipv4 = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")
    mac = re.compile(r"\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b", re.IGNORECASE)
    for path in FIXTURES.glob("monitor_suite_*x86*.txt"):
        text = path.read_text(encoding="utf-8")
        assert not forbidden_keys.search(text), path.name
        assert not ipv4.search(text), path.name
        assert not mac.search(text), path.name
        assert "/home/" not in text
        assert "/mnt/" not in text
