"""Architecture routing tests for aarch64 and amd64."""

from pathlib import Path

import pytest

from monitor_suite_agent.config import Settings
from monitor_suite_agent.telemetry import (
    Paths,
    TelemetrySampler,
    UnsupportedArchitectureError,
    detect_architecture,
)


def test_detect_architecture_normalizes_supported_aliases() -> None:
    assert detect_architecture("aarch64") == "aarch64"
    assert detect_architecture("arm64") == "aarch64"
    assert detect_architecture("x86_64") == "amd64"
    assert detect_architecture("AMD64") == "amd64"


def test_detect_architecture_rejects_unknown_machine() -> None:
    with pytest.raises(UnsupportedArchitectureError, match="riscv64"):
        detect_architecture("riscv64")


def test_aarch64_keeps_existing_raspberry_pi_route(tmp_path: Path) -> None:
    model = tmp_path / "model"
    model.write_text("Raspberry Pi 5 Model B Rev 1.0\n")
    sampler = TelemetrySampler(
        Settings(),
        paths=Paths(root=tmp_path, device_model=model),
        machine=lambda: "aarch64",
    )

    assert sampler.architecture == "aarch64"
    assert sampler.device["architecture"] == "aarch64"
    assert sampler.model == "Raspberry Pi 5 Model B Rev 1.0"
    assert sampler.profile is not None


def test_amd64_route_does_not_run_raspberry_pi_firmware_commands(
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []

    def runner(arguments: list[str], timeout: float) -> None:
        commands.append(arguments)
        return None

    sampler = TelemetrySampler(
        Settings(),
        paths=Paths(
            root=tmp_path,
            proc_stat=tmp_path / "stat",
            proc_meminfo=tmp_path / "meminfo",
            proc_uptime=tmp_path / "uptime",
            proc_mountinfo=tmp_path / "mountinfo",
            proc_diskstats=tmp_path / "diskstats",
            proc_net_route=tmp_path / "route",
            device_model=tmp_path / "model",
            os_release=tmp_path / "os-release",
            cpu_root=tmp_path / "cpu",
            thermal_root=tmp_path / "thermal",
            hwmon_root=tmp_path / "hwmon",
            net_root=tmp_path / "net",
            block_root=tmp_path / "block",
        ),
        command_runner=runner,
        machine=lambda: "x86_64",
    )

    result = sampler._collect_sync()

    assert sampler.architecture == "amd64"
    assert result["device"]["architecture"] == "amd64"
    assert result["power"]["source"] == "unavailable"
    assert result["health"]["status"] == "unavailable"
    assert not any(command and command[0] == "vcgencmd" for command in commands)


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def test_amd64_dmi_uses_only_existing_model_field(tmp_path: Path) -> None:
    dmi = tmp_path / "dmi"
    _write(dmi / "product_name", "Generic x86 System\n")
    _write(dmi / "sys_vendor", "Excluded Vendor\n")
    _write(dmi / "board_name", "Excluded Board\n")
    _write(dmi / "chassis_type", "3\n")
    _write(dmi / "product_uuid", "excluded-uuid\n")
    _write(dmi / "product_serial", "excluded-serial\n")

    sampler = TelemetrySampler(
        Settings(),
        paths=Paths(
            root=tmp_path,
            dmi_root=dmi,
            os_release=tmp_path / "os-release",
        ),
        machine=lambda: "amd64",
    )

    assert sampler.device == {
        "model": "Generic x86 System",
        "operating_system": "Unknown Linux",
        "kernel_version": sampler.device["kernel_version"],
        "architecture": "amd64",
    }
    assert "vendor" not in repr(sampler.device).lower()
    assert "board" not in repr(sampler.device).lower()
    assert "chassis" not in repr(sampler.device).lower()
    assert "serial" not in repr(sampler.device).lower()
    assert "uuid" not in repr(sampler.device).lower()


def test_x86_package_temperature_has_priority(tmp_path: Path) -> None:
    from monitor_suite_agent.telemetry import read_cpu_temperature_c

    thermal = tmp_path / "thermal"
    hwmon = tmp_path / "hwmon"
    _write(thermal / "thermal_zone0/type", "acpitz\n")
    _write(thermal / "thermal_zone0/temp", "27000\n")
    _write(thermal / "thermal_zone1/type", "x86_pkg_temp\n")
    _write(thermal / "thermal_zone1/temp", "43000\n")
    _write(hwmon / "hwmon0/name", "coretemp\n")
    _write(hwmon / "hwmon0/temp1_label", "Package id 0\n")
    _write(hwmon / "hwmon0/temp1_input", "41000\n")

    assert read_cpu_temperature_c(thermal, hwmon) == 43.0


def test_coretemp_package_and_k10temp_labels_are_supported(tmp_path: Path) -> None:
    from monitor_suite_agent.telemetry import read_cpu_temperature_c

    thermal = tmp_path / "thermal"
    intel = tmp_path / "intel"
    _write(intel / "hwmon0/name", "coretemp\n")
    _write(intel / "hwmon0/temp1_label", "Package id 0\n")
    _write(intel / "hwmon0/temp1_input", "41500\n")
    _write(intel / "hwmon0/temp2_label", "Core 0\n")
    _write(intel / "hwmon0/temp2_input", "39000\n")
    assert read_cpu_temperature_c(thermal, intel) == 41.5

    amd = tmp_path / "amd"
    _write(amd / "hwmon0/name", "k10temp\n")
    _write(amd / "hwmon0/temp1_label", "Tctl\n")
    _write(amd / "hwmon0/temp1_input", "52500\n")
    assert read_cpu_temperature_c(thermal, amd) == 52.5


def test_amd64_cooling_averages_active_exact_fan_inputs(tmp_path: Path) -> None:
    from monitor_suite_agent.telemetry import read_amd64_cooling

    hwmon = tmp_path / "hwmon"
    for index, rpm in enumerate((720, 480, 1320, 710, 0, 950), start=1):
        _write(hwmon / f"hwmon0/fan{index}_input", f"{rpm}\n")
    _write(hwmon / "hwmon0/fan1_min", "200\n")
    _write(hwmon / "hwmon0/pwm1", "128\n")
    _write(hwmon / "hwmon0/pwm1_enable", "1\n")

    assert read_amd64_cooling(hwmon) == {
        "state": "active",
        "fan_speed_rpm": 836,
        "fan_count": 6,
        "active_fan_count": 5,
    }


def test_amd64_cooling_idle_and_unavailable(tmp_path: Path) -> None:
    from monitor_suite_agent.telemetry import read_amd64_cooling

    hwmon = tmp_path / "hwmon"
    _write(hwmon / "hwmon0/fan1_input", "0\n")
    assert read_amd64_cooling(hwmon) == {
        "state": "idle",
        "fan_speed_rpm": 0,
        "fan_count": 1,
        "active_fan_count": 0,
    }
    assert read_amd64_cooling(tmp_path / "missing") == {
        "state": "unavailable",
        "fan_speed_rpm": None,
    }


def test_amd64_sampler_uses_current_rapl_cache_without_changing_power_state(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone
    import json

    cache = tmp_path / "power.json"
    now = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
    cache.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-09-20T12:00:00Z",
                "value_w": 8.125,
                "source": "rapl_package",
                "domain": "package",
            }
        )
    )
    sampler = TelemetrySampler(
        Settings(power_cache_file=cache),
        paths=Paths(root=tmp_path),
        machine=lambda: "amd64",
        now=lambda: now,
    )

    result = sampler._collect_sync()

    assert result["power"] == {
        "value_w": 8.125,
        "source": "rapl_package",
        "input_voltage_v": None,
        "domain": "package",
    }
    assert result["health"]["status"] == "unavailable"
