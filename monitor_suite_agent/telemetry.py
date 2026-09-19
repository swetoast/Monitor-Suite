"""Read, calculate, and cache Raspberry Pi status telemetry."""

from __future__ import annotations

import asyncio
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import platform
import re
import subprocess
import time
from typing import Any, Callable, Mapping

from .config import Settings
from .power import PowerProfile, estimate_power_w, select_profile

_LOGGER = logging.getLogger(__name__)
_PM_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s+(current|volt)\(\d+\)=([0-9.]+)([AV])\s*$")
_THROTTLED_RE = re.compile(r"throttled=0x([0-9a-fA-F]+)")


@dataclass(frozen=True, slots=True)
class Paths:
    """Linux interfaces used by the collector."""

    root: Path = Path("/")
    proc_stat: Path = Path("/proc/stat")
    proc_meminfo: Path = Path("/proc/meminfo")
    proc_uptime: Path = Path("/proc/uptime")
    proc_mountinfo: Path = Path("/proc/self/mountinfo")
    proc_diskstats: Path = Path("/proc/diskstats")
    proc_net_route: Path = Path("/proc/net/route")
    device_model: Path = Path("/proc/device-tree/model")
    os_release: Path = Path("/etc/os-release")
    cpu_root: Path = Path("/sys/devices/system/cpu")
    thermal_root: Path = Path("/sys/class/thermal")
    hwmon_root: Path = Path("/sys/class/hwmon")
    net_root: Path = Path("/sys/class/net")
    block_root: Path = Path("/sys/class/block")


@dataclass(frozen=True, slots=True)
class CpuTimes:
    """Aggregate Linux CPU counters."""

    total: int
    idle: int


@dataclass(frozen=True, slots=True)
class RateCounter:
    """Monotonic counter pair and collection time."""

    first: int
    second: int
    monotonic: float


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip("\x00\n ")
    except OSError:
        return None


def run_command(arguments: list[str], timeout: float) -> str | None:
    """Run one read-only command safely."""
    try:
        result = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def run_smartctl(arguments: list[str], timeout: float) -> str | None:
    """Run smartctl and preserve JSON even when health bits set a nonzero exit status."""
    try:
        result = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = result.stdout.strip()
    return output or None


def _smart_device_in_standby(text: str | None) -> bool:
    if not text:
        return False
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return False
    messages = data.get("smartctl", {}).get("messages", [])
    return any("standby" in str(item.get("string", "")).lower() for item in messages)


def read_model(path: Path) -> str:
    """Read the hardware model without exposing the board serial."""
    return _read_text(path) or "Unknown Raspberry Pi"


def parse_os_release(text: str | None) -> str:
    """Return PRETTY_NAME from os-release."""
    if not text:
        return "Unknown Linux"
    for line in text.splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.partition("=")[2].strip().strip('"')
    return "Unknown Linux"


def parse_cpu_times(text: str | None) -> CpuTimes | None:
    """Parse the aggregate CPU line from /proc/stat."""
    if not text:
        return None
    line = next((line for line in text.splitlines() if line.startswith("cpu ")), None)
    if line is None:
        return None
    try:
        values = [int(value) for value in line.split()[1:]]
    except ValueError:
        return None
    if len(values) < 4:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return CpuTimes(total=sum(values), idle=idle)


def calculate_cpu_usage(previous: CpuTimes | None, current: CpuTimes | None) -> float | None:
    """Calculate aggregate CPU use from two kernel counter samples."""
    if previous is None or current is None:
        return None
    total_delta = current.total - previous.total
    idle_delta = current.idle - previous.idle
    if total_delta <= 0 or idle_delta < 0:
        return None
    return max(0.0, min(100.0, 100.0 * (total_delta - idle_delta) / total_delta))


def read_frequency_mhz(cpu_root: Path) -> float | None:
    """Read CPU0 frequency from the standard cpufreq interfaces."""
    base = cpu_root / "cpu0" / "cpufreq"
    for name in ("scaling_cur_freq", "cpuinfo_cur_freq"):
        raw = _read_text(base / name)
        if raw:
            try:
                return round(float(raw) / 1000.0, 1)
            except ValueError:
                pass
    return None


def read_max_frequency_mhz(cpu_root: Path) -> float | None:
    """Read the maximum CPU frequency for fallback estimation."""
    base = cpu_root / "cpu0" / "cpufreq"
    for name in ("scaling_max_freq", "cpuinfo_max_freq"):
        raw = _read_text(base / name)
        if raw:
            try:
                return float(raw) / 1000.0
            except ValueError:
                pass
    return None


def read_cpu_temperature_c(thermal_root: Path, hwmon_root: Path) -> float | None:
    """Read CPU temperature by semantic thermal or hwmon identity."""
    for zone in sorted(thermal_root.glob("thermal_zone*")):
        if (_read_text(zone / "type") or "").lower() in {"cpu-thermal", "cpu_thermal"}:
            return _millivalue(_read_text(zone / "temp"))
    for monitor in sorted(hwmon_root.glob("hwmon*")):
        if (_read_text(monitor / "name") or "").lower() in {"cpu_thermal", "cpu-thermal"}:
            return _millivalue(_read_text(monitor / "temp1_input"))
    return None


def _millivalue(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        return round(float(raw) / 1000.0, 1)
    except ValueError:
        return None


def parse_meminfo(text: str | None) -> dict[str, int]:
    """Parse selected /proc/meminfo values into bytes."""
    values: dict[str, int] = {}
    if not text:
        return values
    for line in text.splitlines():
        key, separator, remainder = line.partition(":")
        if not separator or key not in {"MemTotal", "MemAvailable"}:
            continue
        fields = remainder.split()
        try:
            amount = int(fields[0])
        except (IndexError, ValueError):
            continue
        multiplier = 1024 if len(fields) > 1 and fields[1].lower() == "kb" else 1
        values[key] = amount * multiplier
    return values


def memory_status(text: str | None) -> dict[str, int | float | None]:
    """Build meaningful memory status from MemTotal and MemAvailable."""
    values = parse_meminfo(text)
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    used_percent = None
    if total and available is not None and 0 <= available <= total:
        used_percent = round(100.0 * (total - available) / total, 1)
    return {"used_percent": used_percent, "available_bytes": available, "total_bytes": total}


def filesystem_status(root: Path) -> dict[str, int | float | None]:
    """Return capacity of the root filesystem."""
    try:
        stats = os.statvfs(root)
    except OSError:
        return {"used_percent": None, "available_bytes": None, "total_bytes": None}
    total = stats.f_blocks * stats.f_frsize
    available = stats.f_bavail * stats.f_frsize
    used = (stats.f_blocks - stats.f_bfree) * stats.f_frsize
    used_percent = round(100.0 * used / total, 1) if total else None
    return {"used_percent": used_percent, "available_bytes": available, "total_bytes": total}


def parse_uptime_seconds(text: str | None) -> float | None:
    """Parse system uptime seconds."""
    try:
        return float(text.split()[0]) if text else None
    except (ValueError, IndexError):
        return None


def booted_at(uptime_seconds: float | None, now: datetime | None = None) -> str | None:
    """Convert monotonic uptime to an ISO 8601 UTC boot timestamp."""
    if uptime_seconds is None or uptime_seconds < 0:
        return None
    current = now or datetime.now(timezone.utc)
    return (current - timedelta(seconds=uptime_seconds)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_pmic(text: str | None) -> dict[str, dict[str, float | None]]:
    """Parse and pair Raspberry Pi PMIC voltage/current channels."""
    rails: dict[str, dict[str, float | None]] = {}
    if not text:
        return rails
    for line in text.splitlines():
        match = _PM_RE.match(line)
        if not match:
            continue
        label, kind, raw_value, _unit = match.groups()
        suffix = "_A" if kind == "current" else "_V"
        if not label.endswith(suffix):
            continue
        rail = label[: -len(suffix)]
        entry = rails.setdefault(rail, {"voltage_v": None, "current_a": None, "power_w": None})
        entry["current_a" if kind == "current" else "voltage_v"] = float(raw_value)
    for entry in rails.values():
        voltage = entry["voltage_v"]
        current = entry["current_a"]
        if voltage is not None and current is not None:
            entry["power_w"] = round(voltage * current, 6)
    return rails


def parse_throttling(text: str | None) -> dict[str, bool | int] | None:
    """Decode current and historical Raspberry Pi throttling bits."""
    match = _THROTTLED_RE.search(text or "")
    if not match:
        return None
    value = int(match.group(1), 16)
    return {
        "raw": value,
        "under_voltage_now": bool(value & (1 << 0)),
        "frequency_capped_now": bool(value & (1 << 1)),
        "throttled_now": bool(value & (1 << 2)),
        "soft_temperature_limit_now": bool(value & (1 << 3)),
        "under_voltage_occurred": bool(value & (1 << 16)),
        "frequency_capped_occurred": bool(value & (1 << 17)),
        "throttled_occurred": bool(value & (1 << 18)),
        "soft_temperature_limit_occurred": bool(value & (1 << 19)),
    }


def build_health(flags: Mapping[str, bool | int] | None) -> dict[str, str]:
    """Expose only current authoritative firmware-health conditions."""
    if flags is None:
        return {"status": "unknown", "power_supply": "unknown", "thermal_state": "unknown", "performance_state": "unknown"}
    under_voltage = bool(flags["under_voltage_now"])
    thermal = bool(flags["soft_temperature_limit_now"])
    throttled = bool(flags["throttled_now"])
    capped = bool(flags["frequency_capped_now"])
    return {
        "status": "problem" if any((under_voltage, thermal, throttled, capped)) else "ok",
        "power_supply": "under_voltage" if under_voltage else "ok",
        "thermal_state": "limited" if thermal else "normal",
        "performance_state": "throttled" if throttled else "frequency_capped" if capped else "normal",
    }


def select_network_interface(net_root: Path, route_path: Path, preferred: str | None = None) -> str | None:
    """Select the default-route physical interface and ignore virtual links."""
    if preferred is not None:
        path = net_root / preferred
        if path.exists() and (path / "device").exists():
            return preferred
        return None

    default: str | None = None
    route = _read_text(route_path)
    if route:
        for line in route.splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 4 and fields[1] == "00000000":
                try:
                    if int(fields[3], 16) & 0x1:
                        default = fields[0]
                        break
                except ValueError:
                    pass
    candidates = [default] if default else []
    candidates.extend(path.name for path in sorted(net_root.iterdir()) if path.name != default) if net_root.exists() else None
    for name in candidates:
        if not name or name == "lo" or name.startswith(("docker", "br-", "veth")):
            continue
        path = net_root / name
        if not path.exists():
            continue
        device = path / "device"
        if device.exists() or name.startswith(("eth", "en", "wlan", "wl")):
            return name
    return None


def read_network_counter(net_root: Path, interface: str | None, monotonic: float) -> RateCounter | None:
    """Read receive and transmit byte counters."""
    if not interface:
        return None
    stats = net_root / interface / "statistics"
    try:
        return RateCounter(int((stats / "rx_bytes").read_text()), int((stats / "tx_bytes").read_text()), monotonic)
    except (OSError, ValueError):
        return None


def calculate_rates(previous: RateCounter | None, current: RateCounter | None) -> tuple[int | None, int | None]:
    """Calculate two byte rates while handling resets."""
    if previous is None or current is None:
        return None, None
    elapsed = current.monotonic - previous.monotonic
    first_delta = current.first - previous.first
    second_delta = current.second - previous.second
    if elapsed <= 0 or first_delta < 0 or second_delta < 0:
        return None, None
    return round(first_delta / elapsed), round(second_delta / elapsed)


def read_network_metadata(net_root: Path, interface: str | None) -> dict[str, str | int | None]:
    """Read link state and negotiated speed."""
    if not interface:
        return {"interface": None, "status": "unknown", "link_speed_mbps": None}
    base = net_root / interface
    state = _read_text(base / "operstate")
    if state not in {"up", "down"}:
        state = "unknown"
    speed: int | None = None
    raw_speed = _read_text(base / "speed")
    try:
        parsed = int(raw_speed) if raw_speed is not None else -1
        speed = parsed if parsed >= 0 else None
    except ValueError:
        pass
    return {"interface": interface, "status": state, "link_speed_mbps": speed}


def resolve_root_device(mountinfo: str | None, block_root: Path) -> str | None:
    """Resolve the whole block device backing the root filesystem."""
    if not mountinfo:
        return None
    source: str | None = None
    for line in mountinfo.splitlines():
        fields = line.split()
        if len(fields) < 10 or fields[4] != "/" or "-" not in fields:
            continue
        separator = fields.index("-")
        if len(fields) > separator + 2:
            source = fields[separator + 2]
            break
    if not source or not source.startswith("/dev/"):
        return None
    name = Path(source).name
    partition = block_root / name
    if (partition / "partition").exists():
        match = re.match(r"^(nvme\d+n\d+)p\d+$|^(mmcblk\d+)p\d+$|^([a-z]+)\d+$", name)
        if match:
            return next(group for group in match.groups() if group)
        try:
            parent_name = partition.resolve().parent.name
            if parent_name and (block_root / parent_name).exists():
                return parent_name
        except OSError:
            pass
    return name


def parse_diskstats(text: str | None, device: str | None, monotonic: float) -> RateCounter | None:
    """Read sector counters for one physical block device."""
    if not text or not device:
        return None
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 10 and fields[2] == device:
            try:
                return RateCounter(int(fields[5]) * 512, int(fields[9]) * 512, monotonic)
            except ValueError:
                return None
    return None


def discover_cooling(thermal_root: Path, hwmon_root: Path) -> tuple[Path | None, Path | None]:
    """Find a PWM cooling device and associated fan RPM input."""
    cooling = next((path for path in sorted(thermal_root.glob("cooling_device*")) if (_read_text(path / "type") or "").lower() == "pwm-fan"), None)
    fan = next((path / "fan1_input" for path in sorted(hwmon_root.glob("hwmon*")) if (_read_text(path / "name") or "").lower() in {"pwmfan", "pwm-fan"} and (path / "fan1_input").exists()), None)
    return cooling, fan


def read_cooling(cooling_path: Path | None, fan_path: Path | None) -> dict[str, str | int | None]:
    """Return meaningful cooling state and RPM."""
    if cooling_path is None:
        return {"state": "unavailable", "fan_speed_rpm": None}
    try:
        level = int((cooling_path / "cur_state").read_text())
    except (OSError, ValueError):
        return {"state": "unavailable", "fan_speed_rpm": None}
    rpm: int | None = None
    if fan_path is not None:
        try:
            rpm = int(fan_path.read_text())
        except (OSError, ValueError):
            pass
    return {"state": "active" if level > 0 else "idle", "fan_speed_rpm": rpm}


def _read_int(path: Path) -> int | None:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _raid_redundancy(level: str, status: str, failed_members: int | None) -> str:
    if level in {"raid0", "linear"}:
        return "none"
    if status == "failed":
        return "lost"
    if failed_members:
        return "reduced"
    if level in {"raid1", "raid4", "raid5", "raid6", "raid10"}:
        return "available"
    return "unknown"


def read_raid_arrays(block_root: Path) -> list[dict[str, Any]]:
    """Read compact Linux MD array health from sysfs."""
    arrays: list[dict[str, Any]] = []
    if not block_root.exists():
        return arrays
    for device in sorted(block_root.glob("md*"), key=lambda item: item.name):
        md = device / "md"
        if not md.is_dir():
            continue
        level = _read_text(md / "level") or "unknown"
        array_state = _read_text(md / "array_state") or "unavailable"
        expected = _read_int(md / "raid_disks")
        failed = _read_int(md / "degraded")
        members = list(md.glob("dev-*"))
        if expected is not None and failed is not None:
            active = max(0, expected - failed)
        else:
            active = sum(
                1
                for member in members
                if not {"faulty", "remove", "removed"}.intersection(
                    (_read_text(member / "state") or "").split(",")
                )
            )
        action = _read_text(md / "sync_action") or "idle"
        missing = bool(failed) or (expected is not None and active < expected)
        if array_state in {"inactive", "clear", "broken"} or (level == "raid0" and missing):
            state = "failed"
        elif action in {"recover", "recovery"}:
            state = "recovering"
        elif action == "resync":
            state = "resyncing"
        elif action in {"check", "repair"}:
            state = "checking"
        elif action == "reshape":
            state = "reshaping"
        elif missing:
            state = "degraded"
        elif array_state in {"active", "active-idle", "clean", "read-auto", "readonly"}:
            state = "healthy"
        else:
            state = "unavailable"
        result: dict[str, Any] = {
            "name": device.name,
            "status": state,
            "raid_level": level.upper(),
            "active_members": active,
            "expected_members": expected,
            "failed_members": failed,
            "redundancy": _raid_redundancy(level, state, failed),
        }
        completed = _read_text(md / "sync_completed")
        if state in {"recovering", "resyncing", "checking", "reshaping"} and completed and "/" in completed:
            try:
                done, total = (int(value.strip()) for value in completed.split("/", 1))
                if total > 0:
                    result["progress_percent"] = round(done * 100 / total, 1)
            except ValueError:
                pass
        arrays.append(result)
    return arrays


def _smart_attributes(data: Mapping[str, Any]) -> dict[int, int]:
    table = data.get("ata_smart_attributes", {}).get("table", [])
    values: dict[int, int] = {}
    for item in table if isinstance(table, list) else []:
        try:
            values[int(item["id"])] = int(item.get("raw", {}).get("value", 0))
        except (KeyError, TypeError, ValueError):
            continue
    return values


def parse_smart_json(text: str | None, device: str) -> dict[str, Any] | None:
    """Reduce smartctl JSON to the approved high-value SMART fields."""
    if not text:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not data.get("smart_support", {}).get("available", False):
        return None
    passed = data.get("smart_status", {}).get("passed")
    ata_test = data.get("ata_smart_data", {}).get("self_test", {}).get("status", {})
    ata_test_text = str(ata_test.get("string", "")).lower()
    nvme_test = data.get("nvme_self_test_log", {}).get("current_self_test_operation", {}).get("value")
    testing = "in progress" in ata_test_text or nvme_test not in {None, 0}
    attrs = _smart_attributes(data)
    nvme = data.get("nvme_smart_health_information_log", {})
    critical = int(nvme.get("critical_warning", 0) or 0)
    media_errors = int(nvme.get("media_errors", 0) or 0)
    failed_attribute = any(
        bool(item.get("when_failed"))
        for item in data.get("ata_smart_attributes", {}).get("table", [])
    )
    ata_warning = any(attrs.get(identifier, 0) > 0 for identifier in (5, 197, 198))
    if passed is False or failed_attribute or critical:
        status = "failed"
    elif testing:
        status = "testing"
    elif ata_warning or media_errors:
        status = "warning"
    else:
        status = "healthy"
    result: dict[str, Any] = {
        "device": device,
        "status": status,
        "temperature_c": data.get("temperature", {}).get("current"),
    }
    used = nvme.get("percentage_used")
    if isinstance(used, (int, float)):
        result["remaining_life_percent"] = max(0, min(100, round(100 - float(used), 1)))
    return result


def discover_physical_disks(block_root: Path) -> list[str]:
    """Return physical whole-disk names without partitions or virtual devices."""
    if not block_root.exists():
        return []
    return [
        path.name
        for path in sorted(block_root.iterdir(), key=lambda item: item.name)
        if not path.name.startswith(("loop", "ram", "zram", "dm-", "md"))
        and not (path / "partition").exists()
        and (path / "device").exists()
    ]


def parse_smartctl_scan(text: str | None) -> list[tuple[str, str | None]]:
    """Parse smartctl scan output into endpoint and optional device-type pairs."""
    devices: list[tuple[str, str | None]] = []
    for raw_line in (text or "").splitlines():
        fields = raw_line.partition("#")[0].split()
        if not fields or not fields[0].startswith("/dev/"):
            continue
        device_type: str | None = None
        if "-d" in fields:
            index = fields.index("-d")
            if index + 1 < len(fields):
                device_type = fields[index + 1]
        devices.append((fields[0], device_type))
    return devices


def _public_smart_device(endpoint: str, block_root: Path) -> str:
    """Map a SMART controller endpoint to its public whole-disk block name."""
    name = Path(endpoint).name
    if not name.startswith("nvme") or "n" in name.removeprefix("nvme"):
        return name
    namespaces = [
        path.name
        for path in sorted(block_root.glob(f"{name}n*"), key=lambda item: item.name)
        if not (path / "partition").exists()
    ]
    return namespaces[0] if len(namespaces) == 1 else name


def discover_smart_devices(
    block_root: Path,
    command_runner: Callable[[list[str], float], str | None],
    timeout: float,
) -> list[tuple[str, str | None, str]]:
    """Discover valid SMART endpoints and map them to public block-device names."""
    scan = parse_smartctl_scan(command_runner(["smartctl", "--scan-open"], timeout))
    if scan:
        return [
            (endpoint, device_type, _public_smart_device(endpoint, block_root))
            for endpoint, device_type in scan
        ]
    return [(f"/dev/{name}", None, name) for name in discover_physical_disks(block_root)]


def read_smart_devices(
    block_root: Path,
    command_runner: Callable[[list[str], float], str | None],
    timeout: float,
    previous: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Read approved SMART values from discovered endpoints without waking disks."""
    prior = {item["device"]: item for item in previous or []}
    devices: list[dict[str, Any]] = []
    for endpoint, device_type, public_name in discover_smart_devices(
        block_root, command_runner, timeout
    ):
        arguments = ["smartctl", "-n", "standby", "-a", "-j"]
        if device_type is not None:
            arguments.extend(["-d", device_type])
        arguments.append(endpoint)
        text = command_runner(arguments, timeout)
        result = parse_smart_json(text, public_name)
        if result is not None:
            devices.append(result)
        elif public_name in prior and _smart_device_in_standby(text):
            devices.append(prior[public_name])
        else:
            devices.append(
                {"device": public_name, "status": "unavailable", "temperature_c": None}
            )
    return devices


@dataclass(slots=True)
class ProbeHealth:
    """Internal availability state for one probe group."""

    available: bool | None = None
    consecutive_failures: int = 0
    last_success_monotonic: float | None = None

    def update(self, success: bool, now: float) -> tuple[bool | None, bool]:
        previous = self.available
        if success:
            self.available = True
            self.consecutive_failures = 0
            self.last_success_monotonic = now
        else:
            self.consecutive_failures += 1
            if self.consecutive_failures >= 2:
                self.available = False
        return previous, self.available != previous and previous is not None


@dataclass(slots=True)
class ProbeSchedule:
    """Monotonic deadline for one probe group."""

    next_due: float = float("-inf")

    def due(self, now: float) -> bool:
        return now >= self.next_due

    def schedule(self, now: float, interval: float) -> None:
        self.next_due = now + interval


class TelemetrySampler:
    """Collect hardware status in one lifecycle-managed background task."""

    def __init__(
        self,
        settings: Settings,
        paths: Paths | None = None,
        command_runner: Callable[[list[str], float], str | None] = run_command,
        smart_runner: Callable[[list[str], float], str | None] = run_smartctl,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.settings = settings
        self.paths = paths or Paths()
        self._run_command = command_runner
        self._run_smart = smart_runner
        self._monotonic = monotonic
        self._now = now
        self._task: asyncio.Task[None] | None = None
        self._smart_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._snapshot: dict[str, Any] | None = None
        self._last_success_monotonic: float | None = None
        self._previous_cpu: CpuTimes | None = None
        self._cpu_samples: deque[float] = deque(maxlen=10)
        self._previous_network: RateCounter | None = None
        self._previous_disk: RateCounter | None = None
        self._slow_values: dict[str, Any] = {}
        self._hardware_values: dict[str, Any] = {}
        self._raid_values: list[dict[str, Any]] = []
        self._smart_values: list[dict[str, Any]] = []
        self._thermal_schedule = ProbeSchedule()
        self._power_schedule = ProbeSchedule()
        self._resource_schedule = ProbeSchedule()
        self._raid_schedule = ProbeSchedule()
        self._smart_schedule = ProbeSchedule()
        self._smart_failures = 0
        self._probe_health = {
            name: ProbeHealth()
            for name in ("snapshot", "fast", "thermal", "cooling", "power", "resources", "raid", "smart")
        }
        self._state_log: dict[str, str] = {}
        self._raid_state_log: dict[str, str] = {}
        self.model = read_model(self.paths.device_model)
        self.profile: PowerProfile | None = select_profile(
            self.model,
            settings.idle_power_override_w,
            settings.full_load_power_override_w,
        )
        self.interface = select_network_interface(
            self.paths.net_root, self.paths.proc_net_route, self.settings.network_interface
        )
        self.max_frequency_mhz = read_max_frequency_mhz(self.paths.cpu_root)
        self.root_device = resolve_root_device(_read_text(self.paths.proc_mountinfo), self.paths.block_root)
        self.cooling_path, self.fan_path = discover_cooling(self.paths.thermal_root, self.paths.hwmon_root)
        self.device = {
            "model": self.model,
            "operating_system": parse_os_release(_read_text(self.paths.os_release)),
            "kernel_version": platform.release(),
            "architecture": platform.machine(),
        }

    def _record_probe(self, name: str, success: bool, now: float) -> None:
        """Update one probe group and log only unavailable/recovery transitions."""
        previous, changed = self._probe_health[name].update(success, now)
        if not changed:
            return
        label = {
            "snapshot": "Snapshot collection",
            "fast": "Fast telemetry",
            "thermal": "Thermal data",
            "cooling": "Cooling data",
            "power": "Power data",
            "resources": "Resource data",
            "raid": "RAID data",
            "smart": "SMART data",
        }[name]
        current = self._probe_health[name].available
        _LOGGER.warning("%s %s", label, "recovered" if current else "became unavailable")

    def _log_state_transition(self, name: str, state: str) -> None:
        """Record a baseline silently and log only later state changes."""
        previous = self._state_log.get(name)
        if previous is not None and previous != state:
            _LOGGER.warning("%s changed from %s to %s", name, previous, state)
        self._state_log[name] = state

    @staticmethod
    def _log_selection_transition(
        label: str, previous: object | None, current: object | None
    ) -> None:
        """Log a selected source only when its effective value changes."""
        if previous == current:
            return
        _LOGGER.warning(
            "%s changed from %s to %s",
            label,
            previous if previous is not None else "unavailable",
            current if current is not None else "unavailable",
        )

    def _log_raid_transitions(self, arrays: list[dict[str, Any]]) -> None:
        """Log RAID state changes, including disappearance and return."""
        observed = {array["name"]: array["status"] for array in arrays}
        current = dict(self._raid_state_log)
        for name, state in observed.items():
            previous = self._raid_state_log.get(name)
            if previous is not None and previous != state:
                _LOGGER.warning("RAID %s changed from %s to %s", name, previous, state)
            current[name] = state
        for name, previous in self._raid_state_log.items():
            if name not in observed and previous != "unavailable":
                _LOGGER.warning("RAID %s changed from %s to unavailable", name, previous)
                current[name] = "unavailable"
        self._raid_state_log = current

    async def start(self) -> None:
        """Start the daemon even if the first lightweight sample fails."""
        if self._task and not self._task.done():
            return
        self._stop.clear()
        try:
            await self.collect_once()
        except Exception:
            _LOGGER.exception("Initial telemetry collection failed; daemon remains in starting state")
        self._task = asyncio.create_task(self._run(), name="monitor-suite-sampler")
        self._smart_task = asyncio.create_task(self._run_smart_loop(), name="monitor-suite-smart")

    async def stop(self) -> None:
        """Stop the sampler cleanly."""
        self._stop.set()
        for task in (self._task, self._smart_task):
            if task:
                task.cancel()
        for task in (self._task, self._smart_task):
            if task:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._task = None
        self._smart_task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            started = self._monotonic()
            try:
                await self.collect_once()
            except Exception:
                if self._probe_health["snapshot"].consecutive_failures == 1:
                    _LOGGER.exception("Telemetry collection failed")
            delay = max(0.0, self.settings.sample_interval_seconds - (self._monotonic() - started))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def _run_smart_loop(self) -> None:
        """Collect SMART independently so slow disks never block fast telemetry."""
        while not self._stop.is_set():
            try:
                values = await asyncio.to_thread(
                    read_smart_devices,
                    self.paths.block_root,
                    self._run_smart,
                    self.settings.command_timeout_seconds,
                    self._smart_values,
                )
                self._smart_values = values
                unavailable = any(item["status"] == "unavailable" for item in values)
                available = not unavailable
                self._smart_failures = self._smart_failures + 1 if unavailable else 0
                self._record_probe("smart", available, self._monotonic())
            except Exception:
                self._smart_failures += 1
                self._record_probe("smart", False, self._monotonic())
                if self._probe_health["smart"].consecutive_failures == 1:
                    _LOGGER.exception("SMART collection failed")
            delay = self._smart_retry_delay()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    def _smart_retry_delay(self) -> float:
        """Return bounded retry backoff or the normal SMART interval."""
        if self._smart_failures <= 0:
            return self.settings.smart_sample_interval_seconds
        steps = (1.0, 2.0, 5.0, 15.0)
        multiplier = steps[min(self._smart_failures - 1, len(steps) - 1)]
        return min(
            self.settings.smart_sample_interval_seconds,
            self.settings.smart_retry_interval_seconds * multiplier,
        )

    async def collect_once(self) -> dict[str, Any]:
        """Collect one snapshot and account for whole-cycle success or failure."""
        try:
            snapshot = await asyncio.to_thread(self._collect_sync)
        except Exception:
            self._record_probe("snapshot", False, self._monotonic())
            raise
        completed = self._monotonic()
        self._snapshot = snapshot
        self._last_success_monotonic = completed
        self._record_probe("snapshot", True, completed)
        return deepcopy(snapshot)

    def snapshot(self) -> dict[str, Any] | None:
        """Return a defensive copy of the latest complete snapshot."""
        return deepcopy(self._snapshot)

    def health(self) -> dict[str, object]:
        """Return one concise daemon state with deterministic precedence."""
        if self._snapshot is None or self._last_success_monotonic is None:
            return {"status": "starting", "sample_available": False}

        age = max(0.0, self._monotonic() - self._last_success_monotonic)
        if age > self.settings.stale_after_seconds:
            return {"status": "stale", "sample_available": True}

        repeated_failure = any(
            probe.available is False and probe.consecutive_failures >= 2
            for probe in self._probe_health.values()
        )
        return {
            "status": "degraded" if repeated_failure else "ok",
            "sample_available": True,
        }

    def _collect_sync(self) -> dict[str, Any]:
        mono = self._monotonic()
        if self.interface is None or not (self.paths.net_root / self.interface).exists():
            previous_interface = self.interface
            selected_interface = select_network_interface(
                self.paths.net_root, self.paths.proc_net_route, self.settings.network_interface
            )
            self.interface = selected_interface
            self._log_selection_transition(
                "Network interface", previous_interface, selected_interface
            )
        if self.root_device is None or not (self.paths.block_root / self.root_device).exists():
            previous_root = self.root_device
            selected_root = resolve_root_device(
                _read_text(self.paths.proc_mountinfo), self.paths.block_root
            )
            self.root_device = selected_root
            self._log_selection_transition(
                "Root backing device", previous_root, selected_root
            )
        cooling_missing = (
            (self.cooling_path is None and self.fan_path is None)
            or (self.cooling_path is not None and not self.cooling_path.exists())
            or (self.fan_path is not None and not self.fan_path.exists())
        )
        if cooling_missing:
            previous_cooling = (self.cooling_path, self.fan_path)
            selected_cooling = discover_cooling(self.paths.thermal_root, self.paths.hwmon_root)
            self.cooling_path, self.fan_path = selected_cooling
            self._log_selection_transition(
                "Cooling hardware", previous_cooling, selected_cooling
            )
        cpu_now = parse_cpu_times(_read_text(self.paths.proc_stat))
        usage = calculate_cpu_usage(self._previous_cpu, cpu_now)
        self._previous_cpu = cpu_now
        if usage is not None:
            self._cpu_samples.append(usage)
        smoothed = round(sum(self._cpu_samples) / len(self._cpu_samples), 1) if self._cpu_samples else 0.0

        frequency = read_frequency_mhz(self.paths.cpu_root)
        max_frequency = self.max_frequency_mhz

        if self._thermal_schedule.due(mono):
            temperature_now = read_cpu_temperature_c(self.paths.thermal_root, self.paths.hwmon_root)
            cooling_now = read_cooling(self.cooling_path, self.fan_path)
            thermal_ok = temperature_now is not None
            cooling_expected = self.cooling_path is not None or self.fan_path is not None
            cooling_ok = not cooling_expected or cooling_now["state"] != "unavailable"
            self._record_probe("thermal", thermal_ok, mono)
            self._record_probe("cooling", cooling_ok, mono)
            if thermal_ok:
                self._hardware_values["temperature_c"] = temperature_now
            elif self._probe_health["thermal"].available is False:
                self._hardware_values["temperature_c"] = None
            if cooling_ok:
                self._hardware_values["cooling"] = cooling_now
            elif self._probe_health["cooling"].available is False:
                self._hardware_values["cooling"] = {"state": "unavailable", "fan_speed_rpm": None}
            self._thermal_schedule.schedule(mono, self.settings.thermal_sample_interval_seconds)

        if self._power_schedule.due(mono):
            throttle_text = self._run_command(
                ["vcgencmd", "get_throttled"], self.settings.command_timeout_seconds
            )
            flags = parse_throttling(throttle_text)
            pmic = parse_pmic(
                self._run_command(
                    ["vcgencmd", "pmic_read_adc"], self.settings.command_timeout_seconds
                )
            )
            paired = [float(rail["power_w"]) for rail in pmic.values() if rail["power_w"] is not None]
            input_voltage = pmic.get("EXT5V", {}).get("voltage_v")
            if paired:
                power = {
                    "value_w": round(sum(paired), 3),
                    "source": "internal_rails",
                    "input_voltage_v": input_voltage,
                }
            elif self.profile is not None:
                power = {
                    "value_w": estimate_power_w(smoothed, frequency, max_frequency, self.profile),
                    "source": "cpu_estimate",
                    "input_voltage_v": input_voltage,
                }
            else:
                power = {"value_w": None, "source": "unavailable", "input_voltage_v": input_voltage}
            power_ok = flags is not None and power["source"] != "unavailable"
            self._record_probe("power", power_ok, mono)
            if power_ok:
                self._hardware_values["power"] = power
                self._hardware_values["flags"] = flags
            elif self._probe_health["power"].available is False:
                self._hardware_values["power"] = {
                    "value_w": None, "source": "unavailable", "input_voltage_v": None
                }
                self._hardware_values["flags"] = None
            self._power_schedule.schedule(mono, self.settings.power_sample_interval_seconds)

        temperature = self._hardware_values.get("temperature_c")
        power = self._hardware_values.get(
            "power", {"value_w": None, "source": "unavailable", "input_voltage_v": None}
        )
        flags = self._hardware_values.get("flags")

        network_now = read_network_counter(self.paths.net_root, self.interface, mono)
        download, upload = calculate_rates(self._previous_network, network_now)
        self._previous_network = network_now

        disk_now = parse_diskstats(_read_text(self.paths.proc_diskstats), self.root_device, mono)
        disk_read, disk_write = calculate_rates(self._previous_disk, disk_now)
        self._previous_disk = disk_now
        self._record_probe(
            "fast",
            cpu_now is not None and frequency is not None and network_now is not None and disk_now is not None,
            mono,
        )


        if self._raid_schedule.due(mono):
            self._raid_values = read_raid_arrays(self.paths.block_root)
            self._record_probe(
                "raid",
                self.paths.block_root.exists()
                and all(array["status"] != "unavailable" for array in self._raid_values),
                mono,
            )
            self._log_raid_transitions(self._raid_values)
            active = any(
                item["status"] in {"recovering", "resyncing", "checking", "reshaping"}
                for item in self._raid_values
            )
            interval = (
                self.settings.raid_active_interval_seconds
                if active
                else self.settings.raid_idle_interval_seconds
            )
            self._raid_schedule.schedule(mono, interval)

        if self._resource_schedule.due(mono):
            resources_now = {
                "memory": memory_status(_read_text(self.paths.proc_meminfo)),
                "root_filesystem": filesystem_status(self.paths.root),
                "network_meta": read_network_metadata(self.paths.net_root, self.interface),
                "booted_at": booted_at(
                    parse_uptime_seconds(_read_text(self.paths.proc_uptime)), self._now()
                ),
            }
            resources_ok = (
                resources_now["memory"]["total_bytes"] is not None
                and resources_now["root_filesystem"]["total_bytes"] is not None
                and resources_now["booted_at"] is not None
            )
            self._record_probe("resources", resources_ok, mono)
            if resources_ok or not self._slow_values:
                self._slow_values = resources_now
            elif self._probe_health["resources"].available is False:
                self._slow_values = resources_now
            self._resource_schedule.schedule(mono, self.settings.slow_sample_interval_seconds)

        health_state = build_health(flags)
        self._log_state_transition("Current undervoltage", health_state["power_supply"])
        self._log_state_transition("Thermal limiting", health_state["thermal_state"])
        self._log_state_transition("Performance limiting", health_state["performance_state"])

        network = dict(self._slow_values["network_meta"])
        network.update({"download_bytes_per_second": download, "upload_bytes_per_second": upload})
        return {
            "updated_at": self._now().replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "device": self.device,
            "cpu": {"usage_percent": smoothed, "frequency_mhz": frequency, "temperature_c": temperature},
            "memory": self._slow_values["memory"],
            "root_filesystem": self._slow_values["root_filesystem"],
            "power": power,
            "cooling": self._hardware_values.get("cooling", {"state": "unavailable", "fan_speed_rpm": None}),
            "network": network,
            "disk_activity": {"read_bytes_per_second": disk_read, "write_bytes_per_second": disk_write},
            "system": {"booted_at": self._slow_values["booted_at"]},
            "raid": {"arrays": self._raid_values},
            "smart": {"devices": self._smart_values},
            "health": health_state,
        }
