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

Run the daemon under the dedicated `monitor-suite` service account. Grant only the device access needed by `smartctl` and Raspberry Pi firmware tools. Do not run the web service as root solely for convenience.

The installer and `deploy/monitor-suite-agent.service` provide the baseline. Device access and systemd restrictions must still be verified on the real Raspberry Pi.

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
