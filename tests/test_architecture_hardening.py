"""Architecture-hardening regression tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from monitor_suite_agent.config import Settings
from monitor_suite_agent.models import HealthResponse, StatusResponse
from monitor_suite_agent.telemetry import TelemetrySampler, Paths


def test_smart_cache_has_bounded_freshness() -> None:
    settings = Settings()
    assert settings.smart_cache_max_age_seconds == 1800.0
    assert str(settings.smart_cache_file) == "/run/monitor-suite-agent/smart.json"


def test_health_degrades_after_repeated_expected_smart_failures() -> None:
    sampler = TelemetrySampler(Settings(stale_after_seconds=5), monotonic=lambda: 10.5)
    sampler._snapshot = {"complete": True}
    sampler._last_success_monotonic = 10.0
    sampler._probe_health["smart"].available = False
    sampler._probe_health["smart"].consecutive_failures = 2
    assert sampler.health() == {"status": "degraded", "sample_available": True}


def test_health_model_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        HealthResponse.model_validate({
            "status": "ok", "version": "2.1.0", "sample_available": True, "issues": []
        })



def test_status_model_forbids_accidental_public_fields() -> None:
    from monitor_suite_agent.models import CPUStatus
    with pytest.raises(ValidationError):
        CPUStatus.model_validate({
            "usage_percent": 1.0, "frequency_mhz": 1500.0,
            "temperature_c": 40.0, "debug": "not public"
        })


def test_probe_health_requires_two_failures_and_recovers() -> None:
    from monitor_suite_agent.telemetry import ProbeHealth
    state = ProbeHealth()
    state.update(True, 1.0)
    assert state.available is True
    state.update(False, 2.0)
    assert state.available is True
    state.update(False, 3.0)
    assert state.available is False
    state.update(True, 4.0)
    assert state.available is True
    assert state.consecutive_failures == 0
    assert state.last_success_monotonic == 4.0


def test_general_probe_failure_degrades_health() -> None:
    sampler = TelemetrySampler(Settings(stale_after_seconds=5), monotonic=lambda: 10.5)
    sampler._snapshot = {"complete": True}
    sampler._last_success_monotonic = 10.0
    sampler._probe_health["power"].available = False
    sampler._probe_health["power"].consecutive_failures = 2
    assert sampler.health() == {"status": "degraded", "sample_available": True}


def test_health_is_starting_before_first_complete_snapshot() -> None:
    sampler = TelemetrySampler(Settings(), monotonic=lambda: 10.0)
    assert sampler.health() == {"status": "starting", "sample_available": False}


def test_stale_snapshot_takes_precedence_over_probe_degradation() -> None:
    sampler = TelemetrySampler(Settings(stale_after_seconds=5), monotonic=lambda: 20.0)
    sampler._snapshot = {"complete": True}
    sampler._last_success_monotonic = 10.0
    sampler._probe_health["power"].available = False
    sampler._probe_health["power"].consecutive_failures = 2
    assert sampler.health() == {"status": "stale", "sample_available": True}


def test_every_expected_probe_group_can_degrade_health() -> None:
    for group in ("snapshot", "fast", "thermal", "cooling", "power", "resources", "raid", "smart"):
        sampler = TelemetrySampler(Settings(stale_after_seconds=5), monotonic=lambda: 10.5)
        sampler._snapshot = {"complete": True}
        sampler._last_success_monotonic = 10.0
        sampler._probe_health[group].available = False
        sampler._probe_health[group].consecutive_failures = 2
        assert sampler.health() == {"status": "degraded", "sample_available": True}


def test_one_probe_failure_does_not_degrade_health() -> None:
    sampler = TelemetrySampler(Settings(stale_after_seconds=5), monotonic=lambda: 10.5)
    sampler._snapshot = {"complete": True}
    sampler._last_success_monotonic = 10.0
    sampler._probe_health["resources"].available = True
    sampler._probe_health["resources"].consecutive_failures = 1
    assert sampler.health() == {"status": "ok", "sample_available": True}


def test_failed_collection_is_accounted_and_recovery_clears_it() -> None:
    import asyncio

    sampler = TelemetrySampler(Settings(stale_after_seconds=5), monotonic=lambda: 10.0)
    sampler._collect_sync = lambda: (_ for _ in ()).throw(RuntimeError("probe failed"))  # type: ignore[method-assign]

    for _ in range(2):
        with pytest.raises(RuntimeError, match="probe failed"):
            asyncio.run(sampler.collect_once())

    assert sampler._probe_health["snapshot"].available is False
    assert sampler._probe_health["snapshot"].consecutive_failures == 2

    sampler._collect_sync = lambda: {"complete": True}  # type: ignore[method-assign]
    assert asyncio.run(sampler.collect_once()) == {"complete": True}
    assert sampler._probe_health["snapshot"].available is True
    assert sampler._probe_health["snapshot"].consecutive_failures == 0


def test_start_survives_initial_collection_failure() -> None:
    import asyncio

    async def exercise() -> None:
        sampler = TelemetrySampler(Settings(sample_interval_seconds=60), monotonic=lambda: 10.0)
        sampler._collect_sync = lambda: (_ for _ in ()).throw(RuntimeError("initial failure"))  # type: ignore[method-assign]
        await sampler.start()
        try:
            assert sampler.health() == {"status": "starting", "sample_available": False}
            assert sampler._task is not None
            assert not hasattr(sampler, "_smart_task")
        finally:
            await sampler.stop()

    asyncio.run(exercise())


def test_unavailable_raid_result_counts_as_probe_failure(tmp_path: Path) -> None:
    block_root = tmp_path / "block"
    md = block_root / "md0" / "md"
    md.mkdir(parents=True)
    (md / "level").write_text("raid1")
    (md / "array_state").write_text("unknown")
    (md / "raid_disks").write_text("2")
    (md / "degraded").write_text("0")
    (md / "sync_action").write_text("idle")

    from monitor_suite_agent.telemetry import Paths

    sampler = TelemetrySampler(Settings(), paths=Paths(block_root=block_root))
    sampler._collect_sync()
    assert sampler._probe_health["raid"].consecutive_failures == 1
    sampler._raid_schedule.next_due = float("-inf")
    sampler._collect_sync()
    assert sampler._probe_health["raid"].available is False


def test_readme_is_user_focused_and_copyright_is_exact() -> None:
    expected = "Copyright (c) 2026 Toast"
    root = Path(__file__).parents[1]
    readme = (root / "README.md").read_text()
    package = (root / "monitor_suite_agent/__init__.py").read_text()
    required_sections = (
        "## Highlights",
        "## Table of contents",
        "## What it monitors",
        "## Server capabilities",
        "## How it works",
        "## Requirements",
        "## Installation",
        "## Using the API",
        "## Managing the service",
        "## Understanding health states",
        "## Storage monitoring",
        "## Power monitoring",
        "## Limitations",
        "## Security",
        "## Documentation",
        "## Support and feedback",
        "## Project information",
    )
    for section in required_sections:
        assert section in readme
    assert readme.startswith("# Monitor Suite Agent")
    assert readme.index("## Highlights") < readme.index("## Installation")
    for capability in (
        "Adaptive RAID polling",
        "Standby-aware SMART collection",
        "Failure isolation per probe group",
        "Cached, internally consistent snapshots",
    ):
        assert capability in readme
    assert readme.count("Home Assistant") <= 2
    assert "One status source" not in readme
    assert "One-command installation" not in readme
    assert "Automatic background sampling" not in readme
    assert "curl -fsSL https://raw.githubusercontent.com/swetoast/Monitor-Suite/main/install.sh | sudo sh" in readme
    assert "Home Assistant is one possible future consumer" in readme
    assert "No distribution license is currently declared" in readme
    assert "Last updated: September 19, 2026." in readme
    assert readme.splitlines().count(expected) == 1
    assert package.splitlines().count(f'__copyright__ = "{expected}"') == 1
    assert not any(
        0x1F300 <= ord(character) <= 0x1FAFF
        for character in readme
    )


def test_setuptools_packages_only_the_application() -> None:
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text()
    assert '[tool.setuptools]' in pyproject
    assert 'packages = ["monitor_suite_agent"]' in pyproject


def test_retired_in_process_smart_controls_are_absent() -> None:
    root = Path(__file__).parents[1]
    config = (root / "monitor_suite_agent/config.py").read_text()
    telemetry = (root / "monitor_suite_agent/telemetry.py").read_text()
    assert "smart_sample_interval_seconds" not in config
    assert "smart_retry_interval_seconds" not in config
    assert "smart_runner" not in telemetry


def test_fast_probe_depends_only_on_cpu_counters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from monitor_suite_agent import telemetry

    proc_stat = tmp_path / "stat"
    proc_stat.write_text("cpu  100 0 50 850 0 0 0 0 0 0\n")
    sampler = TelemetrySampler(
        Settings(),
        paths=Paths(root=tmp_path, proc_stat=proc_stat),
        machine=lambda: "amd64",
    )
    monkeypatch.setattr(telemetry, "read_frequency_mhz", lambda path: None)
    monkeypatch.setattr(telemetry, "read_network_counter", lambda *args: None)
    monkeypatch.setattr(telemetry, "parse_diskstats", lambda *args: None)

    sampler._collect_sync()

    assert sampler._probe_health["fast"].available is True


def test_missing_amd64_power_cache_is_capability_gap(tmp_path: Path) -> None:
    sampler = TelemetrySampler(
        Settings(power_cache_file=tmp_path / "missing-power.json"),
        paths=Paths(root=tmp_path),
        machine=lambda: "amd64",
    )

    sampler._collect_sync()
    sampler._power_schedule.next_due = float("-inf")
    sampler._collect_sync()

    assert sampler._probe_health["power"].available is True
    assert sampler._hardware_values["power"]["source"] == "unavailable"


def test_stale_existing_amd64_power_cache_is_probe_failure(tmp_path: Path) -> None:
    cache = tmp_path / "power.json"
    cache.write_text(
        '{"schema_version":1,"generated_at":"2020-01-01T00:00:00Z",'
        '"value_w":5.0,"source":"rapl_package","domain":"package"}'
    )
    sampler = TelemetrySampler(
        Settings(power_cache_file=cache),
        paths=Paths(root=tmp_path),
        machine=lambda: "amd64",
    )

    sampler._collect_sync()
    sampler._power_schedule.next_due = float("-inf")
    sampler._collect_sync()

    assert sampler._probe_health["power"].available is False


def test_malformed_pmic_number_is_ignored() -> None:
    from monitor_suite_agent.telemetry import parse_pmic

    assert parse_pmic("EXT5V_V volt(0)=5..1V\nEXT5V_A current(0)=1.0A") == {
        "EXT5V": {"voltage_v": None, "current_a": 1.0, "power_w": None}
    }


def test_bond_interface_can_be_selected_explicitly_or_from_default_route(
    tmp_path: Path,
) -> None:
    from monitor_suite_agent.telemetry import select_network_interface

    net = tmp_path / "net"
    route = tmp_path / "route"
    for counter in ("rx_bytes", "tx_bytes"):
        path = net / "bond0/statistics" / counter
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("100")
    route.write_text(
        "Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"
        "bond0 00000000 00000000 0003 0 0 0 00000000 0 0 0\n"
    )

    assert select_network_interface(net, route) == "bond0"
    assert select_network_interface(net, route, "bond0") == "bond0"


def test_unlabelled_k10temp_uses_temp1_fallback(tmp_path: Path) -> None:
    from monitor_suite_agent.telemetry import read_cpu_temperature_c

    hwmon = tmp_path / "hwmon"
    monitor = hwmon / "hwmon0"
    monitor.mkdir(parents=True)
    (monitor / "name").write_text("k10temp")
    (monitor / "temp1_input").write_text("48750")

    assert read_cpu_temperature_c(tmp_path / "thermal", hwmon) == 48.8


def test_missing_source_discovery_uses_slow_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from monitor_suite_agent import telemetry

    calls = {"network": 0, "root": 0}

    def network(*args: object) -> None:
        calls["network"] += 1
        return None

    def root(*args: object) -> None:
        calls["root"] += 1
        return None

    monkeypatch.setattr(telemetry, "select_network_interface", network)
    monkeypatch.setattr(telemetry, "resolve_root_device", root)
    sampler = TelemetrySampler(
        Settings(slow_sample_interval_seconds=30.0),
        paths=Paths(root=tmp_path),
        machine=lambda: "amd64",
        monotonic=lambda: 10.0,
    )
    calls.update(network=0, root=0)

    sampler._collect_sync()
    sampler._collect_sync()

    assert calls == {"network": 1, "root": 1}


def test_smart_cache_read_uses_slow_schedule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from monitor_suite_agent import telemetry

    calls = 0

    def read_cache(*args: object) -> tuple[list[dict[str, object]], bool]:
        nonlocal calls
        calls += 1
        return [], True

    monkeypatch.setattr(telemetry, "read_smart_cache", read_cache)
    sampler = TelemetrySampler(
        Settings(slow_sample_interval_seconds=30.0),
        paths=Paths(root=tmp_path),
        machine=lambda: "amd64",
        monotonic=lambda: 10.0,
    )

    sampler._collect_sync()
    sampler._collect_sync()

    assert calls == 1


def test_network_auto_selection_excludes_tunnels_and_virtual_bridges(
    tmp_path: Path,
) -> None:
    from monitor_suite_agent.telemetry import select_network_interface

    net = tmp_path / "net"
    route = tmp_path / "route"
    route.write_text("Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n")
    for name in ("wg0", "tailscale0", "virbr0", "tun0", "tap0", "ztabc", "wlan0"):
        for counter in ("rx_bytes", "tx_bytes"):
            path = net / name / "statistics" / counter
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("100")
    (net / "wlan0/device").mkdir(parents=True)

    assert select_network_interface(net, route) == "wlan0"


def test_vpn_default_route_falls_back_to_underlying_physical_interface(
    tmp_path: Path,
) -> None:
    from monitor_suite_agent.telemetry import select_network_interface

    net = tmp_path / "net"
    route = tmp_path / "route"
    route.write_text(
        "Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"
        "wg0 00000000 00000000 0003 0 0 0 00000000 0 0 0\n"
    )
    for name in ("wg0", "eth0"):
        for counter in ("rx_bytes", "tx_bytes"):
            path = net / name / "statistics" / counter
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("100")
    (net / "eth0/device").mkdir(parents=True)

    assert select_network_interface(net, route) == "eth0"


def test_explicit_tunnel_interface_is_rejected(tmp_path: Path) -> None:
    from monitor_suite_agent.telemetry import select_network_interface

    net = tmp_path / "net"
    route = tmp_path / "route"
    for counter in ("rx_bytes", "tx_bytes"):
        path = net / "wg0/statistics" / counter
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("100")

    assert select_network_interface(net, route, "wg0") is None


def test_default_route_vlan_is_supported(tmp_path: Path) -> None:
    from monitor_suite_agent.telemetry import select_network_interface

    net = tmp_path / "net"
    route = tmp_path / "route"
    route.write_text(
        "Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"
        "eth0.20 00000000 00000000 0003 0 0 0 00000000 0 0 0\n"
    )
    for counter in ("rx_bytes", "tx_bytes"):
        path = net / "eth0.20/statistics" / counter
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("100")

    assert select_network_interface(net, route) == "eth0.20"
    assert select_network_interface(net, route, "eth0.20") == "eth0.20"


def test_additional_virtual_interface_prefixes_are_excluded(tmp_path: Path) -> None:
    from monitor_suite_agent.telemetry import select_network_interface

    net = tmp_path / "net"
    route = tmp_path / "route"
    route.write_text("Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n")
    for name in ("dummy0", "vnet0", "vxlan0", "wlan0"):
        for counter in ("rx_bytes", "tx_bytes"):
            path = net / name / "statistics" / counter
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("100")
    (net / "wlan0/device").mkdir(parents=True)

    assert select_network_interface(net, route) == "wlan0"


def test_physical_cellular_interface_is_supported(tmp_path: Path) -> None:
    from monitor_suite_agent.telemetry import select_network_interface

    net = tmp_path / "net"
    route = tmp_path / "route"
    route.write_text(
        "Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"
        "wwan0 00000000 00000000 0003 0 0 0 00000000 0 0 0\n"
    )
    (net / "wwan0/device").mkdir(parents=True)
    for counter in ("rx_bytes", "tx_bytes"):
        path = net / "wwan0/statistics" / counter
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("100")

    assert select_network_interface(net, route) == "wwan0"
    assert select_network_interface(net, route, "wwan0") == "wwan0"


def test_amd64_health_uses_thermal_limits_and_throttle_deltas(tmp_path: Path) -> None:
    from monitor_suite_agent.telemetry import read_amd64_health

    hwmon = tmp_path / "hwmon" / "hwmon0"
    hwmon.mkdir(parents=True)
    (hwmon / "name").write_text("coretemp\n")
    (hwmon / "temp1_input").write_text("85000\n")
    (hwmon / "temp1_max").write_text("90000\n")
    (hwmon / "temp1_crit").write_text("100000\n")
    (hwmon / "temp1_crit_alarm").write_text("0\n")
    throttle = tmp_path / "cpu" / "cpu0" / "thermal_throttle"
    throttle.mkdir(parents=True)
    (throttle / "package_throttle_count").write_text("7\n")

    health, counts = read_amd64_health(tmp_path / "hwmon", tmp_path / "cpu", None)
    assert health == {
        "status": "ok",
        "thermal_state": "normal",
        "performance_state": "normal",
    }
    (throttle / "package_throttle_count").write_text("8\n")
    health, _ = read_amd64_health(tmp_path / "hwmon", tmp_path / "cpu", counts)
    assert health["status"] == "warning"
    assert health["performance_state"] == "frequency_capped"


def test_amd64_health_reports_thermal_limit_and_critical_alarm(tmp_path: Path) -> None:
    from monitor_suite_agent.telemetry import read_amd64_health

    hwmon = tmp_path / "hwmon0"
    hwmon.mkdir()
    (hwmon / "name").write_text("k10temp\n")
    (hwmon / "temp1_input").write_text("91000\n")
    (hwmon / "temp1_max").write_text("90000\n")
    (hwmon / "temp1_crit").write_text("100000\n")
    (hwmon / "temp1_crit_alarm").write_text("0\n")
    health, _ = read_amd64_health(tmp_path, tmp_path / "cpu", None)
    assert health["status"] == "warning"
    assert health["thermal_state"] == "limited"
    (hwmon / "temp1_crit_alarm").write_text("1\n")
    health, _ = read_amd64_health(tmp_path, tmp_path / "cpu", None)
    assert health["status"] == "critical"
    assert health["thermal_state"] == "critical"


def test_amd64_health_is_unavailable_without_supported_signals(tmp_path: Path) -> None:
    from monitor_suite_agent.telemetry import read_amd64_health

    health, counts = read_amd64_health(tmp_path / "hwmon", tmp_path / "cpu", None)
    assert counts == {}
    assert health == {
        "status": "unavailable",
        "thermal_state": "unavailable",
        "performance_state": "unavailable",
    }
