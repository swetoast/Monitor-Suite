"""Probe scheduling tests."""

from monitor_suite_agent.config import Settings
from monitor_suite_agent.telemetry import ProbeSchedule


def test_probe_schedule_runs_immediately_then_waits_for_deadline() -> None:
    schedule = ProbeSchedule()
    assert schedule.due(100.0)
    schedule.schedule(100.0, 30.0)
    assert not schedule.due(129.999)
    assert schedule.due(130.0)


def test_probe_intervals_match_cost_and_volatility() -> None:
    settings = Settings()
    assert settings.sample_interval_seconds == 1.0
    assert settings.thermal_sample_interval_seconds == 2.0
    assert settings.power_sample_interval_seconds == 5.0
    assert settings.raid_active_interval_seconds == 2.0
    assert settings.raid_idle_interval_seconds == 30.0
    assert settings.slow_sample_interval_seconds == 30.0


def test_all_scheduled_intervals_are_positive() -> None:
    settings = Settings()
    intervals = (
        settings.sample_interval_seconds,
        settings.thermal_sample_interval_seconds,
        settings.power_sample_interval_seconds,
        settings.raid_active_interval_seconds,
        settings.raid_idle_interval_seconds,
        settings.slow_sample_interval_seconds,
    )
    assert all(interval > 0 for interval in intervals)


def test_smartctl_health_exit_still_returns_json(monkeypatch) -> None:
    from subprocess import CompletedProcess
    from monitor_suite_agent.telemetry import run_smartctl

    monkeypatch.setattr(
        "monitor_suite_agent.telemetry.subprocess.run",
        lambda *args, **kwargs: CompletedProcess(args[0], 4, '{"smart_status":{"passed":true}}', ""),
    )
    assert run_smartctl(["smartctl", "-a", "-j", "/dev/sda"], 2.0) == '{"smart_status":{"passed":true}}'
