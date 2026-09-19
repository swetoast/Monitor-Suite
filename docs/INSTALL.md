# Installation

Monitor Suite Agent runs directly on the Raspberry Pi and is reached by Home Assistant over the trusted LAN. A reverse proxy is not required.

## One-command installation

Run this on the Raspberry Pi:

```bash
curl -fsSL https://raw.githubusercontent.com/swetoast/Monitor-Suite/main/install.sh | sudo sh
```

The installer:

- installs missing Debian or Raspberry Pi OS packages with `apt-get`
- downloads the current `main` branch from GitHub
- installs a hardened root systemd service for consistent SMART, NVMe, RAID, and Raspberry Pi hardware access
- creates an isolated Python virtual environment
- installs the locked Python dependencies
- generates a random 256-bit API token
- writes a protected configuration file
- installs and starts the systemd service
- prints the status URL, health URL, and new API token

Save the displayed token in Home Assistant. It is required in the `X-API-Key` request header.

Because this command executes a downloaded script as root, review `install.sh` in the repository first if you do not trust the source or network path. To inspect before running:

```bash
curl -fsSL https://raw.githubusercontent.com/swetoast/Monitor-Suite/main/install.sh -o install.sh
less install.sh
sudo sh install.sh install
```

## Requirements

The default installer supports Debian-family systems with systemd, including Raspberry Pi OS. When needed, it installs:

- Git
- Python 3
- Python virtual-environment support
- pip
- smartmontools

On another distribution, install the missing requirements with that distribution's package manager and run the installer again.

## Generated configuration

The installer creates:

```text
/etc/monitor-suite-agent.env
```

with permissions restricted to root. New installations use:

```text
MONITOR_SUITE_HOST=0.0.0.0
MONITOR_SUITE_PORT=5000
MONITOR_SUITE_API_KEY=<generated-api-token>
MONITOR_SUITE_ENABLE_DOCS=false
```

Reinstalling or updating preserves this file and its API token.

## Show the current API token

```bash
sudo /opt/monitor-suite-agent/install.sh token
```

Only run this in a private terminal. The command prints the token to standard output.

## Rotate the API token

```bash
sudo /opt/monitor-suite-agent/install.sh rotate-token
```

The command replaces the token atomically, restarts the service, and prints the new token. Update Home Assistant immediately because the previous token stops working.

## Update

```bash
sudo /opt/monitor-suite-agent/install.sh update
```

The update fetches the configured branch, reinstalls the locked environment and application, preserves configuration, and restarts the service.

## Status

```bash
sudo /opt/monitor-suite-agent/install.sh status
```

## Uninstall

```bash
sudo /opt/monitor-suite-agent/install.sh uninstall
```

Uninstall removes the service and application directory. It intentionally preserves `/etc/monitor-suite-agent.env`, including the API token, so a later reinstall can reuse the configuration. Delete that file manually only when the configuration is no longer needed.

## Custom installation directory

Environment overrides must be passed to the root shell when using the one-command installer:

```bash
curl -fsSL https://raw.githubusercontent.com/swetoast/Monitor-Suite/main/install.sh \
  | sudo env MONITOR_SUITE_INSTALL_DIR=/srv/monitor-suite-agent sh
```

The installed management commands then use that directory:

```bash
sudo /srv/monitor-suite-agent/install.sh update
sudo /srv/monitor-suite-agent/install.sh token
```

Available overrides:

```text
MONITOR_SUITE_REPO_URL
MONITOR_SUITE_BRANCH
MONITOR_SUITE_INSTALL_DIR
MONITOR_SUITE_CONFIG_FILE
MONITOR_SUITE_SERVICE_USER
```

## Private Git repository

The installer uses Git authentication available to the root environment. Override the repository URL when required:

```bash
sudo env MONITOR_SUITE_REPO_URL=git@github.com:swetoast/Monitor-Suite.git \
  /path/to/install.sh install
```

## Home Assistant connection

Use the URL printed by the installer, or configure:

```text
http://<raspberry-pi-address>:5000
```

Send the generated token in every request:

```text
X-API-Key: <api-token>
```

Restrict TCP port 5000 so only `<homeassistant-server>` at `<nas-ip-address>` can reach it. Plain HTTP is intended only for the explicitly trusted private LAN.


The installer preserves the existing API token during updates.

Before reporting a successful installation, the installer now verifies the local authenticated `/health` endpoint. It requires HTTP 200 without redirects, the exact Monitor Suite Agent health response contract, and a version matching the installed package. A service that exits after briefly becoming active, an occupied port, an authentication failure, invalid JSON, an unrelated response, or a version mismatch prevents the success message and prints concise service diagnostics without printing the API token.
