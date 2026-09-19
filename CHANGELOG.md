# Changelog

## 2.4.4

- Recorded installer API readiness verification as the remaining daemon roadmap item.
- Documented the live false-success case caused by a competing process already owning the configured port.
- Defined acceptance checks for authenticated health validation, response identity, version matching, diagnostics, and regression coverage.

## 2.4.3

- Fixed installation from the repository by explicitly limiting setuptools packaging to `monitor_suite_agent`.
- Prevented the top-level `deploy` directory from being treated as a second Python package.
- Added regression tests that build a wheel and verify that only the intended Python package is included.

## 2.4.2

- Refocused the README on Monitor Suite Agent as standalone Raspberry Pi server software.
- Replaced obvious promotional bullets with differentiated server behavior: adaptive scheduling, standby-aware SMART checks, failure isolation, freshness accounting, conservative telemetry, and coherent cached snapshots.
- Replaced the Home Assistant-led use-case section with concrete server capabilities.
- Reduced Home Assistant to a possible future API consumer rather than presenting it as the purpose of the server.

## 2.4.1

- Refined the README into a concise GitHub landing page with a descriptive title, highlights, navigation, requirements, installation, usage examples, limitations, support guidance, and project information.
- Added compact tables for monitored areas, API endpoints, health states, and power-source meanings.
- Added a text architecture diagram without introducing image assets.
- Clarified the current absence of a distribution license rather than implying usage rights.
- Kept the README free of emojis and developer setup instructions.

## 2.4.0

- Rewrote the README around the problems Monitor Suite Agent solves for Raspberry Pi and Home Assistant users.
- Added a clear summary of the monitoring, storage, power, health, and security value users receive.
- Moved implementation detail behind practical installation, connection, management, and troubleshooting guidance.
- Clarified that the agent is the Raspberry Pi-side data source and does not itself create Home Assistant entities.
- Clarified unsupported measurements, power limitations, SMART compatibility, and trusted-LAN expectations.
- Added README regression checks for the user-facing structure and exact copyright notice.

## 2.3.3

- Added the exact project copyright notice: `Copyright (c) 2026 Toast`.
- Added a regression test that rejects altered copyright wording.

## 2.3.2

- Fixed Git updates after the installation directory has been transferred to the dedicated service account by explicitly marking that checkout as safe for each root-run Git command.
- Hardened installer path and service-account validation to prevent malformed values from becoming systemd directives or shell arguments.
- Added regression tests for service-owned Git updates and systemd directive injection.
- Completed a full pre-deployment audit of the recovered release package.

## 2.3.1

- Replaced the captured Raspberry Pi hostname in the RAID and SMART evidence fixture with `test-host`.
- Replaced captured storage model names with generic USB HDD and NVMe SSD fixture names.
- Extended privacy regression tests to reject the removed hostname and hardware model identifiers.
- Kept device types, capacities, protocols, RAID layout, and SMART behavior intact for regression coverage.

## 2.3.0

- Added a one-command GitHub installation flow using `curl` and the existing POSIX shell installer.
- Added automatic dependency installation on Raspberry Pi OS and other Debian-family systems.
- Generate and display a random 256-bit API token during first installation.
- Added `token` and `rotate-token` management actions.
- Added a concise installation summary with detected status and health URLs.
- Added service startup verification and clearer failures.
- Preserve the existing configuration and token during reinstall and update.
- Improved custom installation-directory and private-repository instructions.

## 2.2.1

- Replaced the private NAS address in public documentation with `<nas-ip-address>`.
- Added `<homeassistant-server>` where the Home Assistant host is referenced in deployment instructions.
- Replaced the captured RAID UUID in the Raspberry Pi regression fixture with a deterministic synthetic UUID.
- Added privacy regression tests for personal names, private deployment addresses, email addresses, device identifiers, credentials, and user-specific home paths.
- Kept the public GitHub repository owner in installer URLs because it is required for installation.

## 2.2.0

- Completed transition-only logging for RAID degradation, failure, recovery activity, completion, disappearance, and return.
- Added concise availability and recovery messages for power, cooling, thermal, resources, fast telemetry, RAID, SMART, and complete snapshot collection.
- Added current undervoltage, thermal limiting, and performance-limiting transitions without logging historical firmware flags.
- Added transition logging for selected network interface, root backing device, and cooling hardware changes.
- Removed duplicate SMART availability logging.
- Kept initial baselines and unchanged collection cycles silent.
- Limited repeated collection exceptions to the first consecutive failure while retaining the later availability-transition message.
- Added focused regression tests that assert exact transition messages and verify unchanged states remain quiet.

## 2.1.0

- Completed daemon health accounting for startup, stale snapshots, and repeated failures from every expected probe group.
- Added whole-snapshot collection health so repeated unexpected collection exceptions degrade the daemon before the snapshot becomes stale.
- Kept startup available after an initial collection failure, allowing `/health` to report `starting` while background retries continue.
- Defined deterministic health precedence: `starting`, `stale`, `degraded`, then `ok`.
- Removed the SMART-specific shortcut from health classification; SMART now follows the same probe-group policy as the rest of the daemon.
- Renamed background tasks to match Monitor Suite Agent.
- Added regression tests for every expected probe group, transient failures, stale-state precedence, startup failure, whole-cycle failure, RAID-unavailable accounting, and recovery.

## 2.0.0

- Renamed the daemon to Monitor Suite Agent.
- Renamed the package, command, service, configuration prefix, release files, and documented Home Assistant entity prefix.
- Added internal health tracking for fast counters, thermal and cooling, power and firmware health, resources, RAID, and SMART.
- Added a two-failure availability threshold with last-good-value retention before values become unavailable.
- Made `/health` aggregate repeated failures from all expected probe groups.
- Added transition logging for probe availability, RAID state, power supply, thermal state, performance state, interface, root device, and cooling rediscovery.
- Added `install.sh` for install, update, status, and uninstall from the Monitor-Suite GitHub repository.
- The installer supports a user-selected installation directory, locked dependencies, preserved configuration, generated API keys, and a dedicated systemd service account.
- Reworked installation and security documentation around direct authenticated LAN access from the NAS without a reverse proxy.

## 1.7.0

- Added API-key authentication through the `X-API-Key` header using constant-time comparison.
- Require a key of at least 32 characters whenever the daemon binds beyond loopback.
- Disabled interactive API documentation and OpenAPI output by default.
- Disabled proxy-header processing unless explicit trusted proxy addresses or networks are configured; wildcard trust is rejected.
- Added Uvicorn concurrency, backlog, and keep-alive limits.
- Added a fixed production dependency lock file for the dependency set validated with this release.
- Added a hardened systemd service baseline and network-security deployment guidance for NAS access.
- Added security regression tests for remote binding, API keys, documentation exposure, and proxy trust.

## 1.6.0

- Added the approved daemon architecture-hardening plan to `docs/ROADMAP.md`.
- Moved SMART collection into an independent background task so slow disks cannot delay fast telemetry or the first lightweight snapshot.
- Added bounded SMART retry backoff at 60 seconds, 2 minutes, 5 minutes, and 15 minutes, returning to the normal interval after recovery.
- Added typed, extra-field-forbidding public response models for `/status` and `/health`.
- Added concise degraded daemon health after repeated failures from a previously expected SMART source.
- Added transition-based SMART logging and moved global logging configuration from application import to the executable entry point.
- Added conditional rediscovery when the selected network interface, root backing device, or cooling path disappears.
- Explicitly retained the stateless design and rejected SQLite and duplicate time-series storage in the roadmap.
- Added backoff, health, and public-model contract tests.

## 1.5.0

- Added independent monotonic schedules for fast counters, thermal and cooling data, power and firmware health, resources, RAID, and SMART.
- Kept CPU usage, CPU frequency, network rates, and disk rates on the one-second dynamic cycle.
- Moved CPU temperature and cooling to a two-second schedule.
- Moved PMIC power and Raspberry Pi throttling commands to a five-second schedule instead of executing them every second.
- Kept memory, root-filesystem, network metadata, and boot time on the 30-second resource schedule.
- Added adaptive RAID scheduling: 30 seconds while idle and two seconds during recovery, resync, checking, or reshape operations.
- Kept normal SMART health collection at 15 minutes and added a 60-second retry schedule only for previously supported disks that become unavailable.
- Preserved last known SMART values when a disk is deliberately left in standby.
- Preserved valid smartctl JSON even when smartctl uses nonzero health-status exit bits.
- Cached maximum CPU frequency at startup because it is static for the running hardware profile.
- Added schedule deadline, interval validation, standby, smartctl exit-status, and adaptive behavior tests.

## 1.4.1

- Separated SMART collection from general slow telemetry and set the default SMART interval to 15 minutes.
- Added `MONITOR_SUITE_SMART_INTERVAL` for validated SMART polling configuration.
- Added `smartctl -n standby` so monitoring does not wake sleeping disks.
- Preserved previously discovered SMART disks as unavailable after temporary collection failures instead of removing them.
- Ensured known SMART warnings and failures are not hidden by another unavailable member.
- Refined NVMe media-error handling so a historical nonzero counter produces warning rather than an automatic current failure.
- Prioritized active RAID recovery operations over the degraded state while preserving member counts.
- Made RAID active-member counts and redundancy states reflect degraded and failed arrays more accurately.
- Added the complete approved Home Assistant entity contract in `docs/HOME_ASSISTANT_ENTITY_MODEL.md`.

## 1.4.0

- Added Linux MD RAID health collection from sysfs with clean, degraded, failed, recovery, resync, check, reshape, and unavailable states.
- Added approved RAID fields only: level, active members, expected members, failed members, redundancy, member SMART summary, and operation progress when active.
- Added SMART collection for supported physical disks through `smartctl` JSON.
- Exposed only SMART status, temperature, and remaining life when the device reports a trustworthy endurance value.
- Kept raw SMART attributes, identifiers, histories, counters, and command output internal.
- Added RAID and SMART classification, filtering, progress, and failure-path tests.
- Retained the supplied Raspberry Pi 5 RAID and SMART probe as regression evidence.

## 1.3.2

- Preserved the supplied Raspberry Pi 5 RAID and SMART probe as regression evidence.
- Added a fixture-integrity test covering the verified clean RAID 0 array, member states, SMART results, and identifier redaction.
- Recorded the approved RAID sensor states and minimal attribute model in `docs/ROADMAP.md`.

## 1.3.1

- Added `docs/ROADMAP.md` with the two agreed remaining items: RAID health and the Home Assistant integration.
- Defined RAID-health discovery, privacy, validation, and acceptance requirements before implementation.
- Removed unrelated future considerations from the active roadmap.

## 1.3.0

- Added optional `MONITOR_SUITE_NETWORK_INTERFACE` selection and validation.
- Added regression tests for explicit interface selection.

## 1.2.0

- Implemented the design-document `/status` schema.
- Added memory, root-filesystem, cooling, physical-network, root-disk, and boot-time collection.
- Added semantic thermal, cooling, network, and block-device discovery instead of relying on unstable indexes.
- Added monotonic network and disk rate calculations with reset handling.
- Reduced health to current authoritative power, thermal, and performance states and removed the duplicate `issues` list.
- Added two Raspberry Pi 5 regression fixtures derived from the supplied power and system-statistics probes.
- Added full snapshot, failure-path, reset, filtering, parser, calculation, and API-contract tests.

## 1.1.0

- Replaced the broad telemetry payload with a compact, logically named `/status` response.
- Exposed only device model, CPU load, CPU frequency, CPU temperature, classified power, input voltage, and an actionable health summary.
- Kept individual PMIC rails internal instead of exposing a large diagnostic dump.
- Renamed the PMIC result as calculated internal-rail power and stopped presenting it as total input power.

## 1.0.1

- Replaced the duplicate `/telemetry` and `/power_usage` routes with one `/status` endpoint.
- Kept `/health` strictly for service availability and `/docs` for API documentation.

## 1.0.0

- Replaced Flask with FastAPI and Uvicorn.
- Replaced psutil CPU telemetry with `/proc/stat` and cpufreq sysfs.
- Replaced `vcgencmd measure_temp` with thermal sysfs.
- Removed shell-based `os.popen` calls and NVMe power assumptions.
- Added one lifecycle-managed asynchronous sampler and cached responses.
- Added PMIC rail parsing and explicit calculated, estimated, and unavailable classifications.
- Added decoded throttling flags, environment configuration, validation, tests, and compatibility endpoint.
