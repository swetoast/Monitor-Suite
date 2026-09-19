# Security

## Supported deployment

Monitor Suite Agent runs directly on the Raspberry Pi and is reached from the Home Assistant server over the trusted LAN. A reverse proxy is not part of the normal deployment.

A non-loopback bind requires an API key of at least 32 characters. The installer creates one automatically.

```text
MONITOR_SUITE_HOST=0.0.0.0
MONITOR_SUITE_PORT=5000
MONITOR_SUITE_API_KEY=<generated secret>
MONITOR_SUITE_ENABLE_DOCS=false
```

The Home Assistant server sends the key in every request:

```text
X-API-Key: <generated secret>
```

Store `/etc/monitor-suite-agent.env` with restricted permissions. Do not place the key in source code, URLs, entity attributes, diagnostics, logs, screenshots, or public documentation.

Plain HTTP does not encrypt traffic. This is an accepted tradeoff only for the explicitly trusted private LAN. Restrict TCP port 5000 on the Raspberry Pi so only the Home Assistant server at `<nas-ip-address>` can connect.

## API documentation

Interactive documentation and the OpenAPI schema are disabled by default. They can be enabled temporarily with:

```text
MONITOR_SUITE_ENABLE_DOCS=true
```

## Request limits

The server defaults to 32 concurrent connections, a backlog of 64, and a five-second keep-alive timeout.

## Least privilege

The network-facing Uvicorn API runs as the unprivileged `monitor-suite` account. It reads normal telemetry, Linux MD RAID state, Raspberry Pi firmware health, and NVMe temperatures available through sysfs and `hwmon`. A separate root-only oneshot service performs fixed-purpose SMART reads without opening a network listener, then writes a sanitized cache under `/run/monitor-suite-agent/`. Both units retain systemd hardening appropriate to their responsibilities. Keep the service on a trusted LAN and protect the API token.

The installer, `deploy/monitor-suite-agent.service`, `deploy/monitor-suite-smart.service`, and `deploy/monitor-suite-smart.timer` provide the baseline. Device access and systemd restrictions must still be verified on the real Raspberry Pi.

## Dependencies

`requirements.lock` records the exact dependency set validated for this release.

## API token management

A new installation generates a random 256-bit API token and stores it only in the protected environment file. The installer prints it once in the installation summary so it can be copied into Home Assistant. Updates preserve the existing token.

Show the current token only in a private terminal:

```bash
sudo /opt/monitor-suite-agent/install.sh token
```

Rotate a compromised token with:

```bash
sudo /opt/monitor-suite-agent/install.sh rotate-token
```

Rotation restarts the service immediately. Every client must then be updated with the new token.
