#!/bin/sh
set -eu

REPO_URL=${MONITOR_SUITE_REPO_URL:-https://github.com/swetoast/Monitor-Suite.git}
BRANCH=${MONITOR_SUITE_BRANCH:-main}
INSTALL_DIR=${MONITOR_SUITE_INSTALL_DIR:-/opt/monitor-suite-agent}
CONFIG_FILE=${MONITOR_SUITE_CONFIG_FILE:-/etc/monitor-suite-agent.env}
SERVICE_FILE=${MONITOR_SUITE_SERVICE_FILE:-/etc/systemd/system/monitor-suite-agent.service}
SERVICE_USER=${MONITOR_SUITE_SERVICE_USER:-monitor-suite}
SERVICE_NAME=monitor-suite-agent.service
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
    case "$SERVICE_FILE" in /*) ;; *) fail "MONITOR_SUITE_SERVICE_FILE must be an absolute path." ;; esac
    case "$INSTALL_DIR$CONFIG_FILE$SERVICE_FILE" in
        *[!A-Za-z0-9_./-]*) fail "Installation, configuration, and service paths may use only letters, numbers, _, ., /, and -." ;;
    esac
    case "$SERVICE_USER" in
        ""|*[!A-Za-z0-9_-]*) fail "MONITOR_SUITE_SERVICE_USER contains unsupported characters." ;;
    esac
    case "$BRANCH" in
        ""|-*) fail "MONITOR_SUITE_BRANCH must be a branch name and cannot begin with -." ;;
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

create_user() {
    if ! id "$SERVICE_USER" >/dev/null 2>&1; then
        useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
    fi
    for group in video disk; do
        if getent group "$group" >/dev/null 2>&1; then
            usermod -a -G "$group" "$SERVICE_USER"
        fi
    done
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
    chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
}

install_python() {
    say "Installing the locked Python environment"
    if [ ! -x "$INSTALL_DIR/.venv/bin/python" ]; then
        su -s /bin/sh -c "python3 -m venv '$INSTALL_DIR/.venv'" "$SERVICE_USER"
    fi
    su -s /bin/sh -c "'$INSTALL_DIR/.venv/bin/python' -m pip install --disable-pip-version-check --requirement '$INSTALL_DIR/requirements.lock'" "$SERVICE_USER"
    su -s /bin/sh -c "'$INSTALL_DIR/.venv/bin/python' -m pip install --disable-pip-version-check --no-deps --force-reinstall '$INSTALL_DIR'" "$SERVICE_USER"
}

create_config() {
    if [ -f "$CONFIG_FILE" ]; then
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
    supplementary=
    for group in video disk; do
        if getent group "$group" >/dev/null 2>&1; then
            supplementary="$supplementary $group"
        fi
    done
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Monitor Suite Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
SupplementaryGroups=$supplementary
EnvironmentFile=$CONFIG_FILE
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/monitor-suite-agent
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
RestrictSUIDSGID=true
RestrictRealtime=true
LockPersonality=true
MemoryDenyWriteExecute=true
SystemCallArchitectures=native
UMask=0077

[Install]
WantedBy=multi-user.target
EOF
    chmod 0644 "$SERVICE_FILE"
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME" >/dev/null
    systemctl restart "$SERVICE_NAME"
}

wait_for_service() {
    attempts=0
    while [ "$attempts" -lt 20 ]; do
        if systemctl is-active --quiet "$SERVICE_NAME"; then
            return 0
        fi
        attempts=$((attempts + 1))
        sleep 1
    done
    systemctl --no-pager --full status "$SERVICE_NAME" || true
    fail "The service did not become active."
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
    need_command git
    need_command python3
    need_command systemctl
    create_user
    install_source
    install_python
    create_config
    create_service
    wait_for_service
    show_summary
}

status_agent() {
    need_root
    systemctl --no-pager --full status "$SERVICE_NAME"
}

uninstall_agent() {
    need_root
    systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload
    rm -rf "$INSTALL_DIR"
    say "Removed the service and application."
    say "Preserved configuration: $CONFIG_FILE"
}

usage() {
    cat <<EOF
Usage: install.sh [install|update|status|token|rotate-token|uninstall]

Environment overrides:
  MONITOR_SUITE_REPO_URL       Git repository URL
  MONITOR_SUITE_BRANCH         Git branch or tag (default: main)
  MONITOR_SUITE_INSTALL_DIR    Installation directory
  MONITOR_SUITE_CONFIG_FILE    Configuration file
  MONITOR_SUITE_SERVICE_USER   Service account
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
