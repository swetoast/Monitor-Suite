# Roadmap

This roadmap contains only the remaining agreed work for Monitor Suite Agent. Values that are collected internally do not automatically become API fields, Home Assistant entities, or entity attributes.

## 1. RAID health (implemented and refined through 2.6.0)

The supplied Raspberry Pi 5 RAID and SMART probe is preserved as `tests/fixtures/raid_smart_probe_pi5.txt` and is authoritative regression evidence for the initial implementation.

Implement one meaningful status result per detected Linux MD array. The Home Assistant representation is one status sensor per array, for example:

```text
sensor.monitor_suite_md0_status
```

Supported states:

- `Healthy`
- `Degraded`
- `Failed`
- `Recovering`
- `Resyncing`
- `Checking`
- `Reshaping`
- `Unavailable`

Approved attributes:

- `raid_level`
- `active_members`
- `expected_members`
- `failed_members`
- `redundancy`

During an active RAID operation only, add `progress` with unit `%`. Do not expose member device names, serial numbers, WWNs, RAID UUIDs, raw SMART tables, raw command output, or attributes that duplicate the sensor state.

The verified fixture contains one clean RAID 0 array, `md0`, with two expected and active members, zero failed members, and no redundancy. SMART health remains attached to each physical member disk and is not aggregated into the RAID array.

## 2. SMART monitoring (implemented and refined through 2.6.0)

SMART monitoring must expose only values that provide clear, independent user value. SMART data that is useful only for calculating health remains internal.

Create sensors only for supported physical disks. Do not create SMART entities for devices where SMART is unavailable, such as the probed `mmcblk0` device.

### SMART status

Create one SMART status sensor per supported physical disk, for example:

```text
sensor.monitor_suite_sda_smart_status
```

Supported states:

- `Healthy`
- `Warning`
- `Failed`
- `Testing`
- `Unavailable`

The status sensor has no attributes. Its state is calculated internally from the overall SMART result and relevant protocol-specific health indicators.

A nonzero `smartctl` exit status must not automatically mark a disk as failed. The parsed SMART result and meaningful health indicators are authoritative because unsupported log operations can produce a nonzero exit status for an otherwise healthy disk.

### Disk temperature

Create one temperature sensor per supported physical disk when a trustworthy temperature is available, for example:

```text
sensor.monitor_suite_sda_temperature
```

- Unit: `°C`
- Device class: `temperature`
- State class: `measurement`

### Remaining life

Create one remaining-life sensor only when the device reports a trustworthy endurance value, primarily through NVMe `percentage_used`, for example:

```text
sensor.monitor_suite_nvme0n1_remaining_life
```

- Unit: `%`
- State class: `measurement`
- Value: `100 - percentage_used`, clamped to the range 0 through 100

Do not create this sensor for devices that do not provide a reliable endurance value.

### Internal SMART inputs

The following values may be used internally to calculate SMART status but must not be exposed as separate sensors or normal entity attributes:

- Overall SMART pass or fail result
- Reallocated sectors
- Pending sectors
- Offline uncorrectable sectors
- Failed SMART attributes
- NVMe critical warning
- NVMe available spare and threshold
- NVMe media errors
- Current self-test state and latest result
- SMART availability

### Excluded SMART data

Do not expose the following as normal sensors or attributes:

- Model and firmware information
- Serial numbers, WWNs, EUI-64 values, or other unique identifiers
- Power-on hours and power-cycle counts
- Start-stop and load-cycle counts
- Unsafe-shutdown counts
- UDMA CRC counts
- Historical self-test lists
- NVMe command-error counts and raw error-log entries
- Raw SMART attributes
- Raw `smartctl` output or exit status

### Approved SMART entity surface

For each supported physical disk, expose only:

1. SMART status
2. Temperature, when available
3. Remaining life, when reliably reported

No other SMART sensors or attributes are approved.

## 3. Home Assistant integration

Build a separate Home Assistant integration consuming `/status` through one shared coordinator.

Requirements:

- Expose only the approved RAID and SMART entities plus other previously approved high-value daemon entities.
- Use predictable entity identifiers and understandable displayed names.
- Assign correct units, device classes, state classes, and validated Material Design Icons.
- Handle daemon and individual-value availability cleanly.
- Avoid unnecessary polling and reuse one coordinated API update.
- Keep raw source data, internal calculations, and diagnostic details out of normal entity attributes.

## Explicitly outside the roadmap

- External power sensors
- Configurable monitored filesystem
- NVMe health as a separate broad feature beyond the approved SMART status, temperature, and remaining-life sensors
- Prometheus output
- Authentication

## 4. Daemon architecture hardening (completed in 2.0.0)

The following work is approved before the Home Assistant integration is treated as production-ready:

1. Isolate expensive SMART work (implemented in 1.6.0) from the fast telemetry loop so a slow disk cannot delay CPU, network, disk-rate, thermal, or power updates.
2. Publish lightweight API snapshots independently of the external SMART collector.
3. Run fixed-purpose SMART collection in a separate root-only systemd oneshot service on a 15-minute timer.
4. Track probe-group success internally and apply explicit last-good-value and availability rules without exposing diagnostic clutter as normal sensors. Implemented in 2.0.0.
5. Rediscover the network interface (implemented in 1.6.0), root backing device, and cooling paths only when their cached selections become invalid.
6. Add typed public API response models (implemented in 1.6.0) to protect the `/status` and `/health` contracts.
7. Report concise daemon health states for startup, stale snapshots, and repeated expected-probe failures without duplicating telemetry. Completed and regression-tested across every probe group in 2.1.0.
8. Log state transitions rather than unchanged probe cycles. Completed and regression-tested in 2.2.0 for RAID state and recovery, probe availability, current undervoltage, thermal and performance limiting, selected network interface, root backing device, and cooling hardware. Public-source privacy cleanup was completed in 2.2.1.
9. Keep RAID state in the unprivileged API collector and SMART access in the privileged collector, joined only through the sanitized cache contract.
10. Keep the daemon stateless. Do not add SQLite or time-series storage. Home Assistant owns history. The only local state is the nonsensitive atomic SMART cache under `/run`, used to cross the privilege boundary and retain sleeping-disk health.


## 5. Security hardening (implemented in 1.7.0)

- API-key authentication is mandatory for non-loopback binds.
- API documentation is disabled by default.
- Proxy headers require explicit trusted proxy addresses or networks.
- Uvicorn concurrency, backlog, and keep-alive limits are bounded.
- A validated dependency lock file is included for production deployment.
- A least-privilege systemd baseline and NAS deployment guidance are included.


## 6. Rename and GitHub deployment (implemented in 2.0.0)

- The daemon is named Monitor Suite Agent.
- The Python package is `monitor_suite_agent`.
- The command is `monitor-suite-agent`.
- The service is `monitor-suite-agent.service`.
- Environment variables use the `MONITOR_SUITE_` prefix.
- `install.sh` installs, updates, reports status, and uninstalls from `https://github.com/swetoast/Monitor-Suite.git`.
- Direct authenticated access from the NAS over the trusted LAN is the normal deployment.

## 7. Installer API readiness verification (completed in 2.7.0)

The live installation on September 19, 2026 exposed a false-success case: systemd briefly reported the service as active while Uvicorn was entering a restart loop because another process already owned the configured port. The installer then printed the status and health URLs even though those URLs were served by the unrelated process.

Before printing `Monitor Suite Agent is installed and running.`, the installer must verify the installed API itself rather than relying only on the transient systemd unit state.

Required acceptance checks:

1. Confirm that `monitor-suite-agent.service` remains active after the initial startup grace period.
2. Request the configured `/health` endpoint with the generated or preserved API token.
3. Require HTTP 200 without accepting redirects.
4. Require a JSON object rather than HTML or another response format.
5. Verify that the response identifies Monitor Suite Agent through the expected health contract.
6. Verify that the reported API version matches the version installed from the checked-out source.
7. On failure, do not print the success message or endpoint summary.
8. Show a concise diagnostic that distinguishes a port conflict, failed service, authentication error, invalid response, and version mismatch.
9. Include the relevant systemd status or recent journal context without printing the API token.
10. Add regression coverage for a competing process that already owns the configured port and returns an unrelated redirect or JSON response.

Implemented in 2.7.0 with startup-grace validation, authenticated health-contract verification, version matching, failure classification, token-safe diagnostics, and regression coverage for unrelated processes occupying the configured port. The Home Assistant integration remains the only separate consumer-side roadmap item.


## 8. amd64 device and telemetry support (in progress)

Monitor Suite Agent has so far been validated only on arm64 Raspberry Pi 5 hardware. Every platform-specific reader in the collector currently assumes that environment: hardware identity comes from `/proc/device-tree/model`, CPU temperature is selected by the `cpu-thermal` thermal-zone type, cooling is discovered from a `pwm-fan` device, and power and firmware health come exclusively from `vcgencmd`. On an amd64 host none of those sources exist, so the affected values collapse to `unavailable` and the firmware probes fail on every cycle.

This section covers making the agent operate correctly on amd64 (`x86_64`) hosts. It is bounded by two fixed rules for the whole section:

- **The approved sensor and Home Assistant entity surface does not change.** amd64 support adds no new sensors and removes none. The existing entities defined in sections 1 through 3 remain the complete entity contract on every platform.
- **New platform data is exposed only as additional attributes on existing `/status` objects**, never as new sensors, and only when it carries clear, independent meaning. Every added attribute is still subject to meaning-before-availability, honest classification, and the privacy rules below. Values collected internally to classify a state do not automatically become attributes.

Honest classification continues to govern gaps: where amd64 has no trustworthy equivalent of a Raspberry Pi source, the affected field reports `unavailable` rather than an invented value.

### 8.0 Phase 0: architecture routing and contract lock

Phase 0 establishes the platform boundary before any amd64-specific telemetry source is added.

- Detect the machine architecture once with `platform.machine()`.
- Normalize `aarch64` and `arm64` to `aarch64`.
- Normalize `x86_64` and `amd64` to `amd64`.
- Reject unsupported architectures explicitly.
- Route `aarch64` through the existing Raspberry Pi collection behavior unchanged.
- Route `amd64` through the x86 capability path without running Raspberry Pi-only firmware commands.
- Keep capability discovery out of architecture detection. Architecture detection selects the path; each collector later determines which measurements the machine actually provides.

The existing API and Home Assistant contract is the compatibility baseline for both architectures. amd64 must remain as close to the existing aarch64 implementation as the available hardware permits. Endpoint paths, top-level objects, core state fields, field types, units, Home Assistant entity IDs, device classes, state classes, icons, availability behavior, and the basic attribute structure remain stable. Platform differences belong primarily inside agent collectors. A small number of optional, typed, meaningful attributes may differ when hardware capabilities differ, but core sensor state and meaning must not change. Raspberry Pi telemetry must not be redesigned, renamed, consolidated, degraded, or otherwise changed as part of amd64 support.

Phase 0 acceptance criteria:

- Physical aarch64 reports `architecture=aarch64` and selects the Raspberry Pi path.
- Physical x86_64 reports `architecture=amd64` and selects the x86 path.
- amd64 never executes `vcgencmd`.
- Raspberry Pi fixture output remains unchanged.
- `/status` and `/health` retain their existing schemas and core state semantics.
- Architecture-specific gaps do not degrade daemon health merely because a Raspberry Pi-only source does not exist.

Because the public API models forbid unknown fields (`extra="forbid"`, enforced by the API-contract regression tests), any attribute added under this section must be added to the typed response model in the same change. "Attributes can be added to endpoints" is therefore a deliberate, typed contract change, not an open passthrough of raw data.

### 8.1 Authoritative amd64 evidence

The following synthetic-from-verified x86 fixtures are preserved as the authoritative regression evidence for this section, in the same way the Raspberry Pi 5 probe is authoritative for sections 1 and 2:

- `tests/fixtures/monitor_suite_x86_fixture.txt` — full platform capability snapshot (DMI identity, thermal zones, `hwmon` providers, powercap, storage, network).
- `tests/fixtures/monitor_suite_x86_probe.txt` — tool and runtime availability, CPU topology, `hwmon` temperature and fan channels, cooling devices.
- `tests/fixtures/monitor_suite_x86_followup.txt` — physical disks, SMART health per device, RAID array state, physical-versus-virtual interface filtering.
- `tests/fixtures/monitor_suite_x86_power_probe.txt` — RAPL powercap energy counters, `perf` RAPL events, and `turbostat` power metrics, with `recommended_source=powercap_energy_delta`.
- `tests/fixtures/monitor_suite_amd64_fan_fixture.txt` — Super-I/O fan inputs, PWM readback, and ACPI `Fan` cooling devices.

All fixtures are derived from observations on verified physical x86 machines. They are read-only and privacy-scrubbed: no hostnames, addresses, hardware serials, UUIDs, WWNs, personal paths, or raw command output. That scrub level is the acceptance baseline for anything derived from them. Exact counts are stored per fixture and regression-tested; partitions are never included in `physical_disk_count`, and only exact `pwmN` files are included in `pwm_input_count`.

### 8.2 Platform capability layer (enabling refactor)

Introduce an internal platform-capability layer that selects sources by detected capability rather than by assuming Raspberry Pi hardware. Requirements:

- Detect the platform from stable evidence (architecture and the presence of `/proc/device-tree/model` versus `/sys/class/dmi/id`), not from `platform.machine()` alone.
- Gate Raspberry Pi firmware commands (`vcgencmd get_throttled`, `vcgencmd pmic_read_adc`) behind Pi detection so amd64 hosts never execute or repeatedly fail them.
- Keep all selection driver-name and label based, never `hwmon` or `thermal_zone` index based, consistent with section 16.4 of the design.
- The layer is internal only. It produces no sensor and no attribute of its own.

This refactor is a prerequisite for the remaining subsections and is expected to land first.

### 8.3 Device identity (implemented)

Keep amd64 device identity aligned with the existing aarch64 API contract.

- Populate the existing `device.model` field from `/sys/class/dmi/id/product_name` when the device-tree model is unavailable.
- Fall back to `Unknown System` when the DMI product name is unavailable.
- Do not add DMI-specific device attributes. `system_vendor`, `board_name`, `chassis_type`, serial numbers, UUIDs, and asset tags remain internal or unread.
- Preserve the existing `device` object shape: `model`, `operating_system`, `kernel_version`, and `architecture`.

### 8.4 CPU temperature (implemented; existing `cpu.temperature_c` surface unchanged)

Extend CPU-temperature source selection so the existing `cpu.temperature_c` value resolves on amd64:

- Accept the `x86_pkg_temp` thermal zone in addition to `cpu-thermal`.
- Accept the `coretemp` `hwmon` provider using the `Package id 0` label (Intel) and the `k10temp` provider using the `Tctl`/`Tccd` labels (AMD), selected by driver name and validated label.
- Do not expose per-core temperatures. They remain internal, consistent with "one value, one meaning."

No new sensor is created. Only the internal selection widens.

### 8.5 Cooling (implemented; existing `cooling` state preserved)

amd64 cooling can expose multiple exact `fanN_input` readings instead of the Raspberry Pi single-fan source. The existing cooling sensor contract remains authoritative.

- Keep `cooling.fan_speed_rpm` as the core numeric state with unit RPM.
- On amd64, calculate `fan_speed_rpm` as the rounded arithmetic mean of valid active fan readings greater than `0 RPM`.
- Keep `cooling.state` as `active`, `idle`, or `unavailable`.
- Add optional typed attributes `fan_count` and `active_fan_count` on amd64.
- `fan_count` is the number of valid exact `fanN_input` readings, including valid zero-RPM readings.
- `active_fan_count` is the number of valid exact `fanN_input` readings greater than zero.
- Report `idle` with `fan_speed_rpm=0` when valid fan inputs exist but all report zero.
- Report `unavailable` when no valid exact `fanN_input` reading exists.
- Do not expose individual RPM values, a selected fan RPM, PWM telemetry, or inferred fan roles.
- Count only exact `fanN_input` and exact `pwmN` files. Never write PWM values.
- Logical ACPI thermal cooling devices alone do not qualify as useful cooling telemetry.
- Preserve the existing Raspberry Pi cooling behavior unchanged.

The verified desktop evidence contains six valid fan inputs, five active fans, one zero-RPM fan, and five exact PWM channels. Its expected amd64 cooling result is `fan_speed_rpm=836`, `fan_count=6`, `active_fan_count=5`, and `state=active`.

### 8.6 Power (implemented; existing `power.value_w` state preserved)

amd64 has a genuine measured-power path through RAPL powercap energy counters, which the power probe fixture marks as the recommended source. This is the amd64 analogue of the Raspberry Pi `internal_rails` method and must be classified as honestly.

- Use a separate root-only, networkless collector to sample the package `energy_uj` counter twice and divide the wrap-safe energy delta by elapsed time.
- Write only a strict, sanitized, atomic cache containing schema version, generation time, package watts, source, and domain. The unprivileged API validates freshness and schema before using it.
- Extend `power.source` with a new measured value, `rapl_package`, and update the typed model and design accordingly. Selection order on amd64 becomes RAPL package energy delta, then a calibrated `cpu_estimate` only if a profile or override exists, then `unavailable`.
- amd64 hosts have no built-in power profile, so `cpu_estimate` applies only when `idle_power_override_w` and `full_load_power_override_w` are configured. Absent both, an amd64 host with RAPL reports `rapl_package`, and one without reports `unavailable`.
- Carry a caveat mirroring the PMIC caveat in section 13.2: the package domain is not full board or wall power, and CPU/SoC power limits and TDP values are never reported as live power. This matches the fixture note that power limits and TDP are not live measurements.
- A `power.domain` attribute (for example `package`) may be added to the existing `power` object to make the measured scope explicit.

External input-power sensing remains explicitly out of the roadmap, unchanged from the exclusions above.

### 8.7 Firmware health (implemented for initial amd64 support)

The `health` object is currently derived entirely from Raspberry Pi firmware throttling bits, for which amd64 has no direct equivalent.

- Phase 1: on amd64, `health.status` and its sub-fields report `unavailable`. This is the honest default and must not be filled with invented conditions. Health reporting `unavailable` on a supported platform is treated as an expected platform capability gap, not a probe failure (see 8.8).
- Phase 2 (optional, only if a clear definition is agreed): derive a defined amd64 health from trustworthy signals, such as `thermal_state` from proximity to the `coretemp`/`k10temp` critical trip and `performance_state` from an active RAPL constraint. Any such mapping is added as defined fields with documented thresholds, never as heuristic guesses, and reuses the existing `health` states.

### 8.8 Scheduling and failure isolation (implemented)

Ensure platform capability gaps do not degrade daemon health:

- Distinguish "unsupported on this platform" from "expected probe failed." A source that is legitimately absent on amd64 (Pi firmware health, PMIC rails, or a missing RAPL cache on hardware without readable package counters) reports `unavailable` without incrementing probe-failure accounting or moving `/health` to `degraded`. An existing but stale, malformed, or unreadable RAPL cache is treated as a real collector failure.
- Removing the unconditional `vcgencmd` calls on amd64 eliminates the per-cycle power-probe failures the current code would record on that platform.
- Preserve failure isolation, last-known-good retention, and the stateless design unchanged. The RAPL cache is runtime-only under `/run`, and no new runtime dependency is introduced.

### 8.9 Testing and acceptance (implemented; physical release validation pending)

Add regression coverage driven by the fixtures in 8.1:

- Device identity resolves only the existing `device.model` field from DMI; no vendor, board, chassis, serial, UUID, or asset-tag fields are exposed.
- CPU temperature resolves from `coretemp`/`x86_pkg_temp` and from `k10temp` labels.
- Cooling preserves `fan_speed_rpm` as the core state, averages valid active exact `fanN_input` readings, exposes only `fan_count` and `active_fan_count` as optional attributes, and correctly handles zero or unavailable inputs.
- Power resolves to `rapl_package` from an energy-counter delta, falls back correctly, and never reports TDP or a power limit as live power.
- Health reports `unavailable` on amd64 in phase 1 without degrading daemon health.
- Privacy scrub holds: no hostnames, addresses, serials, UUIDs, WWNs, or device paths in any amd64-derived field.
- The approved sensor and entity list in sections 1 through 3 is unchanged, and `/status` and `/health` still validate under `extra="forbid"` with the added attributes present in the typed models.

Implementation acceptance now includes direct fixture-driven regression tests for exact x86 counts, package-temperature selection, desktop multi-fan cooling, privacy scrubbing, RAPL calculation and cache validation, API-model strictness, amd64 health behavior, and the unchanged Raspberry Pi regression suite.

The remaining acceptance work is deployment validation on physical amd64 hardware. Software tests alone do not prove service permissions, kernel driver availability, sysfs visibility, or systemd behavior on a target machine.

### 8.10 Explicitly outside amd64 support (initial)

- GPU, iGPU, and discrete-accelerator power or temperature
- Per-core CPU temperature sensors
- Multi-socket aggregation beyond a single package-domain power sum
- Laptop battery and AC-adapter reporting
- Any fan, PWM, or power-limit control
- Non-Linux hosts
