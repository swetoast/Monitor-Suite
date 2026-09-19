# Home Assistant entity model

This document defines the approved Home Assistant entity surface for Monitor Suite Agent. The daemon API may retain additional source values for calculations and diagnostics, but the integration must not automatically expose every API field.

## Principles

- Every entity must provide independent user value.
- Graphable measurements remain separate sensors.
- Attributes are used only when they directly explain the entity state.
- Static device information belongs in the device registry, not in sensors.
- Internal inputs, raw counters, and diagnostic data remain internal.
- A temporarily failed collection makes an existing entity unavailable; it must not make the entity disappear.

## Device registry information

Use the following as device information where supported:

- Model
- Operating system
- Kernel version
- Architecture

Do not create sensors for these values.

## Core sensors

### Overall status

Entity: `sensor.monitor_suite_status`

States:

- `Healthy`
- `Warning`
- `Critical`
- `Unavailable`

Approved attributes:

- `power_supply`
- `thermal_state`
- `performance_state`

Do not add raw throttling flags, issue lists, temperatures, voltage, power, or debug data to this sensor.

### CPU usage

Entity: `sensor.monitor_suite_cpu_usage`

- Unit: `%`
- State class: `measurement`
- No attributes

### CPU frequency

Entity: `sensor.monitor_suite_cpu_frequency`

- Unit: `MHz`
- Device class: `frequency`
- State class: `measurement`
- No attributes

### CPU temperature

Entity: `sensor.monitor_suite_cpu_temperature`

- Unit: `°C`
- Device class: `temperature`
- State class: `measurement`
- No attributes

### Memory usage

Entity: `sensor.monitor_suite_memory_usage`

- Unit: `%`
- State class: `measurement`
- No attributes

Do not expose available or total memory as entities or attributes.

### Storage usage

Entity: `sensor.monitor_suite_storage_usage`

- Unit: `%`
- State class: `measurement`
- No attributes

Do not expose available or total filesystem capacity as entities or attributes.

### Power

Entity: `sensor.monitor_suite_power`

- Unit: `W`
- Device class: `power`
- State class: `measurement`
- Approved attribute: `source`

The source attribute is required because internal-rail power and CPU-estimated power have different limitations.

### Input voltage

Entity: `sensor.monitor_suite_input_voltage`

- Unit: `V`
- Device class: `voltage`
- State class: `measurement`
- No attributes

### Fan speed

Entity: `sensor.monitor_suite_fan_speed`

- Unit: `rpm`
- State class: `measurement`
- No attributes

Do not create a separate cooling-state entity. Zero RPM represents idle, a positive value represents active cooling, and unavailable data uses entity availability.

### Network download

Entity: `sensor.monitor_suite_network_download`

- Unit: `B/s`
- Device class: `data_rate`
- State class: `measurement`
- No attributes

### Network upload

Entity: `sensor.monitor_suite_network_upload`

- Unit: `B/s`
- Device class: `data_rate`
- State class: `measurement`
- No attributes

Do not create entities for interface name, link status, or negotiated link speed.

### Disk read

Entity: `sensor.monitor_suite_disk_read`

- Unit: `B/s`
- Device class: `data_rate`
- State class: `measurement`
- No attributes

### Disk write

Entity: `sensor.monitor_suite_disk_write`

- Unit: `B/s`
- Device class: `data_rate`
- State class: `measurement`
- No attributes

### Last boot

Entity: `sensor.monitor_suite_last_boot`

- Device class: `timestamp`
- No attributes

Do not create a second uptime sensor from the same source value.

## RAID sensors

Create one status sensor per detected array, for example `sensor.monitor_suite_md0_status`.

States:

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
- `smart_status`
- `progress`, only while an operation is active

## SMART sensors

For each supported physical disk, expose only:

1. SMART status
2. Temperature, when available
3. Remaining life, when reliably reported

The SMART status sensor has no attributes. Do not expose raw SMART values, identifiers, history, lifetime counters, or command results.

## Excluded entities

Do not create sensors for:

- Memory available or total
- Filesystem available or total
- Cooling state
- Network interface
- Network link state
- Network link speed
- Uptime in addition to last boot
- Device model, operating system, kernel, or architecture
- SMART model, firmware, serial number, WWN, power-on hours, power cycles, unsafe shutdowns, load cycles, raw attributes, or self-test history
