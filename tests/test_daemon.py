"""Daemon regression tests based on both supplied Raspberry Pi 5 probes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from monitor_suite_agent.config import Settings
from monitor_suite_agent.telemetry import (
    CpuTimes,
    RateCounter,
    booted_at,
    build_health,
    calculate_cpu_usage,
    calculate_rates,
    memory_status,
    parse_cpu_times,
    parse_diskstats,
    parse_pmic,
    parse_throttling,
    resolve_root_device,
    select_network_interface,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_power_probe_regression_fixture() -> None:
    text = (FIXTURES / "power_probe_pi5.txt").read_text()
    cpu_lines = [line for line in text.splitlines() if line.startswith("cpu  ")]
    first = parse_cpu_times(cpu_lines[0])
    second = parse_cpu_times(cpu_lines[1])
    assert first is not None and second is not None
    usage = calculate_cpu_usage(first, second)
    assert usage == pytest.approx(30.861244, rel=0.000001)

    flags = parse_throttling(text)
    assert flags is not None
    assert flags["raw"] == 0
    assert build_health(flags) == {
        "status": "ok",
        "power_supply": "ok",
        "thermal_state": "normal",
        "performance_state": "normal",
    }

    rails = parse_pmic(text)
    assert len(rails) == 14
    assert rails["VDD_CORE"]["voltage_v"] == 0.7212447
    assert rails["VDD_CORE"]["current_a"] == 1.6967
    assert rails["VDD_CORE"]["power_w"] == pytest.approx(1.223736, abs=0.000001)
    assert rails["EXT5V"]["voltage_v"] == 5.0987
    assert rails["EXT5V"]["current_a"] is None
    assert rails["EXT5V"]["power_w"] is None


def test_system_probe_memory_fixture() -> None:
    text = (FIXTURES / "system_probe_pi5.txt").read_text()
    status = memory_status(text)
    assert status == {
        "used_percent": 45.0,
        "available_bytes": 4_647_550_976,
        "total_bytes": 8_453_947_392,
    }


def test_system_probe_root_device_and_disk_fixture(tmp_path: Path) -> None:
    text = (FIXTURES / "system_probe_pi5.txt").read_text()
    block = tmp_path / "block"
    (block / "nvme0n1p2").mkdir(parents=True)
    (block / "nvme0n1p2" / "partition").write_text("2")
    (block / "nvme0n1").mkdir()
    assert resolve_root_device(text, block) == "nvme0n1"
    counter = parse_diskstats(text, "nvme0n1", 10.0)
    assert counter == RateCounter(2_932_700 * 512, 2_360_266 * 512, 10.0)


def test_physical_interface_preferred_and_virtual_interfaces_filtered(tmp_path: Path) -> None:
    net = tmp_path / "net"
    for name in ("eth0", "docker0", "br-92b62be64466", "veth8d09df9", "lo"):
        (net / name).mkdir(parents=True)
    route = tmp_path / "route"
    route.write_text("Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\neth0 00000000 0100000A 0003 0 0 100 00000000 0 0 0\n")
    assert select_network_interface(net, route) == "eth0"


def test_rate_calculation_and_reset_handling() -> None:
    assert calculate_rates(RateCounter(1000, 2000, 10.0), RateCounter(4000, 8000, 12.0)) == (1500, 3000)
    assert calculate_rates(RateCounter(4000, 8000, 10.0), RateCounter(100, 100, 11.0)) == (None, None)
    assert calculate_rates(None, RateCounter(100, 100, 11.0)) == (None, None)


def test_boot_timestamp_has_stable_utc_format() -> None:
    now = datetime(2026, 9, 19, 8, 25, 28, tzinfo=timezone.utc)
    assert booted_at(5045.0, now) == "2026-09-19T07:01:23Z"


def test_historical_flags_do_not_claim_current_problem() -> None:
    flags = parse_throttling("throttled=0x50000")
    assert flags is not None
    assert build_health(flags)["status"] == "ok"


def test_current_flags_have_clear_precedence() -> None:
    flags = parse_throttling("throttled=0xf")
    assert flags is not None
    health = build_health(flags)
    assert health == {
        "status": "critical",
        "power_supply": "under_voltage",
        "thermal_state": "limited",
        "performance_state": "throttled",
    }


def test_missing_sources_are_safe() -> None:
    assert parse_cpu_times(None) is None
    assert parse_pmic("Bad/missing arguments.") == {}
    assert parse_throttling("nonsense") is None
    assert memory_status(None) == {"used_percent": None, "available_bytes": None, "total_bytes": None}


def test_settings_require_complete_calibration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONITOR_SUITE_IDLE_W", "2.8")
    monkeypatch.delenv("MONITOR_SUITE_FULL_LOAD_W", raising=False)
    with pytest.raises(ValueError, match="must be set together"):
        Settings.from_env()


def test_cpu_counter_reset_is_not_reported_as_usage() -> None:
    assert calculate_cpu_usage(CpuTimes(1000, 800), CpuTimes(10, 5)) is None

def test_full_sampler_snapshot_from_pi5_fixture_tree(tmp_path: Path) -> None:
    from monitor_suite_agent.telemetry import Paths, TelemetrySampler

    root = tmp_path / "root"
    root.mkdir()
    proc = tmp_path / "proc"
    sys = tmp_path / "sys"
    (proc / "self").mkdir(parents=True)
    (proc / "net").mkdir()
    (proc / "device-tree").mkdir()
    (tmp_path / "etc").mkdir()
    cpu = sys / "devices/system/cpu/cpu0/cpufreq"
    cpu.mkdir(parents=True)
    thermal = sys / "class/thermal"
    hwmon = sys / "class/hwmon"
    net = sys / "class/net"
    block = sys / "class/block"
    for directory in (thermal, hwmon, net, block):
        directory.mkdir(parents=True)

    (proc / "device-tree/model").write_bytes(b"Raspberry Pi 5 Model B Rev 1.0\x00")
    (tmp_path / "etc/os-release").write_text('PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\n')
    (proc / "stat").write_text("cpu  100 0 50 850 0 0 0 0 0 0\n")
    (proc / "meminfo").write_text("MemTotal: 8255808 kB\nMemAvailable: 4538624 kB\n")
    (proc / "uptime").write_text("5045.00 0.00\n")
    (proc / "self/mountinfo").write_text("25 1 259:2 / / rw - ext4 /dev/nvme0n1p2 rw\n")
    (proc / "diskstats").write_text("259 0 nvme0n1 1 0 100 0 1 0 200 0 0 0 0 0 0 0 0 0\n")
    (proc / "net/route").write_text("Iface Destination Gateway Flags\neth0 00000000 0100000A 0003\n")
    (cpu / "scaling_cur_freq").write_text("1500000\n")
    (cpu / "scaling_max_freq").write_text("2400000\n")

    zone = thermal / "thermal_zone9"
    zone.mkdir()
    (zone / "type").write_text("cpu-thermal\n")
    (zone / "temp").write_text("34750\n")
    cooler = thermal / "cooling_device4"
    cooler.mkdir()
    (cooler / "type").write_text("pwm-fan\n")
    (cooler / "cur_state").write_text("0\n")
    fan = hwmon / "hwmon8"
    fan.mkdir()
    (fan / "name").write_text("pwmfan\n")
    (fan / "fan1_input").write_text("0\n")

    eth = net / "eth0"
    (eth / "statistics").mkdir(parents=True)
    (eth / "operstate").write_text("up\n")
    (eth / "speed").write_text("1000\n")
    (eth / "statistics/rx_bytes").write_text("1000\n")
    (eth / "statistics/tx_bytes").write_text("2000\n")
    (block / "nvme0n1").mkdir()
    (block / "nvme0n1p2").mkdir()
    (block / "nvme0n1p2/partition").write_text("2\n")

    pmic = (FIXTURES / "power_probe_pi5.txt").read_text()
    def command(arguments: list[str], _timeout: float) -> str | None:
        return "throttled=0x0" if arguments[-1] == "get_throttled" else pmic

    clock = iter((10.0, 11.0))
    paths = Paths(
        root=root,
        proc_stat=proc / "stat",
        proc_meminfo=proc / "meminfo",
        proc_uptime=proc / "uptime",
        proc_mountinfo=proc / "self/mountinfo",
        proc_diskstats=proc / "diskstats",
        proc_net_route=proc / "net/route",
        device_model=proc / "device-tree/model",
        os_release=tmp_path / "etc/os-release",
        cpu_root=sys / "devices/system/cpu",
        thermal_root=thermal,
        hwmon_root=hwmon,
        net_root=net,
        block_root=block,
    )
    sampler = TelemetrySampler(
        Settings(slow_sample_interval_seconds=30.0),
        paths=paths,
        command_runner=command,
        monotonic=lambda: next(clock),
        now=lambda: datetime(2026, 9, 19, 8, 25, 28, tzinfo=timezone.utc),
    )
    first = sampler._collect_sync()
    assert first["device"]["model"] == "Raspberry Pi 5 Model B Rev 1.0"
    assert first["cpu"] == {"usage_percent": 0.0, "frequency_mhz": 1500.0, "temperature_c": 34.8}
    assert first["memory"]["used_percent"] == 45.0
    assert first["power"]["source"] == "internal_rails"
    assert first["power"]["value_w"] > 2.0
    assert first["power"]["input_voltage_v"] == 5.0987
    assert first["cooling"] == {"state": "idle", "fan_speed_rpm": 0}
    assert first["network"]["interface"] == "eth0"
    assert first["network"]["download_bytes_per_second"] is None
    assert first["disk_activity"]["read_bytes_per_second"] is None
    assert first["system"]["booted_at"] == "2026-09-19T07:01:23Z"
    assert first["health"]["status"] == "ok"
    assert "issues" not in first["health"]

    (proc / "stat").write_text("cpu  130 0 60 900 0 0 0 0 0 0\n")
    (eth / "statistics/rx_bytes").write_text("3000\n")
    (eth / "statistics/tx_bytes").write_text("5000\n")
    (proc / "diskstats").write_text("259 0 nvme0n1 1 0 104 0 1 0 208 0 0 0 0 0 0 0 0 0\n")
    second = sampler._collect_sync()
    assert second["cpu"]["usage_percent"] == 44.4
    assert second["network"]["download_bytes_per_second"] == 2000
    assert second["network"]["upload_bytes_per_second"] == 3000
    assert second["disk_activity"] == {"read_bytes_per_second": 2048, "write_bytes_per_second": 4096}


def test_explicit_physical_network_interface_selection(tmp_path: Path) -> None:
    net = tmp_path / "net"
    (net / "eth0/device").mkdir(parents=True)
    (net / "wlan0/device").mkdir(parents=True)
    route = tmp_path / "route"
    route.write_text("Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\neth0 00000000 00000000 0001 0 0 0 00000000 0 0 0\n")
    assert select_network_interface(net, route, "wlan0") == "wlan0"
    assert select_network_interface(net, route, "missing0") is None
