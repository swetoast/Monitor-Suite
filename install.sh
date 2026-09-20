#!/bin/sh
set -eu

REPO_URL=${MONITOR_SUITE_REPO_URL:-https://github.com/swetoast/Monitor-Suite.git}
BRANCH=${MONITOR_SUITE_BRANCH:-main}
INSTALL_DIR=${MONITOR_SUITE_INSTALL_DIR:-/opt/monitor-suite-agent}
CONFIG_FILE=${MONITOR_SUITE_CONFIG_FILE:-/etc/monitor-suite-agent.env}
SERVICE_FILE=/etc/systemd/system/monitor-suite-agent.service
SERVICE_NAME=monitor-suite-agent.service
SMART_SERVICE_NAME=monitor-suite-smart.service
SMART_TIMER_NAME=monitor-suite-smart.timer
POWER_SERVICE_NAME=monitor-suite-power.service
POWER_TIMER_NAME=monitor-suite-power.timer
SERVICE_USER=${MONITOR_SUITE_SERVICE_USER:-monitor-suite}
ACTION=${1:-install}
CREATED_TOKEN=

say() {
    printf '%s\n' "$*"
}

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

need_root() {
    [ "$(id -u)" -eq 0 ] || fail "Run with sudo or as root."
}

need_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

validate_paths() {
    case "$INSTALL_DIR" in
        /) fail "The installation directory cannot be /." ;;
        /*) ;;
        *) fail "MONITOR_SUITE_INSTALL_DIR must be an absolute path." ;;
    esac
    case "$CONFIG_FILE" in /*) ;; *) fail "MONITOR_SUITE_CONFIG_FILE must be an absolute path." ;; esac
    case "$INSTALL_DIR$CONFIG_FILE" in
        *[!A-Za-z0-9_./-]*) fail "Installation and configuration paths may use only letters, numbers, _, ., /, and -." ;;
    esac
    case "$BRANCH" in
        ""|-*) fail "MONITOR_SUITE_BRANCH must be a branch name and cannot begin with -." ;;
    esac
    case "$SERVICE_USER" in
        [A-Za-z_]* ) ;;
        *) fail "MONITOR_SUITE_SERVICE_USER must begin with a letter or underscore." ;;
    esac
    case "$SERVICE_USER" in
        *[!A-Za-z0-9_-]*) fail "MONITOR_SUITE_SERVICE_USER contains unsupported characters." ;;
    esac
}

git_install() {
    git -c "safe.directory=$INSTALL_DIR" "$@"
}

install_dependencies() {
    missing=
    for command in git python3 systemctl; do
        command -v "$command" >/dev/null 2>&1 || missing="$missing $command"
    done
    python3 -c 'import ensurepip, venv' >/dev/null 2>&1 || missing="$missing python3-venv"
    command -v smartctl >/dev/null 2>&1 || missing="$missing smartmontools"

    [ -z "$missing" ] && return
    if command -v apt-get >/dev/null 2>&1; then
        say "Installing required packages:$missing"
        export DEBIAN_FRONTEND=noninteractive
        apt-get update
        apt-get install -y git python3 python3-venv python3-pip smartmontools
    else
        fail "Install these requirements and run the installer again:$missing"
    fi
}

generate_token() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 32
    else
        python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
    fi
}

read_config_value() {
    key=$1
    [ -r "$CONFIG_FILE" ] || return 1
    sed -n "s/^${key}=//p" "$CONFIG_FILE" | tail -n 1
}

install_source() {
    if [ -d "$INSTALL_DIR/.git" ]; then
        say "Updating source in $INSTALL_DIR"
        git_install -C "$INSTALL_DIR" remote set-url origin "$REPO_URL"
        git_install -C "$INSTALL_DIR" fetch --prune origin "$BRANCH"
        git_install -C "$INSTALL_DIR" checkout -B "$BRANCH" "origin/$BRANCH"
    elif [ -e "$INSTALL_DIR" ]; then
        fail "Installation path exists but is not a Git checkout: $INSTALL_DIR"
    else
        say "Downloading Monitor Suite Agent"
        git clone --branch "$BRANCH" --single-branch "$REPO_URL" "$INSTALL_DIR"
    fi
    chown -R root:root "$INSTALL_DIR"
}

install_python() {
    say "Installing the locked Python environment"
    if [ ! -x "$INSTALL_DIR/.venv/bin/python" ]; then
        python3 -m venv "$INSTALL_DIR/.venv"
    fi
    "$INSTALL_DIR/.venv/bin/python" -m pip install --disable-pip-version-check --requirement "$INSTALL_DIR/requirements.lock"
    "$INSTALL_DIR/.venv/bin/python" -m pip install --disable-pip-version-check --no-deps --force-reinstall "$INSTALL_DIR"
}

create_config() {
    if [ -f "$CONFIG_FILE" ]; then
        chown root:"$SERVICE_USER" "$CONFIG_FILE"
        chmod 0640 "$CONFIG_FILE"
        say "Preserving existing configuration: $CONFIG_FILE"
        return
    fi
    CREATED_TOKEN=$(generate_token)
    umask 077
    cat > "$CONFIG_FILE" <<EOF
MONITOR_SUITE_HOST=0.0.0.0
MONITOR_SUITE_PORT=5000
MONITOR_SUITE_API_KEY=$CREATED_TOKEN
MONITOR_SUITE_ENABLE_DOCS=false
MONITOR_SUITE_LIMIT_CONCURRENCY=32
MONITOR_SUITE_BACKLOG=64
MONITOR_SUITE_KEEP_ALIVE=5
EOF
    chown root:"$SERVICE_USER" "$CONFIG_FILE"
    chmod 0640 "$CONFIG_FILE"
    say "Created protected configuration: $CONFIG_FILE"
}

create_service() {
    install -m 0644 "$INSTALL_DIR/deploy/monitor-suite-agent.service" "$SERVICE_FILE"
    sed -i "s|/opt/monitor-suite-agent|$INSTALL_DIR|g; s|/etc/monitor-suite-agent.env|$CONFIG_FILE|g; s|User=monitor-suite|User=$SERVICE_USER|g; s|Group=monitor-suite|Group=$SERVICE_USER|g" "$SERVICE_FILE"
    install -m 0644 "$INSTALL_DIR/deploy/monitor-suite-smart.service" "/etc/systemd/system/$SMART_SERVICE_NAME"
    sed -i "s|/opt/monitor-suite-agent|$INSTALL_DIR|g; s|/etc/monitor-suite-agent.env|$CONFIG_FILE|g; s|Group=monitor-suite|Group=$SERVICE_USER|g" "/etc/systemd/system/$SMART_SERVICE_NAME"
    install -m 0644 "$INSTALL_DIR/deploy/monitor-suite-smart.timer" "/etc/systemd/system/$SMART_TIMER_NAME"
    install -m 0644 "$INSTALL_DIR/deploy/monitor-suite-power.service" "/etc/systemd/system/$POWER_SERVICE_NAME"
    sed -i "s|/opt/monitor-suite-agent|$INSTALL_DIR|g; s|/etc/monitor-suite-agent.env|$CONFIG_FILE|g; s|Group=monitor-suite|Group=$SERVICE_USER|g" "/etc/systemd/system/$POWER_SERVICE_NAME"
    install -m 0644 "$INSTALL_DIR/deploy/monitor-suite-power.timer" "/etc/systemd/system/$POWER_TIMER_NAME"
    systemctl daemon-reload
    systemctl enable "$SMART_TIMER_NAME" "$SERVICE_NAME" >/dev/null
    systemctl start "$SMART_SERVICE_NAME"
    case "$(uname -m)" in
        x86_64|amd64)
            systemctl enable "$POWER_TIMER_NAME" >/dev/null
            systemctl start "$POWER_SERVICE_NAME"
            systemctl restart "$POWER_TIMER_NAME"
            ;;
        *)
            systemctl disable --now "$POWER_TIMER_NAME" >/dev/null 2>&1 || true
            ;;
    esac
    systemctl restart "$SERVICE_NAME"
    systemctl restart "$SMART_TIMER_NAME"
}

service_diagnostics() {
    systemctl --no-pager --full status "$SERVICE_NAME" >&2 || true
    if command -v journalctl >/dev/null 2>&1; then
        journalctl --no-pager --quiet --unit "$SERVICE_NAME" --lines 20 >&2 || true
    fi
}

wait_for_service() {
    attempts=0
    while [ "$attempts" -lt 20 ]; do
        if systemctl is-active --quiet "$SERVICE_NAME"; then
            sleep 2
            if systemctl is-active --quiet "$SERVICE_NAME"; then
                return 0
            fi
        fi
        attempts=$((attempts + 1))
        sleep 1
    done
    service_diagnostics
    fail "The service did not remain active after startup."
}

verify_api() {
    host=$(read_config_value MONITOR_SUITE_HOST || true)
    port=$(read_config_value MONITOR_SUITE_PORT || true)
    token=$(read_config_value MONITOR_SUITE_API_KEY || true)
    [ -n "$host" ] || host=0.0.0.0
    [ -n "$port" ] || port=5000
    [ -n "$token" ] || fail "No API token was found in $CONFIG_FILE"
    case "$host" in
        0.0.0.0|::|\[::\]) request_host=127.0.0.1 ;;
        *) request_host=$host ;;
    esac
    expected_version=$("$INSTALL_DIR/.venv/bin/python" -c 'from monitor_suite_agent import __version__; print(__version__)')

    MONITOR_SUITE_VERIFY_URL="http://$request_host:$port/health" \
    MONITOR_SUITE_VERIFY_TOKEN="$token" \
    MONITOR_SUITE_VERIFY_VERSION="$expected_version" \
    "$INSTALL_DIR/.venv/bin/python" - <<'PYVERIFY'
import json
import os
import time
import urllib.error
import urllib.request

url = os.environ["MONITOR_SUITE_VERIFY_URL"]
token = os.environ["MONITOR_SUITE_VERIFY_TOKEN"]
expected_version = os.environ["MONITOR_SUITE_VERIFY_VERSION"]

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None

opener = urllib.request.build_opener(NoRedirect)
request = urllib.request.Request(url, headers={"X-API-Key": token})
response = None
for attempt in range(20):
    try:
        response = opener.open(request, timeout=2)
        break
    except urllib.error.HTTPError as error:
        if error.code in (301, 302, 303, 307, 308):
            print("API verification failed: the health endpoint returned a redirect.")
            raise SystemExit(21)
        if error.code in (401, 403):
            print("API verification failed: the health endpoint rejected the configured API token.")
            raise SystemExit(22)
        print(f"API verification failed: the health endpoint returned HTTP {error.code}.")
        raise SystemExit(23)
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        if attempt == 19:
            print("API verification failed: the health endpoint could not be reached.")
            raise SystemExit(20)
        time.sleep(1)

if response is None or response.status != 200:
    print("API verification failed: the health endpoint did not return HTTP 200.")
    raise SystemExit(23)

try:
    payload = json.loads(response.read().decode("utf-8"))
except (UnicodeDecodeError, json.JSONDecodeError):
    print("API verification failed: the health endpoint did not return valid JSON.")
    raise SystemExit(24)

if not isinstance(payload, dict):
    print("API verification failed: the health endpoint did not return a JSON object.")
    raise SystemExit(24)

if (
    payload.get("status") not in {"starting", "ok", "degraded", "stale"}
    or not isinstance(payload.get("sample_available"), bool)
    or not isinstance(payload.get("version"), str)
    or set(payload) != {"status", "version", "sample_available"}
):
    print("API verification failed: the response is not the Monitor Suite Agent health contract. Another process may own the configured port.")
    raise SystemExit(25)

if payload["version"] != expected_version:
    print(
        "API verification failed: version mismatch "
        f"(expected {expected_version}, received {payload['version']})."
    )
    raise SystemExit(26)

print(f"Verified Monitor Suite Agent {expected_version} at {url}")
PYVERIFY
}

show_token() {
    need_root
    token=$(read_config_value MONITOR_SUITE_API_KEY || true)
    [ -n "$token" ] || fail "No API token was found in $CONFIG_FILE"
    printf '%s\n' "$token"
}

rotate_token() {
    need_root
    [ -f "$CONFIG_FILE" ] || fail "Configuration not found: $CONFIG_FILE"
    token=$(generate_token)
    temporary="${CONFIG_FILE}.tmp.$$"
    umask 077
    awk -v token="$token" '
        BEGIN { replaced = 0 }
        /^MONITOR_SUITE_API_KEY=/ { print "MONITOR_SUITE_API_KEY=" token; replaced = 1; next }
        { print }
        END { if (!replaced) print "MONITOR_SUITE_API_KEY=" token }
    ' "$CONFIG_FILE" > "$temporary"
    chown root:"$SERVICE_USER" "$temporary"
    chmod 0640 "$temporary"
    mv "$temporary" "$CONFIG_FILE"
    systemctl restart "$SERVICE_NAME"
    say "API token rotated. Update every client that uses the old token."
    printf 'API token: %s\n' "$token"
}

show_summary() {
    port=$(read_config_value MONITOR_SUITE_PORT || true)
    [ -n "$port" ] || port=5000
    ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    [ -n "$ip" ] || ip='<raspberry-pi-address>'
    say ""
    say "Monitor Suite Agent is installed and running."
    say "Status URL: http://$ip:$port/status"
    say "Health URL: http://$ip:$port/health"
    if [ -n "$CREATED_TOKEN" ]; then
        say "API token: $CREATED_TOKEN"
        say "Save this token in Home Assistant. It will not be shown during updates."
    else
        say "Existing API token preserved. Show it with: sudo $INSTALL_DIR/install.sh token"
    fi
    say "Request header: X-API-Key: <api-token>"
    say "Service status: sudo systemctl status $SERVICE_NAME"
}

install_or_update() {
    need_root
    validate_paths
    install_dependencies
    need_command getent
    need_command groupadd
    need_command useradd
    need_command usermod
    if ! getent group "$SERVICE_USER" >/dev/null 2>&1; then
        groupadd --system "$SERVICE_USER"
    fi
    if ! id "$SERVICE_USER" >/dev/null 2>&1; then
        useradd --system --gid "$SERVICE_USER" --home-dir "$INSTALL_DIR" \
            --shell /usr/sbin/nologin "$SERVICE_USER"
    fi
    if getent group video >/dev/null 2>&1; then
        usermod --append --groups video "$SERVICE_USER"
    fi
    need_command git
    need_command python3
    need_command systemctl
    install_source
    install_python
    create_config
    create_service
    wait_for_service
    if ! verify_api; then
        service_diagnostics
        fail "Installation verification failed. The success summary was not printed."
    fi
    show_summary
}

status_agent() {
    need_root
    systemctl --no-pager --full status "$SERVICE_NAME"
}

uninstall_agent() {
    need_root
    systemctl disable --now "$SERVICE_NAME" "$SMART_TIMER_NAME" 2>/dev/null || true
    rm -f "/etc/systemd/system/$SMART_SERVICE_NAME" "/etc/systemd/system/$SMART_TIMER_NAME"
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload
    rm -rf "$INSTALL_DIR" /run/monitor-suite-agent
    say "Removed the service and application."
    say "Preserved configuration: $CONFIG_FILE"
}

usage() {
    cat <<EOF
Usage: install.sh [install|update|status|token|rotate-token|uninstall]

Environment overrides:
  MONITOR_SUITE_REPO_URL       Git repository URL
  MONITOR_SUITE_BRANCH         Git branch (default: main)
  MONITOR_SUITE_INSTALL_DIR    Installation directory
  MONITOR_SUITE_CONFIG_FILE    Configuration file
EOF
}

case "$ACTION" in
    install|update) install_or_update ;;
    status) status_agent ;;
    token) show_token ;;
    rotate-token) rotate_token ;;
    uninstall) uninstall_agent ;;
    help|-h|--help) usage ;;
    *) usage >&2; exit 64 ;;
esac
