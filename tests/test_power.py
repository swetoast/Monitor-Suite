"""Power calculation tests."""

from monitor_suite_agent.power import PowerProfile, estimate_power_w, profile_for_model


def test_idle_load_returns_idle_power() -> None:
    assert estimate_power_w(0, 600, 1800, PowerProfile(3.0, 6.0)) == 3.0


def test_full_load_at_minimum_clock_exceeds_idle() -> None:
    result = estimate_power_w(100, 600, 1800, PowerProfile(3.0, 6.0))
    assert 3.0 < result < 6.0


def test_full_load_at_maximum_clock_reaches_profile_maximum() -> None:
    assert estimate_power_w(100, 1800, 1800, PowerProfile(3.0, 6.0)) == 6.0


def test_model_suffix_is_supported() -> None:
    assert profile_for_model("Raspberry Pi 4 Model B Rev 1.5") == PowerProfile(3.0, 6.0)
