# Monitor Suite Agent Design

## 1. Document purpose

This document defines the design of Monitor Suite Agent, a lightweight system-monitoring service for Raspberry Pi computers. The service collects hardware and operating-system data locally, derives a small number of useful values, and exposes one concise JSON status endpoint through FastAPI and Uvicorn.

The design deliberately avoids exposing every available Linux, firmware, PMIC, thermal, storage, and network value. A value is included only when it has a clear operational meaning, a stable source, an understandable name, and an identified consumer use case.

## 2. Design status

- Project: Monitor Suite Agent
- Design baseline: 1.0
- Target runtime: Linux on Raspberry Pi
- Primary validated hardware: Raspberry Pi 5 Model B Rev 1.0
- Validated operating system: Debian GNU/Linux 13 (Trixie)
- Validated architecture: AArch64
- Validated Python version: Python 3.13.5
- Application framework: FastAPI
- Production server: Uvicorn
- API endpoint: `GET /status`
- Supporting endpoints: `GET /health` and generated FastAPI documentation under `/docs`

The supplied hardware probes validate the main Raspberry Pi 5 paths and data formats. Final runtime behavior still requires testing on the packaged application running on the target Raspberry Pi.

## 3. Goals

The service must:

1. Provide a single current-status endpoint for the monitor data.
2. Use direct Linux interfaces where practical instead of unnecessary Python dependencies.
3. Use Raspberry Pi firmware commands only for data not available through a suitable Linux interface.
4. Collect data in the background instead of triggering hardware reads for each HTTP request.
5. Return a complete cached snapshot quickly.
6. Distinguish measured, reported, calculated, estimated, and unavailable values.
7. Use names that communicate both meaning and unit.
8. Keep the response compact and predictable.
9. Avoid exposing persistent identifiers or sensitive system details.
10. Support future Home Assistant integration without designing the server around Home Assistant entity limitations.
11. Continue operating when optional telemetry sources are unavailable.
12. Shut down cleanly and avoid orphaned sampling tasks.

## 4. Non-goals

The service is not intended to be:

- A complete Linux monitoring agent
- A process monitor
- A log aggregation service
- A replacement for SMART or NVMe health tools
- A network discovery service
- A hardware inventory database
- A power meter with guaranteed USB-C input accuracy
- A Prometheus replacement
- A Home Assistant custom integration
- A source of one entity or field for every raw hardware value

## 5. Design principles

### 5.1 Meaning before availability

A value is not exposed merely because it can be collected. It must answer a useful question.

Examples:

- CPU temperature answers whether the processor is running hot.
- Root filesystem use answers whether the operating-system volume is running out of space.
- Individual PMIC rail voltages do not answer a normal user question and remain internal.

### 5.2 One value, one meaning

Names must not suggest broader coverage or greater accuracy than the source provides.

For example, the sum of paired PMIC output rails is not complete USB-C input power. The API therefore identifies its source rather than presenting it as measured input power.

### 5.3 No spray-and-pray telemetry

The normal response must not include:

- Every PMIC rail
- Every thermal zone
- Every `hwmon` channel
- Every disk
- Every network interface
- Every Linux counter
- Duplicate averages and totals
- Raw firmware responses

Detailed values may be used internally for calculations and future diagnostics.

### 5.4 Stable public contract

The `/status` schema should not change because Docker creates a new virtual interface, a kernel changes an `hwmon` index, or a new block device is attached.

### 5.5 Honest classification

Power values must state how they were obtained:

- `internal_rails`: calculated from matching PMIC voltage and current rails
- `cpu_estimate`: estimated from calibrated idle, full-load, CPU-use, and frequency values
- `unavailable`: no supported method produced a value

No software-derived value may be described as directly measured USB-C input power.

## 6. Validated Raspberry Pi 5 environment

The supplied probes confirmed the following environment:

- Model: Raspberry Pi 5 Model B Rev 1.0
- Processor: four ARM Cortex-A76 cores
- Architecture: AArch64
- Operating system: Debian GNU/Linux 13
- Kernel: `6.18.50+rpt-rpi-2712`
- CPU frequency range: 1500 MHz to 2400 MHz
- CPU governor during probing: `powersave`
- Thermal zone: `cpu-thermal`
- Root filesystem: ext4 on `/dev/nvme0n1p2`
- Root physical device: `nvme0n1`
- Physical network interface: `eth0`
- Network link: 1000 Mbps, full duplex
- Cooling device: `pwm-fan`, levels 0 through 4
- Fan speed channel: `fan1_input`
- PMIC ADC support: available through `vcgencmd pmic_read_adc`
- Throttling state during probing: `0x0`

The probe also found multiple disks, Docker bridges, transient virtual Ethernet interfaces, NVMe temperature channels, RP1 ADC channels, and attached storage. These findings confirm that automatic filtering and source selection are required.

## 7. Application architecture

```text
Linux procfs and sysfs      Raspberry Pi firmware
          |                          |
          +-----------+--------------+
                      |
               Telemetry readers
                      |
               Background sampler
                      |
          Validation and calculations
                      |
             Atomic status snapshot
                      |
                FastAPI /status
                      |
                    Uvicorn
```

### 7.1 Components

#### FastAPI application

Responsibilities:

- Define application lifespan
- Start one telemetry sampler
- Stop the sampler cleanly
- Serve cached responses
- Return HTTP errors in JSON
- Provide generated OpenAPI documentation

#### Uvicorn server

Responsibilities:

- Run the ASGI application
- Bind to the configured host and port
- Handle HTTP connections
- Forward proxy headers when configured

The normal deployment uses exactly one Uvicorn worker. Multiple workers would create multiple independent samplers and rolling histories.

#### Telemetry sampler

Responsibilities:

- Collect dynamic values on a schedule
- Refresh slower-changing values at an appropriate interval
- Maintain previous counters for rate calculations
- Convert raw values into documented units
- Build one complete snapshot
- Replace the cached snapshot atomically
- Preserve the last valid snapshot if a collection cycle partially fails

#### Telemetry readers

Responsibilities:

- Read a single source
- Parse and validate its format
- Return typed values or `null`
- Never apply user-facing health policy
- Never raise an unhandled exception for an optional source

#### Calculation layer

Responsibilities:

- Calculate CPU use from consecutive `/proc/stat` samples
- Calculate network throughput from consecutive interface counters
- Calculate disk throughput from consecutive block counters
- Calculate memory use from `MemTotal` and `MemAvailable`
- Calculate filesystem use from filesystem capacity values
- Calculate PMIC rail power from matched voltage and current channels
- Build concise health states from authoritative firmware flags

## 8. Runtime dependencies

Required packages:

```text
fastapi
uvicorn
```

Standard-library components include:

```text
asyncio
contextlib
collections.deque
dataclasses
datetime
logging
os
pathlib
re
statistics
subprocess
time
```

The design does not require `psutil`, Flask, NumPy, pandas, or shell-based `os.popen` calls.

## 9. Configuration

Configuration is read from environment variables.

```text
MONITOR_SUITE_HOST=127.0.0.1
MONITOR_SUITE_PORT=5000
MONITOR_SUITE_SAMPLE_INTERVAL=1
MONITOR_SUITE_COMMAND_TIMEOUT=2
MONITOR_SUITE_IDLE_W=
MONITOR_SUITE_FULL_LOAD_W=
```

### 9.1 Rules

- Host defaults to `127.0.0.1`.
- Port defaults to `5000`.
- Dynamic sample interval defaults to one second.
- Command timeout defaults to two seconds.
- Power calibration overrides are optional.
- Full-load power must be greater than idle power.
- Invalid configuration must stop startup with a clear error.
- The supported deployment is direct authenticated access over the trusted LAN.

## 10. API endpoints

### 10.1 `GET /status`

Returns the latest complete monitoring snapshot.

This is the only endpoint that returns system-monitoring data.

### 10.2 `GET /health`

Returns service availability and snapshot freshness only. It does not duplicate Raspberry Pi health and monitoring values.

Example:

```json
{
  "status": "ok",
  "version": "2.1.0",
  "sample_available": true
}
```

### 10.3 `GET /docs`

Provides generated FastAPI API documentation.

### 10.4 Removed endpoints

The following routes must not exist:

```text
GET /telemetry
GET /power_usage
```

## 11. Public `/status` schema

```json
{
  "updated_at": "2026-09-19T08:26:32Z",
  "device": {
    "model": "Raspberry Pi 5 Model B Rev 1.0",
    "operating_system": "Debian GNU/Linux 13",
    "kernel_version": "6.18.50+rpt-rpi-2712",
    "architecture": "aarch64"
  },
  "cpu": {
    "usage_percent": 12.4,
    "frequency_mhz": 1500.0,
    "temperature_c": 34.8
  },
  "memory": {
    "used_percent": 45.7,
    "available_bytes": 4592922624,
    "total_bytes": 8453947392
  },
  "root_filesystem": {
    "used_percent": 67.0,
    "available_bytes": 158950322176,
    "total_bytes": 503653924864
  },
  "power": {
    "value_w": 2.48,
    "source": "internal_rails",
    "input_voltage_v": 5.16
  },
  "cooling": {
    "state": "idle",
    "fan_speed_rpm": 0
  },
  "network": {
    "interface": "eth0",
    "status": "up",
    "link_speed_mbps": 1000,
    "download_bytes_per_second": 11230,
    "upload_bytes_per_second": 8896
  },
  "disk_activity": {
    "read_bytes_per_second": 0,
    "write_bytes_per_second": 73728
  },
  "system": {
    "booted_at": "2026-09-19T07:01:23Z"
  },
  "health": {
    "status": "ok",
    "power_supply": "ok",
    "thermal_state": "normal",
    "performance_state": "normal"
  }
}
```

## 12. Field definitions and units

### 12.1 Top-level timestamp

#### `updated_at`

- Type: string
- Format: ISO 8601 UTC timestamp
- Meaning: Time at which the complete cached snapshot was finalized
- Example: `2026-09-19T08:26:32Z`

### 12.2 Device

#### `device.model`

- Type: string
- Source: `/proc/device-tree/model`
- Meaning: Raspberry Pi hardware model

#### `device.operating_system`

- Type: string
- Source: `PRETTY_NAME` from `/etc/os-release`
- Meaning: Installed operating-system name and release

#### `device.kernel_version`

- Type: string
- Source: kernel release
- Meaning: Running Linux kernel version

#### `device.architecture`

- Type: string
- Source: system architecture
- Meaning: Running machine architecture

Device information is cached because it is static during normal operation.

### 12.3 CPU

#### `cpu.usage_percent`

- Type: number
- Unit: percent
- Range: 0 to 100
- Precision: one decimal place
- Source: consecutive aggregate `/proc/stat` samples
- Meaning: Smoothed total CPU utilization

Calculation:

```text
total_delta = current_total - previous_total
idle_delta = current_idle - previous_idle
usage_percent = 100 * (total_delta - idle_delta) / total_delta
```

The value uses a short rolling average to reduce one-second noise. The API does not expose separate instantaneous, 10-second, 60-second, or per-core values.

#### `cpu.frequency_mhz`

- Type: number or `null`
- Unit: megahertz
- Precision: one decimal place
- Preferred source: `scaling_cur_freq`
- Fallback source: `cpuinfo_cur_freq`
- Meaning: Current CPU frequency

Raw sysfs values are converted from kilohertz to megahertz.

#### `cpu.temperature_c`

- Type: number or `null`
- Unit: degrees Celsius
- Precision: one decimal place
- Preferred source: thermal zone with type `cpu-thermal`
- Fallback source: validated CPU temperature channel from `hwmon`
- Meaning: Current CPU temperature

The implementation selects the thermal zone by its type, not by assuming that `thermal_zone0` always represents the CPU.

### 12.4 Memory

#### `memory.used_percent`

- Type: number
- Unit: percent
- Precision: one decimal place
- Source: `/proc/meminfo`
- Meaning: Memory not currently available for allocation

Calculation:

```text
used_bytes = MemTotal - MemAvailable
used_percent = 100 * used_bytes / MemTotal
```

`MemAvailable` is used instead of `MemFree` so reclaimable caches are handled correctly.

#### `memory.available_bytes`

- Type: integer
- Unit: bytes
- Source: `MemAvailable`
- Meaning: Estimated memory available for new workloads without swapping

#### `memory.total_bytes`

- Type: integer
- Unit: bytes
- Source: `MemTotal`
- Meaning: Total usable system memory reported by Linux

`used_bytes` is omitted because it can be calculated from total minus available.

### 12.5 Root filesystem

#### `root_filesystem.used_percent`

- Type: number
- Unit: percent
- Precision: one decimal place
- Scope: `/`
- Meaning: Used capacity of the root filesystem

#### `root_filesystem.available_bytes`

- Type: integer
- Unit: bytes
- Meaning: Root-filesystem capacity available to an unprivileged process

#### `root_filesystem.total_bytes`

- Type: integer
- Unit: bytes
- Meaning: Total capacity of the root filesystem

Filesystem capacity is collected through Python's filesystem APIs. Mount information is used to resolve the root device and filesystem identity internally.

The response does not include device paths, mount options, filesystem type, or model names.

### 12.6 Power

#### `power.value_w`

- Type: number or `null`
- Unit: watts
- Precision: up to three decimal places
- Meaning: Best available power value produced by the selected source

The interpretation depends on `power.source`.

#### `power.source`

- Type: string
- Allowed values:
  - `internal_rails`
  - `cpu_estimate`
  - `unavailable`

Meaning:

- `internal_rails`: sum of matched PMIC voltage and current rail outputs
- `cpu_estimate`: calibrated software estimate using CPU use and frequency
- `unavailable`: no supported power method produced a value

#### `power.input_voltage_v`

- Type: number or `null`
- Unit: volts
- Precision: up to three decimal places
- Source on validated Raspberry Pi 5: PMIC `EXT5V_V`
- Meaning: Reported external 5 V input rail voltage

The Raspberry Pi 5 PMIC data does not provide a matching `EXT5V_A` channel in the validated output. The service therefore cannot calculate complete USB-C input power from PMIC data alone.

### 12.7 Cooling

#### `cooling.state`

- Type: string
- Allowed values:
  - `idle`
  - `active`
  - `unavailable`

Meaning:

- `idle`: a validated cooling device exists and its current state is zero
- `active`: a validated cooling device exists and its current state is greater than zero
- `unavailable`: no validated cooling-device source is available

#### `cooling.fan_speed_rpm`

- Type: integer or `null`
- Unit: revolutions per minute
- Preferred source: validated fan input under Linux `hwmon`
- Meaning: Current fan speed

A fan speed of zero means a validated fan channel reports zero RPM. It must not be used as a replacement for an unavailable reading.

Cooling level and maximum cooling level remain internal because they are driver details rather than broadly meaningful measurements.

### 12.8 Network

#### `network.interface`

- Type: string or `null`
- Meaning: Selected physical network interface

Selection rules:

1. Ignore loopback.
2. Ignore Docker bridges.
3. Ignore `veth` interfaces.
4. Prefer the physical interface associated with the default route.
5. Fall back to a physical interface with carrier.

#### `network.status`

- Type: string
- Allowed values:
  - `up`
  - `down`
  - `unknown`

#### `network.link_speed_mbps`

- Type: integer or `null`
- Unit: megabits per second
- Meaning: Negotiated physical link speed

#### `network.download_bytes_per_second`

- Type: integer or `null`
- Unit: bytes per second
- Meaning: Current receive rate on the selected physical interface

#### `network.upload_bytes_per_second`

- Type: integer or `null`
- Unit: bytes per second
- Meaning: Current transmit rate on the selected physical interface

Rates are calculated from consecutive cumulative counters and monotonic elapsed time.

```text
rate = max(0, current_counter - previous_counter) / elapsed_seconds
```

Counter decreases are treated as resets. The first observation returns `null` until a valid rate can be calculated.

### 12.9 Disk activity

#### `disk_activity.read_bytes_per_second`

- Type: integer or `null`
- Unit: bytes per second
- Meaning: Current read throughput of the physical device backing the root filesystem

#### `disk_activity.write_bytes_per_second`

- Type: integer or `null`
- Unit: bytes per second
- Meaning: Current write throughput of the physical device backing the root filesystem

The implementation resolves the physical root device and monitors that device only. It must not add partition and whole-device counters together.

For `/proc/diskstats`, sector counters are converted using the kernel's 512-byte accounting unit for these fields.

### 12.10 System

#### `system.booted_at`

- Type: string
- Format: ISO 8601 UTC timestamp
- Source: current wall-clock time minus monotonic uptime
- Meaning: Time at which the current operating-system boot began

A separate continuously increasing `uptime_seconds` value is omitted because it duplicates this timestamp.

### 12.11 Health

The health object contains only conditions backed by authoritative Raspberry Pi firmware flags.

#### `health.status`

Allowed values:

- `ok`
- `warning`
- `problem`
- `unknown`

Policy:

- `problem`: one or more current firmware health conditions are active
- `warning`: reserved for a future clearly defined non-critical condition
- `ok`: all current authoritative conditions are normal
- `unknown`: throttling status cannot be retrieved or parsed

Historical conditions must not turn the current status into `problem`.

#### `health.power_supply`

Allowed values:

- `ok`
- `under_voltage`
- `unknown`

#### `health.thermal_state`

Allowed values:

- `normal`
- `limited`
- `unknown`

#### `health.performance_state`

Allowed values:

- `normal`
- `frequency_capped`
- `throttled`
- `unknown`

If both frequency capping and throttling are active, `throttled` takes precedence.

The health response does not contain an `issues` array. Each field explains its own condition without duplicating information.

## 13. Power calculation design

### 13.1 Raspberry Pi 5 PMIC method

The validated Raspberry Pi 5 provides matching current and voltage channels such as:

```text
VDD_CORE_A current(7)=1.69670000A
VDD_CORE_V volt(15)=0.72124470V
```

Each matched rail is calculated as:

```text
rail_power_w = voltage_v * current_a
```

The internal rail result is:

```text
internal_rail_power_w = sum(matched_independent_rail_power_w)
```

Only explicitly matched `_A` and `_V` channels are used. Voltage-only channels such as `EXT5V_V` and `BATT_V` do not contribute to the sum.

The calculation is classified as `internal_rails`, not measured input power.

### 13.2 PMIC caveat

The PMIC total does not necessarily include:

- USB-C input current
- PMIC conversion losses
- Power-supply conversion losses
- Cable losses
- Every external USB device
- Every PCIe or fan load
- Every board-level load outside the paired channels

Actual input power requires an external input-voltage and current sensor.

### 13.3 Older Raspberry Pi fallback

When paired PMIC rails are unavailable, the service may calculate a software estimate if a supported model profile exists.

```text
usage = clamp(cpu_usage_percent / 100, 0, 1)
frequency_ratio = clamp(current_frequency / maximum_frequency, 0, 1)
frequency_factor = 0.65 + 0.35 * frequency_ratio
dynamic_power = full_load_power - idle_power
estimated_power = idle_power + dynamic_power * usage * frequency_factor
```

This prevents full CPU use at minimum frequency from incorrectly collapsing to idle power.

The result is classified as `cpu_estimate`.

### 13.4 Calibration

Users may override idle and full-load profile values through environment variables. Calibration should be based on an external power meter connected at the desired measurement point.

NVMe boot detection must not change the power profile automatically. Booting from NVMe does not reveal the current or maximum NVMe power consumption.

## 14. Sampling strategy

The sampler uses independent monotonic deadlines. A single one-second lifecycle loop checks which probe groups are due, reuses cached results for groups that are not due, and atomically replaces the complete public snapshot.

### 14.1 Dynamic counters: 1 second

- CPU usage from `/proc/stat`
- CPU frequency from cpufreq sysfs
- Physical network byte counters
- Root-disk sector counters

These values are inexpensive and require frequent samples for meaningful rates.

### 14.2 Thermal and cooling: 2 seconds

- CPU temperature
- NVMe composite temperatures from `hwmon`
- Fan speed and cooling state

These sysfs values can change quickly enough to justify a short interval but do not need to be read every lifecycle tick.

### 14.3 Power and current firmware health: 5 seconds

- PMIC rail calculation
- Input voltage
- Current under-voltage, thermal-limit, and throttling flags

This group invokes `vcgencmd`, so it is cached separately instead of running every second.

### 14.4 Resources: 30 seconds

- Memory usage
- Root-filesystem usage
- Network metadata
- Boot time

### 14.5 Adaptive RAID schedule

RAID sysfs is read every 30 seconds while arrays are idle. If any array is recovering, resyncing, checking, or reshaping, the next RAID probe is scheduled after two seconds so progress remains useful. The schedule returns to 30 seconds after the operation ends.

### 14.6 SMART schedule

A root-only systemd oneshot collector runs every 15 minutes and writes a sanitized atomic cache. SMART uses `smartctl -n standby`; a sleeping disk retains its last known values and is not awakened for monitoring. The unprivileged API validates cache schema and freshness, preserves known device identities as unavailable when the cache cannot be trusted, and overlays fresh NVMe composite temperatures from `hwmon`.

### 14.7 Static values

Hardware model, operating-system information, architecture, selected interfaces, root-device mapping, cooling discovery, and maximum CPU frequency are collected or resolved at startup.

### 14.8 Snapshot consistency

Each due probe group updates its own cache. A sampling cycle builds a new response away from the active snapshot and replaces the cached snapshot only after all due work is complete. Clients never receive a partially updated dictionary.

## 15. Error handling

### 15.1 Optional sources

If an optional value cannot be collected:

- Log a concise debug or warning message as appropriate.
- Return `null` for the affected numeric field.
- Use `unknown` or `unavailable` for the affected state field.
- Preserve other valid values.
- Do not fail the complete `/status` response.

### 15.2 Critical sources

If no complete snapshot has ever been produced, `/status` returns HTTP 503 with a JSON error.

### 15.3 Command execution

All external commands use argument lists with `subprocess.run`, a timeout, captured output, and exit-code validation.

Shell command strings and `os.popen` are not permitted.

### 15.4 Stale data

The implementation tracks the last successful snapshot time internally. `/health` reports `stale` when the snapshot age exceeds `MONITOR_SUITE_STALE_AFTER`. Repeated probe-group failures report `degraded` only while the main snapshot remains fresh.

Snapshot age does not need to be exposed in the normal `/status` payload unless a client requirement is established.

## 16. Source selection and filtering

### 16.1 Thermal sources

- Select CPU temperature by semantic type or validated label.
- Do not depend on `thermal_zone0` or `hwmon0` numbering.
- Keep RP1 and NVMe temperatures internal unless a future use case justifies exposing them.

### 16.2 Network sources

- Exclude loopback.
- Exclude Docker bridges.
- Exclude transient `veth` interfaces.
- Select one physical interface.
- Do not expose MAC addresses or IP addresses.

### 16.3 Storage sources

- Resolve `/` through mount information.
- Identify the backing partition and physical block device.
- Use filesystem APIs for root capacity.
- Use only the root physical disk for disk-rate calculations.
- Do not expose attached USB, SD, RAID, or secondary NVMe activity in the main response.

### 16.4 Hardware-monitoring sources

Linux `hwmon` indexes are not stable identifiers. Discovery must use device links, driver names, and validated labels. Unknown voltage, current, temperature, and fan channels are not exposed automatically.

## 17. Internal values not exposed by `/status`

The service may collect or retain the following internally:

- Raw `/proc/stat` counters
- Rolling CPU sample history
- Raw PMIC rails
- PMIC channel matching data
- Raw throttling hexadecimal value
- Historical throttling bits
- CPU minimum and maximum frequency
- CPU governor
- Raw memory fields
- Swap values
- Cache and buffer values
- Raw network counters
- Network errors and drops
- Docker and virtual interfaces
- Raw disk counters
- Attached block-device inventory
- Root partition and physical-device mapping
- Cooling level and maximum level
- RP1 temperature
- NVMe temperature channels
- Bootloader version and capabilities
- ARM and GPU memory split
- Sample duration
- Collection-error counts

Collection does not imply public exposure.

## 18. Privacy and security

The service must not expose:

- Raspberry Pi serial number
- MAC addresses
- IP addresses by default
- Wi-Fi SSIDs or credentials
- Process lists
- Process command lines
- Environment variables
- Usernames
- Package inventories
- Complete mount options
- Docker container identifiers
- Device serial numbers

Recommended deployment practices:

- Run as a non-root service account.
- Grant only the groups required for read-only firmware access.
- Bind to the LAN interface only when API-key authentication is configured.
- Use firewall restrictions when binding to a LAN address.
- Do not add unauthenticated write endpoints.
- Keep `pmicwr` and other firmware write operations outside the application.

## 19. Performance requirements

The service should:

- Use one sampler task.
- Use one Uvicorn worker by default.
- Return cached `/status` responses without launching commands.
- Move blocking filesystem and subprocess work outside the asyncio event loop.
- Use bounded rolling buffers.
- Avoid retaining unbounded history.
- Avoid polling static values every second.
- Complete normal status requests in a few milliseconds when the snapshot is available.

## 20. Testing strategy

### 20.1 Unit tests

Required coverage:

- Raspberry Pi model normalization
- `/proc/stat` CPU calculations
- Counter reset handling
- CPU frequency conversion
- Thermal value conversion
- Memory calculation
- Root-filesystem calculation
- Network-rate calculation
- Disk-rate calculation
- Physical interface filtering
- Root-device resolution
- PMIC parsing with real Raspberry Pi 5 output
- PMIC voltage/current pairing
- Voltage-only rail handling
- Power-source selection
- Throttling bit decoding
- Health-state precedence
- Cooling-state mapping
- Configuration validation

### 20.2 API tests

Required coverage:

- `/status` exists.
- `/health` exists.
- `/telemetry` does not exist.
- `/power_usage` does not exist.
- Response field names match the schema.
- Units are represented by field suffixes.
- Unavailable values use `null`, `unknown`, or `unavailable` correctly.
- Raw PMIC rails are absent.
- Raw throttling flags are absent.
- Sensitive identifiers are absent.

### 20.3 Hardware tests

Required Raspberry Pi 5 tests:

- Idle system
- Sustained CPU load
- Fan transition from idle to active
- PMIC rail response under load
- Network receive and transmit activity
- Root-disk read and write activity
- Service restart
- Uvicorn shutdown
- Missing `vcgencmd`
- `vcgencmd` timeout
- Unavailable fan RPM
- Network link down
- Counter reset or interface replacement

### 20.4 Cross-model tests

Before claiming support for another Raspberry Pi model:

- Capture its exact model string.
- Verify thermal paths.
- Verify CPU-frequency paths.
- Verify supported `vcgencmd` commands.
- Confirm whether PMIC ADC channels exist.
- Validate the fallback profile against external measurements.

## 21. Acceptance criteria

The design is implemented correctly when:

1. Uvicorn runs one FastAPI application and one sampler.
2. `/status` is the only monitoring-data endpoint.
3. `/status` returns the documented schema.
4. Every numeric field has an explicit unit in its name.
5. Power source and limitations are unambiguous.
6. Docker and virtual interfaces do not appear in the response.
7. Only the root filesystem and root physical disk are represented.
8. Raw PMIC rails do not appear in the response.
9. Raw throttling flags do not appear in the response.
10. `issues` is absent from health.
11. Historical firmware events do not appear as current failures.
12. Optional source failures do not break unrelated values.
13. Sensitive identifiers are absent.
14. Tests include the verified Raspberry Pi 5 probe formats.
15. Hardware behavior is verified before the release is described as hardware-tested.

## 22. Roadmap status

RAID health and the approved SMART sensor values were implemented and refined through version 1.4.1. The remaining roadmap item is the separate Home Assistant integration. See `docs/ROADMAP.md` for the approved entity surface.

## 23. Final design summary

Monitor Suite Agent is a focused status service, not a raw telemetry dump. It collects direct Linux and Raspberry Pi firmware data in one background sampler, performs clearly defined calculations, and serves a compact cached response through FastAPI and Uvicorn.

The public API exposes only values with clear operational meaning:

- Device identity
- CPU use, frequency, and temperature
- Memory use
- Root-filesystem use
- Classified power and input voltage
- Cooling state and fan speed
- Physical network throughput
- Root-disk activity
- Boot time
- Authoritative power, thermal, and performance health

Everything else remains internal until it has a specific, validated purpose.

## 11. Daemon health accounting

`GET /health` returns one concise state with fixed precedence:

1. `starting` when no complete snapshot has been published.
2. `stale` when the last complete snapshot exceeds `MONITOR_SUITE_STALE_AFTER`.
3. `degraded` when any expected probe group has failed at least twice consecutively while the main snapshot is still fresh.
4. `ok` otherwise.

Expected probe groups are the complete snapshot cycle, fast counters, thermal data, detected cooling hardware, power and firmware health, slow resources, RAID, and SMART. One isolated failure retains the last good value and does not degrade the daemon. A successful probe resets its failure count. Internal probe names, counters, timestamps, and failure details are not exposed through `/health` or Home Assistant entities.

## 12. Transition logging

Normal successful collection cycles do not write telemetry logs. The daemon records the initial state silently and logs only a later meaningful change.

Logged transitions are:

- RAID degradation, failure, active recovery work, completion, disappearance, and return
- Power, cooling, thermal, resource, fast-counter, RAID, SMART, and whole-snapshot availability after the failure threshold, plus recovery
- Current undervoltage appearing or clearing
- Current thermal limiting appearing or clearing
- Current performance throttling or frequency capping changing
- Selected network interface changing
- Root backing device changing
- Cooling hardware selection changing

An unexpected collection exception is logged on the first consecutive failure. Identical repeated exceptions remain quiet. If the failure reaches the availability threshold, the availability transition is logged once. Initial baselines and unchanged states are never logged.
