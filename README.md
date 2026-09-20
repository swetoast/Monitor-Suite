# Monitor Suite Agent

Monitor Suite Agent is a lightweight Linux monitoring server for Raspberry Pi aarch64 and supported amd64 systems. It collects system, thermal, power, cooling, network, filesystem, Linux software RAID, and SMART data in the background and exposes one stable authenticated HTTP API.

The server is designed for unattended operation on a trusted LAN. It schedules each probe according to its cost, keeps the latest coherent snapshot in memory, preserves last-known-good values through isolated read failures, and reports unsupported data as unavailable instead of inventing values.

## Highlights

- Adaptive RAID polling that increases refresh frequency during recovery, resync, check, and reshape operations
- Standby-aware SMART collection that retains last-known values instead of intentionally waking supported sleeping disks
- Failure isolation per probe group, so a temporary SMART or RAID error does not discard unrelated system telemetry
- Last-known-good retention with explicit freshness and consecutive-failure accounting
- Raspberry Pi firmware decoding for current undervoltage, thermal limiting, and performance limiting
- amd64 package temperature, multi-fan cooling summaries, DMI model detection, and privileged RAPL package-power collection where supported
- Power values labelled by measurement source and confidence, without presenting internal rails as total input power
- Physical-device and physical-interface filtering that excludes virtual network noise and unrelated attached storage
- Cached, internally consistent snapshots served without executing hardware probes during API requests

## Table of contents

- [What it monitors](#what-it-monitors)
- [Server capabilities](#server-capabilities)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Using the API](#using-the-api)
- [Managing the service](#managing-the-service)
- [Understanding health states](#understanding-health-states)
- [Storage monitoring](#storage-monitoring)
- [Power monitoring](#power-monitoring)
- [Limitations](#limitations)
- [Security](#security)
- [Documentation](#documentation)
- [Support and feedback](#support-and-feedback)
- [Project information](#project-information)

## What it monitors

| Area | Information provided |
| --- | --- |
| Overall health | Whether the agent is starting, operating normally, degraded, or returning stale data |
| Processor | CPU use, load, frequency, temperature, and throttling conditions |
| Memory | Current memory use and availability |
| System | Uptime, boot time, operating system, kernel, architecture, and hardware model |
| Root storage | Filesystem use and the physical device backing the root filesystem |
| Network | Current physical interface, link information, and transfer rates |
| Cooling | Active-cooling availability and current state when supported |
| Power conditions | Current undervoltage and firmware-reported power or performance limits |
| RAID | Array state, RAID level, member health, recovery progress, speed, and estimated completion time |
| SMART | Useful health, temperature, error, and lifetime values exposed by supported devices |
| Power use | Internal-rail measurement or a calibrated CPU-load estimate, including source and confidence |

Monitor Suite Agent reports only values it can obtain and interpret. Unsupported values are returned as unavailable rather than estimated without evidence.

## Server capabilities

### Independent probe scheduling

CPU, thermal, power, resource, RAID, and SMART data do not share one polling interval. Fast values can stay responsive without forcing expensive storage checks to run at the same rate.

### Coherent cached responses

Collection happens in the background. API requests read a completed snapshot rather than launching commands and assembling partially updated data during the request.

### Degraded operation

Each probe group tracks availability, consecutive failures, and its last successful update. A failed optional source does not take down the server or erase healthy data from other probe groups.

### Storage-aware monitoring

RAID activity changes its own polling schedule. SMART checks use standby-aware operation, bounded retry delays, and parsed health evidence rather than treating every nonzero command exit as disk failure.

### Conservative telemetry

The server filters virtual interfaces, avoids publishing raw identifiers, distinguishes measured power from estimated power, and returns unavailable values when the host cannot provide reliable evidence.

## How it works

Monitor Suite Agent runs as an unprivileged systemd service. It reads Linux system interfaces and, on Raspberry Pi, the existing firmware sources locally, keeps the latest results in memory, and serves a consistent snapshot over HTTP.

```text
Linux hardware and operating system
             |
             v
     Monitor Suite Agent
             |
       authenticated API
             |
             v
     API consumer
```

This design means:

- API consumers do not need SSH or shell access to the monitored system.
- API requests return cached data instead of executing every probe on demand.
- Fast-changing values refresh frequently while slower checks run less often.
- RAID polling accelerates automatically during recovery, resync, check, or reshape.
- SMART polling uses standby-aware behavior and does not intentionally wake a sleeping supported disk.
- External consumers remain responsible for history, retention, dashboards, and alerting.

## Requirements

### Supported environment

- Raspberry Pi 5 remains the primary release-tested target. amd64 support is fixture-tested and requires final validation on physical target installations.
- A supported Linux distribution with systemd and Python 3.11 or newer is required.
- systemd must be available.
- The installing account must have `sudo` access.
- The monitored system needs internet access to GitHub and Python package sources during installation.
- API consumers must be able to reach the monitored system over a trusted local network.

The installer adds missing Debian packages when needed, including Git, Python 3, Python virtual-environment support, pip, and `smartmontools`.

### Hardware-dependent features

Some data depends on the architecture, hardware model, operating system, kernel, storage device, enclosure, USB bridge, permissions, and available kernel interfaces. Missing support does not prevent unrelated telemetry from operating.

## Installation

Run this command on the monitored Linux system:

```bash
curl -fsSL https://raw.githubusercontent.com/swetoast/Monitor-Suite/main/install.sh | sudo sh
```

The installer will:

1. Check and install required Debian packages.
2. Download Monitor Suite Agent from GitHub.
3. Install an unprivileged API service plus a short-lived privileged SMART collector.
4. Create an isolated Python environment.
5. Generate a random API token.
6. Install and start the systemd service.
7. Confirm that the service becomes active.
8. Print the status URL, health URL, and API token.

Save the displayed token. Every API request must include it in the `X-API-Key` header.

### Inspect before installing

The one-command installer downloads and executes a script with root privileges. If you prefer to inspect it first:

```bash
curl -fsSL https://raw.githubusercontent.com/swetoast/Monitor-Suite/main/install.sh -o install.sh
less install.sh
sudo sh install.sh install
```

For custom installation paths, private repositories, package details, and uninstall behavior, see the [installation guide](docs/INSTALL.md).

## Using the API

The installer prints the detected address. The default base URL is:

```text
http://<raspberry-pi-address>:5000
```

### Check agent availability

```bash
curl -H "X-API-Key: <api-token>" \
  http://<raspberry-pi-address>:5000/health
```

`/health` returns the agent version, current daemon health state, and whether a complete sample is available.

### Read the full status

```bash
curl -H "X-API-Key: <api-token>" \
  http://<raspberry-pi-address>:5000/status
```

`/status` returns the complete current monitoring snapshot. A client can poll this endpoint and use the response for monitoring, history, alerts, or automation.

### API endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Small availability and freshness check |
| `GET /status` | Complete current monitoring snapshot |

Interactive API documentation is disabled by default for the supported LAN deployment.

## Managing the service

### Check status

```bash
sudo /opt/monitor-suite-agent/install.sh status
```

### Update

```bash
sudo /opt/monitor-suite-agent/install.sh update
```

Updates preserve the existing configuration and API token.

### Show the API token

```bash
sudo /opt/monitor-suite-agent/install.sh token
```

Run this only in a private terminal because it prints the current token.

### Rotate the API token

```bash
sudo /opt/monitor-suite-agent/install.sh rotate-token
```

Rotation restarts the service. Update every client immediately because the previous token stops working.

### Uninstall

```bash
sudo /opt/monitor-suite-agent/install.sh uninstall
```

Uninstall removes the service and application but preserves `/etc/monitor-suite-agent.env`. Remove that file manually only when the stored configuration is no longer needed.

## Understanding health states

| State | Meaning |
| --- | --- |
| `starting` | The first complete monitoring sample is not available yet |
| `ok` | Expected probe groups are current and no firmware health condition is active |
| `degraded` | An expected probe group has repeatedly failed or a current firmware health condition is active |
| `stale` | The last complete sample is older than the configured freshness limit |

A single isolated probe failure retains the last good value. Persistent failures degrade the service until the affected probe group recovers. This avoids unnecessary state changes from one temporary read error while still exposing continuing problems.

## Storage monitoring

### RAID

Linux software RAID monitoring includes:

- array state and RAID level
- expected and active member count
- member health
- degraded-device count
- recovery, resync, check, or reshape activity
- progress, speed, and estimated completion time when available

RAID is normally checked every 30 seconds. During active array work, polling increases to every 2 seconds so progress remains useful.

### SMART

SMART monitoring exposes useful health and lifetime information provided by supported devices. A nonzero `smartctl` exit status alone is not treated as proof that a disk has failed because unsupported log operations can also produce nonzero results.

A root-only, networkless collector checks SMART every 15 minutes and writes a sanitized runtime cache for the unprivileged API service. Standby-aware polling retains the last known values for a sleeping disk rather than intentionally waking it. NVMe composite temperatures are read separately from `hwmon` by the API service. Actual support depends on the disk, enclosure, USB bridge, kernel driver, and `smartctl` support.

## Power monitoring

Every reported power value identifies how it was obtained:

| Source | Meaning |
| --- | --- |
| `internal_rails` | Calculated from matched internal PMIC voltage and current readings |
| `cpu_estimate` | Fallback estimate based on CPU load and optional idle and full-load calibration |
| `unavailable` | No supported source produced a value |

Internal-rail power is not complete USB-C input power and must not be treated as wall-socket consumption. Optional idle and full-load calibration values must be configured together before the CPU estimate can use them.

## Limitations

Monitor Suite Agent:

- does not control the host, disks, RAID arrays, fans, power limits, or power supply
- does not repair storage problems or modify RAID configuration
- does not replace backups, native RAID tools, or manufacturer diagnostics
- does not expose every raw Linux counter or every SMART field
- does not provide complete USB-C input or wall-socket power measurement
- does not store time-series history
- does not provide dashboards, time-series storage, notifications, or client-specific entities
- does not require a reverse proxy for its supported deployment

## Security

The intended deployment is direct access over a trusted LAN:

```text
API consumer -> monitored Linux system:5000
```

The installer binds the service to the LAN, generates a protected API token, and disables interactive API documentation by default. Restrict TCP port 5000 so only approved LAN clients can connect.

Do not:

- expose the service directly to the internet
- commit `/etc/monitor-suite-agent.env`
- include the API token in screenshots or issue reports
- publish unreviewed hardware probe captures
- publish hostnames, addresses, serial numbers, WWNs, RAID UUIDs, or identifying storage model names

See the [security guide](docs/SECURITY.md) for the complete deployment model.

## Documentation

- [Installation and management](docs/INSTALL.md)
- [Security model](docs/SECURITY.md)
- [Technical design](docs/DESIGN.md)
- [Roadmap](docs/ROADMAP.md)
- [Release history](CHANGELOG.md)

## Support and feedback

Use the repository's Issues section to report bugs, request improvements, or describe unsupported Raspberry Pi and storage configurations.

Include:

- Raspberry Pi model
- operating-system version
- Monitor Suite Agent version
- output from `sudo systemctl status monitor-suite-agent.service`
- relevant service logs after removing private or identifying information

Never include the API token or the contents of `/etc/monitor-suite-agent.env`.

## Project information

Monitor Suite Agent is maintained as a Raspberry Pi monitoring-server project. The repository documentation describes the supported installation, security model, data contract, and technical design. Home Assistant is one possible future consumer of the server API, not the focus of the server itself.

No distribution license is currently declared in this repository. Copyright is not a substitute for a software license, so users should not assume permission to redistribute or modify the project until a license is added.

Last updated: September 19, 2026.

Copyright (c) 2026 Toast
