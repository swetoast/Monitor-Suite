"""Power profiles and calculations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PowerProfile:
    """Default model-specific estimation profile."""

    idle_w: float
    cpu_full_load_w: float


PROFILES: dict[str, PowerProfile] = {
    "Raspberry Pi 1 Model A": PowerProfile(0.5, 2.0),
    "Raspberry Pi 1 Model A+": PowerProfile(0.5, 2.0),
    "Raspberry Pi 1 Model B": PowerProfile(0.7, 2.5),
    "Raspberry Pi 1 Model B+": PowerProfile(0.7, 2.5),
    "Raspberry Pi 2 Model B": PowerProfile(1.15, 3.0),
    "Raspberry Pi 3 Model A Plus": PowerProfile(1.2, 3.8),
    "Raspberry Pi 3 Model B Plus": PowerProfile(1.15, 3.6),
    "Raspberry Pi 4 Model B": PowerProfile(3.0, 6.0),
    "Raspberry Pi 5 Model B": PowerProfile(2.7, 7.5),
    "Raspberry Pi Zero": PowerProfile(0.1, 1.2),
    "Raspberry Pi Zero W": PowerProfile(0.3, 1.3),
}


def profile_for_model(model: str) -> PowerProfile | None:
    """Find a profile while tolerating memory and revision suffixes."""
    for name in sorted(PROFILES, key=len, reverse=True):
        if model.startswith(name):
            return PROFILES[name]
    return None


def estimate_power_w(
    cpu_usage_percent: float,
    current_frequency_mhz: float | None,
    maximum_frequency_mhz: float | None,
    profile: PowerProfile,
) -> float:
    """Estimate board power from a calibrated CPU-load model.

    Frequency adjusts only part of the dynamic range, so full CPU load at the
    minimum clock can never collapse to idle power.
    """
    usage = min(100.0, max(0.0, cpu_usage_percent)) / 100.0
    frequency_ratio = 1.0
    if (
        current_frequency_mhz is not None
        and maximum_frequency_mhz is not None
        and maximum_frequency_mhz > 0
    ):
        frequency_ratio = min(
            1.0, max(0.0, current_frequency_mhz / maximum_frequency_mhz)
        )
    frequency_factor = 0.65 + (0.35 * frequency_ratio)
    dynamic_w = profile.cpu_full_load_w - profile.idle_w
    return round(profile.idle_w + dynamic_w * usage * frequency_factor, 3)


def select_profile(
    model: str,
    idle_override_w: float | None,
    full_load_override_w: float | None,
) -> PowerProfile | None:
    """Select a calibrated override pair or a model fallback profile."""
    if idle_override_w is not None and full_load_override_w is not None:
        return PowerProfile(idle_override_w, full_load_override_w)
    return profile_for_model(model)
