"""Typed public API response models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeviceStatus(APIModel):
    model: str
    operating_system: str
    kernel_version: str
    architecture: str


class CPUStatus(APIModel):
    usage_percent: float | None
    frequency_mhz: float | None
    temperature_c: float | None


class UsageStatus(APIModel):
    used_percent: float | None
    available_bytes: int | None
    total_bytes: int | None


class PowerStatus(APIModel):
    value_w: float | None
    source: Literal["internal_rails", "cpu_estimate", "unavailable"]
    input_voltage_v: float | None


class CoolingStatus(APIModel):
    state: Literal["idle", "active", "unavailable"]
    fan_speed_rpm: int | None


class NetworkStatus(APIModel):
    interface: str | None
    status: Literal["up", "down", "unavailable"]
    link_speed_mbps: int | None
    download_bytes_per_second: int | None
    upload_bytes_per_second: int | None


class DiskActivityStatus(APIModel):
    read_bytes_per_second: int | None
    write_bytes_per_second: int | None


class SystemStatus(APIModel):
    booted_at: str | None


class RaspberryPiHealth(APIModel):
    status: Literal["ok", "warning", "critical", "unavailable"]
    power_supply: str
    thermal_state: str
    performance_state: str


class RaidArrayStatus(APIModel):
    name: str
    status: Literal[
        "healthy", "degraded", "failed", "recovering", "resyncing",
        "checking", "reshaping", "unavailable"
    ]
    raid_level: str
    active_members: int
    expected_members: int | None
    failed_members: int | None
    redundancy: Literal["none", "available", "reduced", "lost", "unknown"]
    smart_status: Literal["healthy", "warning", "failed", "testing", "unavailable"]
    progress_percent: float | None = None


class RaidStatus(APIModel):
    arrays: list[RaidArrayStatus]


class SmartDeviceStatus(APIModel):
    device: str
    status: Literal["healthy", "warning", "failed", "testing", "unavailable"]
    temperature_c: float | None
    remaining_life_percent: float | None = None


class SmartStatus(APIModel):
    devices: list[SmartDeviceStatus]


class StatusResponse(APIModel):
    updated_at: str
    device: DeviceStatus
    cpu: CPUStatus
    memory: UsageStatus
    root_filesystem: UsageStatus
    power: PowerStatus
    cooling: CoolingStatus
    network: NetworkStatus
    disk_activity: DiskActivityStatus
    system: SystemStatus
    raid: RaidStatus
    smart: SmartStatus
    health: RaspberryPiHealth


class HealthResponse(APIModel):
    status: Literal["starting", "ok", "degraded", "stale"]
    version: str
    sample_available: bool
