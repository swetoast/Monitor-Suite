"""Architecture-hardening regression tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from monitor_suite_agent.config import Settings
from monitor_suite_agent.models import HealthResponse, StatusResponse
from monitor_suite_agent.telemetry import TelemetrySampler


def test_smart_retry_backoff_is_bounded() -> None:
    sampler = TelemetrySampler(Settings(smart_retry_interval_seconds=60, smart_sample_interval_seconds=900))
    expected = (900, 60, 120, 300, 900, 900)
    for failures, delay in enumerate(expected):
        sampler._smart_failures = failures
        assert sampler._smart_retry_delay() == delay


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
            assert sampler._smart_task is not None
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
