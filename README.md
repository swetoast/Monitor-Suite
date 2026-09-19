# Monitor Suite Agent

Monitor Suite Agent is a small FastAPI daemon that samples meaningful Raspberry Pi and Linux telemetry in the background and serves one cached status response through Uvicorn.

## Requirements

- Python 3.11 or later
- Raspberry Pi OS or another Linux distribution on Raspberry Pi
- `vcgencmd` for Raspberry Pi firmware health and PMIC readings

The current target is Raspberry Pi 5 Model B on Debian 13 with Python 3.13.5.

## Install

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install .
```

## Run

```bash
MONITOR_SUITE_HOST=0.0.0.0 python -m monitor_suite_agent
```

The default port is `5000`.

```text
GET /status
GET /health
```

Run one Uvicorn worker. Each worker would otherwise own a separate sampler and counter history.

## Status data

`/status` contains CPU, memory, root-filesystem, classified power, input voltage, cooling, physical-network, root-disk, boot-time, and concise current-health information. Raw PMIC rails, raw throttling flags, virtual interfaces, attached-disk inventories, and low-value Linux counters remain internal.

Power source values:

- `internal_rails`: sum of matched PMIC output-rail voltage and current pairs
- `cpu_estimate`: calibrated CPU-load fallback estimate
- `unavailable`: no supported source produced a value

`internal_rails` is not complete USB-C input power.

## Configuration

```text
MONITOR_SUITE_HOST=127.0.0.1
MONITOR_SUITE_API_KEY=
MONITOR_SUITE_ENABLE_DOCS=false
MONITOR_SUITE_TRUSTED_PROXIES=
MONITOR_SUITE_LIMIT_CONCURRENCY=32
MONITOR_SUITE_BACKLOG=64
MONITOR_SUITE_KEEP_ALIVE=5
MONITOR_SUITE_PORT=5000
MONITOR_SUITE_SAMPLE_INTERVAL=1
MONITOR_SUITE_THERMAL_INTERVAL=2
MONITOR_SUITE_POWER_INTERVAL=5
MONITOR_SUITE_SLOW_SAMPLE_INTERVAL=30
MONITOR_SUITE_COMMAND_TIMEOUT=2
MONITOR_SUITE_STALE_AFTER=5
MONITOR_SUITE_IDLE_W=
MONITOR_SUITE_FULL_LOAD_W=
MONITOR_SUITE_NETWORK_INTERFACE=
MONITOR_SUITE_RAID_IDLE_INTERVAL=30
MONITOR_SUITE_RAID_ACTIVE_INTERVAL=2
MONITOR_SUITE_SMART_INTERVAL=900
MONITOR_SUITE_SMART_RETRY_INTERVAL=60
```

The two calibration values must be supplied together. Measure them externally for the actual board and attached hardware.

## Tests

```bash
python -m pytest
```

The regression suite contains fixtures derived from both supplied Raspberry Pi 5 probes.

## Design

See `docs/DESIGN.md` for the API contract, calculations, source-selection rules, security boundaries, and acceptance criteria.

## Storage health

The cached `/status` response includes compact RAID and SMART sections. RAID data contains only array state and counts needed to understand current health. SMART data contains only per-disk status, temperature when available, and remaining life when the device reports a trustworthy endurance value.

`smartctl` is provided by the `smartmontools` package. If it is unavailable, SMART devices are omitted without affecting the rest of `/status`. Linux MD RAID state is read directly from sysfs and does not require `mdadm`.

The approved Home Assistant entity surface is documented in `docs/HOME_ASSISTANT_ENTITY_MODEL.md`.

## Probe scheduling

The daemon uses independent monotonic deadlines so inexpensive, fast-changing counters can update quickly without repeatedly running slower or more intrusive probes.

- Every 1 second: CPU usage and frequency, network throughput, and root-disk throughput.
- Every 2 seconds: CPU temperature and fan speed.
- Every 5 seconds: PMIC power, input voltage, and current firmware power, thermal, and throttling state.
- Every 30 seconds: memory usage, root-filesystem usage, network metadata, and boot time.
- RAID every 30 seconds while idle, automatically increasing to every 2 seconds during recovery, resync, checking, or reshape.
- SMART every 15 minutes while available, with a 60-second retry only after a previously supported disk becomes unavailable.

SMART uses `smartctl -n standby` and retains the last known values when a disk is sleeping, so monitoring does not wake an idle disk. All intervals are validated as positive values at startup.

## Persistence

The daemon is intentionally stateless and does not use SQLite or store time-series measurements. It retains only current runtime caches needed to calculate rates and serve the current snapshot. Home Assistant owns long-term history.

## Network security

Loopback remains the code default. The GitHub installer configures direct trusted-LAN access and generates a required API key of at least 32 characters. Clients send it in the `X-API-Key` header. Interactive documentation is disabled by default and Uvicorn has bounded concurrency and keep-alive defaults. See `docs/INSTALL.md` and `docs/SECURITY.md`.

## Install from GitHub

Run one command on the Raspberry Pi:

```bash
curl -fsSL https://raw.githubusercontent.com/swetoast/Monitor-Suite/main/install.sh | sudo sh
```

The installer installs missing Raspberry Pi OS or Debian packages, downloads the project, generates a protected API token, enables the systemd service, and prints the connection details. Existing configuration and tokens are preserved during updates.

Common management commands:

```bash
sudo /opt/monitor-suite-agent/install.sh update
sudo /opt/monitor-suite-agent/install.sh status
sudo /opt/monitor-suite-agent/install.sh token
sudo /opt/monitor-suite-agent/install.sh rotate-token
sudo /opt/monitor-suite-agent/install.sh uninstall
```

Review the full installation and customization guide in `docs/INSTALL.md` before using the command on an untrusted network.

## Daemon health

`GET /health` returns only the daemon status, version, and whether a complete sample exists. Status precedence is `starting`, `stale`, `degraded`, and `ok`. One isolated probe failure retains the last good value; two consecutive failures from any expected probe group degrade the daemon until that group recovers.

## Transition logging

The daemon keeps normal polling quiet. It logs only meaningful state changes, including RAID degradation and recovery, probe availability and recovery, current undervoltage and thermal limiting, selected network interface, root backing device, and cooling hardware. Initial baselines and unchanged cycles are not logged.
