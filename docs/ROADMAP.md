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
