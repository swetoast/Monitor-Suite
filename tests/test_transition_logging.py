"""Regression tests for quiet, transition-only daemon logging."""

import logging

from monitor_suite_agent.config import Settings
from monitor_suite_agent.telemetry import TelemetrySampler


def messages(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records]


def test_probe_availability_logs_only_threshold_and_recovery(caplog) -> None:
    sampler = TelemetrySampler(Settings())
    with caplog.at_level(logging.WARNING, logger="monitor_suite_agent.telemetry"):
        sampler._record_probe("power", True, 1.0)
        sampler._record_probe("power", True, 2.0)
        sampler._record_probe("power", False, 3.0)
        sampler._record_probe("power", False, 4.0)
        sampler._record_probe("power", False, 5.0)
        sampler._record_probe("power", True, 6.0)
        sampler._record_probe("power", True, 7.0)

    assert messages(caplog) == [
        "Power data became unavailable",
        "Power data recovered",
    ]


def test_cooling_availability_logs_only_transition(caplog) -> None:
    sampler = TelemetrySampler(Settings())
    with caplog.at_level(logging.WARNING, logger="monitor_suite_agent.telemetry"):
        sampler._record_probe("cooling", True, 1.0)
        sampler._record_probe("cooling", False, 2.0)
        sampler._record_probe("cooling", False, 3.0)
        sampler._record_probe("cooling", False, 4.0)
        sampler._record_probe("cooling", True, 5.0)

    assert messages(caplog) == [
        "Cooling data became unavailable",
        "Cooling data recovered",
    ]


def test_raid_logs_degradation_recovery_and_completion_once(caplog) -> None:
    sampler = TelemetrySampler(Settings())
    with caplog.at_level(logging.WARNING, logger="monitor_suite_agent.telemetry"):
        sampler._log_raid_transitions([{"name": "md0", "status": "healthy"}])
        sampler._log_raid_transitions([{"name": "md0", "status": "healthy"}])
        sampler._log_raid_transitions([{"name": "md0", "status": "degraded"}])
        sampler._log_raid_transitions([{"name": "md0", "status": "recovering"}])
        sampler._log_raid_transitions([{"name": "md0", "status": "recovering"}])
        sampler._log_raid_transitions([{"name": "md0", "status": "healthy"}])
        sampler._log_raid_transitions([{"name": "md0", "status": "failed"}])

    assert messages(caplog) == [
        "RAID md0 changed from healthy to degraded",
        "RAID md0 changed from degraded to recovering",
        "RAID md0 changed from recovering to healthy",
        "RAID md0 changed from healthy to failed",
    ]


def test_raid_disappearance_and_return_log_once(caplog) -> None:
    sampler = TelemetrySampler(Settings())
    with caplog.at_level(logging.WARNING, logger="monitor_suite_agent.telemetry"):
        sampler._log_raid_transitions([{"name": "md0", "status": "healthy"}])
        sampler._log_raid_transitions([])
        sampler._log_raid_transitions([])
        sampler._log_raid_transitions([{"name": "md0", "status": "healthy"}])

    assert messages(caplog) == [
        "RAID md0 changed from healthy to unavailable",
        "RAID md0 changed from unavailable to healthy",
    ]


def test_firmware_conditions_log_only_current_state_changes(caplog) -> None:
    sampler = TelemetrySampler(Settings())
    with caplog.at_level(logging.WARNING, logger="monitor_suite_agent.telemetry"):
        sampler._log_state_transition("Current undervoltage", "ok")
        sampler._log_state_transition("Current undervoltage", "ok")
        sampler._log_state_transition("Current undervoltage", "under_voltage")
        sampler._log_state_transition("Current undervoltage", "under_voltage")
        sampler._log_state_transition("Current undervoltage", "ok")
        sampler._log_state_transition("Thermal limiting", "normal")
        sampler._log_state_transition("Thermal limiting", "limited")
        sampler._log_state_transition("Thermal limiting", "limited")
        sampler._log_state_transition("Thermal limiting", "normal")

    assert messages(caplog) == [
        "Current undervoltage changed from ok to under_voltage",
        "Current undervoltage changed from under_voltage to ok",
        "Thermal limiting changed from normal to limited",
        "Thermal limiting changed from limited to normal",
    ]


def test_selected_sources_log_only_real_changes(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="monitor_suite_agent.telemetry"):
        TelemetrySampler._log_selection_transition("Network interface", "eth0", "eth0")
        TelemetrySampler._log_selection_transition("Network interface", "eth0", "wlan0")
        TelemetrySampler._log_selection_transition("Root backing device", "sda", "sda")
        TelemetrySampler._log_selection_transition("Root backing device", "sda", "nvme0n1")
        TelemetrySampler._log_selection_transition(
            "Cooling hardware", (None, None), (None, None)
        )
        TelemetrySampler._log_selection_transition(
            "Cooling hardware", (None, None), ("cooling0", "fan1_input")
        )

    assert messages(caplog) == [
        "Network interface changed from eth0 to wlan0",
        "Root backing device changed from sda to nvme0n1",
        "Cooling hardware changed from (None, None) to ('cooling0', 'fan1_input')",
    ]


def test_all_probe_groups_use_one_transition_message(caplog) -> None:
    expected = {
        "snapshot": "Snapshot collection",
        "fast": "Fast telemetry",
        "thermal": "Thermal data",
        "cooling": "Cooling data",
        "power": "Power data",
        "resources": "Resource data",
        "raid": "RAID data",
        "smart": "SMART data",
    }
    sampler = TelemetrySampler(Settings())
    with caplog.at_level(logging.WARNING, logger="monitor_suite_agent.telemetry"):
        for group in expected:
            sampler._record_probe(group, True, 1.0)
            sampler._record_probe(group, False, 2.0)
            sampler._record_probe(group, False, 3.0)
            sampler._record_probe(group, False, 4.0)
            sampler._record_probe(group, True, 5.0)

    assert messages(caplog) == [
        message
        for label in expected.values()
        for message in (f"{label} became unavailable", f"{label} recovered")
    ]


def test_initial_state_and_unchanged_cycles_are_quiet(caplog) -> None:
    sampler = TelemetrySampler(Settings())
    with caplog.at_level(logging.WARNING, logger="monitor_suite_agent.telemetry"):
        for _ in range(5):
            sampler._log_state_transition("Current undervoltage", "ok")
            sampler._log_state_transition("Thermal limiting", "normal")
            sampler._log_state_transition("Performance limiting", "normal")
            sampler._log_raid_transitions([{"name": "md0", "status": "healthy"}])
            TelemetrySampler._log_selection_transition("Network interface", "eth0", "eth0")
            TelemetrySampler._log_selection_transition("Root backing device", "sda", "sda")

    assert messages(caplog) == []
