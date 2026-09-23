"""Installer contract and management-action tests."""

from pathlib import Path
import os
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess


ROOT = Path(__file__).parents[1]
INSTALLER = ROOT / "install.sh"


def test_installer_targets_monitor_suite_github_repository() -> None:
    text = INSTALLER.read_text()
    assert "https://github.com/swetoast/Monitor-Suite.git" in text
    assert "requirements.lock" in text
    assert "monitor-suite-agent.service" in text


def test_installer_supports_one_command_github_install() -> None:
    readme = (ROOT / "README.md").read_text()
    guide = (ROOT / "docs/INSTALL.md").read_text()
    command = (
        "curl -fsSL https://raw.githubusercontent.com/"
        "swetoast/Monitor-Suite/main/install.sh | sudo sh"
    )
    assert command in readme
    assert command in guide
    assert "apt-get install -y git python3 python3-venv python3-pip smartmontools" in INSTALLER.read_text()


def test_installer_preserves_configuration_and_token() -> None:
    text = INSTALLER.read_text()
    assert 'if [ -f "$CONFIG_FILE" ]' in text
    assert "Preserving existing configuration" in text
    assert "Existing API token preserved" in text
    assert "MONITOR_SUITE_API_KEY=$CREATED_TOKEN" in text


def test_installer_uses_direct_lan_authentication() -> None:
    text = INSTALLER.read_text()
    assert "MONITOR_SUITE_HOST=0.0.0.0" in text
    assert "MONITOR_SUITE_API_KEY=$CREATED_TOKEN" in text
    assert "MONITOR_SUITE_ENABLE_DOCS=false" in text
    assert "X-API-Key: <api-token>" in text


def test_installer_exposes_management_actions() -> None:
    text = INSTALLER.read_text()
    for action in ("install", "update", "status", "token", "rotate-token", "uninstall"):
        assert action in text
    result = subprocess.run(
        ["sh", str(INSTALLER), "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "token" in result.stdout
    assert "rotate-token" in result.stdout


def fake_root_commands(tmp_path: Path) -> Path:
    binary = tmp_path / "bin"
    binary.mkdir()
    (binary / "id").write_text("#!/bin/sh\nprintf '0\\n'\n")
    (binary / "chown").write_text("#!/bin/sh\nexit 0\n")
    (binary / "systemctl").write_text("#!/bin/sh\nexit 0\n")
    for path in binary.iterdir():
        path.chmod(0o755)
    return binary


def installer_environment(tmp_path: Path, config: Path) -> dict[str, str]:
    binary = fake_root_commands(tmp_path)
    environment = os.environ.copy()
    environment["PATH"] = f"{binary}:/usr/bin:/bin"
    environment["MONITOR_SUITE_CONFIG_FILE"] = str(config)
    environment["MONITOR_SUITE_SERVICE_USER"] = "monitor-suite"
    return environment


def test_token_action_prints_existing_token(tmp_path: Path) -> None:
    config = tmp_path / "agent.env"
    config.write_text("MONITOR_SUITE_API_KEY=existing-test-token\n")
    result = subprocess.run(
        ["sh", str(INSTALLER), "token"],
        env=installer_environment(tmp_path, config),
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout == "existing-test-token\n"
    assert config.read_text() == "MONITOR_SUITE_API_KEY=existing-test-token\n"


def test_rotate_token_replaces_token_and_preserves_configuration(tmp_path: Path) -> None:
    config = tmp_path / "agent.env"
    config.write_text(
        "MONITOR_SUITE_HOST=0.0.0.0\n"
        "MONITOR_SUITE_PORT=5000\n"
        "MONITOR_SUITE_API_KEY=old-test-token\n"
        "MONITOR_SUITE_ENABLE_DOCS=false\n"
    )
    result = subprocess.run(
        ["sh", str(INSTALLER), "rotate-token"],
        env=installer_environment(tmp_path, config),
        text=True,
        capture_output=True,
        check=True,
    )
    updated = config.read_text()
    token_line = next(line for line in updated.splitlines() if line.startswith("MONITOR_SUITE_API_KEY="))
    token = token_line.split("=", 1)[1]
    assert token != "old-test-token"
    assert len(token) >= 43
    assert "MONITOR_SUITE_PORT=5000" in updated
    assert "MONITOR_SUITE_ENABLE_DOCS=false" in updated
    assert f"API token: {token}" in result.stdout


def test_updates_allow_root_to_manage_service_owned_checkout() -> None:
    text = INSTALLER.read_text()
    assert 'git -c "safe.directory=$INSTALL_DIR"' in text
    assert 'git_install -C "$INSTALL_DIR" fetch' in text


def test_installer_rejects_systemd_directive_injection(tmp_path: Path) -> None:
    text = INSTALLER.read_text()
    assert '*[!A-Za-z0-9_./-]*' in text
    binary = fake_root_commands(tmp_path)
    result = subprocess.run(
        ["sh", str(INSTALLER), "install"],
        env={
            **os.environ,
            "PATH": f"{binary}:/usr/bin:/bin",
            "MONITOR_SUITE_INSTALL_DIR": "/opt/agent\nExecStart=/bin/false",
        },
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "may use only" in result.stderr



def test_api_service_is_unprivileged_and_smart_collector_is_root() -> None:
    installer = INSTALLER.read_text()
    api = (INSTALLER.parent / "deploy/monitor-suite-agent.service").read_text()
    collector = (INSTALLER.parent / "deploy/monitor-suite-smart.service").read_text()
    timer = (INSTALLER.parent / "deploy/monitor-suite-smart.timer").read_text()
    assert "User=monitor-suite" in api
    assert "Group=monitor-suite" in api
    assert "PrivateDevices=true" not in api
    assert "SupplementaryGroups=video" in api
    assert "User=root" in collector
    assert "Group=monitor-suite" in collector
    assert "monitor-suite-smart-collector" in collector
    assert "OnUnitActiveSec=15min" in timer
    assert "useradd --system" in installer


def test_installer_creates_matching_service_group_and_video_membership() -> None:
    installer = INSTALLER.read_text()
    assert 'groupadd --system "$SERVICE_USER"' in installer
    assert 'useradd --system --gid "$SERVICE_USER"' in installer
    assert 'usermod --append --groups video "$SERVICE_USER"' in installer
    assert "MONITOR_SUITE_SERVICE_FILE" not in installer
    assert 'rm -rf "$INSTALL_DIR" /run/monitor-suite-agent' in installer


def test_unprivileged_service_keeps_systemd_hardening() -> None:
    service = (INSTALLER.parent / "deploy/monitor-suite-agent.service").read_text()
    for directive in (
        "NoNewPrivileges=true",
        "PrivateTmp=true",
        "ProtectSystem=strict",
        "ProtectHome=true",
        "ProtectKernelTunables=true",
        "ProtectKernelModules=true",
        "ProtectControlGroups=true",
        "RestrictSUIDSGID=true",
        "LockPersonality=true",
        "MemoryDenyWriteExecute=true",
    ):
        assert directive in service



def test_existing_configuration_is_preserved_and_hardened() -> None:
    installer = INSTALLER.read_text()
    existing = installer.index('if [ -f "$CONFIG_FILE" ]')
    created = installer.index('CREATED_TOKEN=$(generate_token)')
    block = installer[existing:created]
    assert 'chown root:"$SERVICE_USER" "$CONFIG_FILE"' in block
    assert 'chmod 0640 "$CONFIG_FILE"' in block
    assert 'return' in block



def verifier_program() -> str:
    installer = INSTALLER.read_text()
    match = re.search(r"<<'PYVERIFY'\n(.*?)\nPYVERIFY", installer, re.DOTALL)
    assert match is not None
    return match.group(1)


def run_verifier(status: int, body: object, *, location: str | None = None) -> subprocess.CompletedProcess[str]:
    payload = body if isinstance(body, bytes) else json.dumps(body).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            assert self.path == "/health"
            assert self.headers.get("X-API-Key") == "test-token"
            self.send_response(status)
            if location is not None:
                self.send_header("Location", location)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        return subprocess.run(
            ["python3", "-c", verifier_program()],
            env={
                **os.environ,
                "MONITOR_SUITE_VERIFY_URL": f"http://127.0.0.1:{server.server_port}/health",
                "MONITOR_SUITE_VERIFY_TOKEN": "test-token",
                "MONITOR_SUITE_VERIFY_VERSION": "2.7.0",
            },
            text=True,
            capture_output=True,
        )
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_api_verifier_accepts_exact_health_contract() -> None:
    result = run_verifier(
        200,
        {"status": "ok", "version": "2.7.0", "sample_available": True},
    )
    assert result.returncode == 0
    assert "Verified Monitor Suite Agent 2.7.0" in result.stdout
    assert "test-token" not in result.stdout + result.stderr


def test_api_verifier_rejects_unrelated_json_on_occupied_port() -> None:
    result = run_verifier(200, {"service": "unrelated", "status": "ok"})
    assert result.returncode == 25
    assert "Another process may own the configured port" in result.stdout
    assert "test-token" not in result.stdout + result.stderr


def test_api_verifier_rejects_redirect_from_unrelated_process() -> None:
    result = run_verifier(302, {}, location="/login")
    assert result.returncode == 21
    assert "returned a redirect" in result.stdout


def test_api_verifier_distinguishes_authentication_and_version_failures() -> None:
    auth = run_verifier(401, {"detail": "unauthorized"})
    assert auth.returncode == 22
    assert "rejected the configured API token" in auth.stdout

    version = run_verifier(
        200,
        {"status": "ok", "version": "9.9.9", "sample_available": True},
    )
    assert version.returncode == 26
    assert "version mismatch" in version.stdout


def test_api_verifier_rejects_non_json_response() -> None:
    result = run_verifier(200, b"not-json")
    assert result.returncode == 24
    assert "did not return valid JSON" in result.stdout


def test_success_summary_is_gated_by_service_and_api_verification() -> None:
    installer = INSTALLER.read_text()
    sequence = installer[installer.index("install_or_update() {"):installer.index("status_agent() {")]
    assert sequence.index("wait_for_service") < sequence.index("verify_api")
    assert sequence.index("verify_api") < sequence.index("show_summary")
    assert 'if ! verify_api; then' in sequence


def test_installer_configures_privilege_separated_collectors() -> None:
    text = INSTALLER.read_text()
    assert "monitor-suite-smart.service" in text
    assert "monitor-suite-smart.timer" in text
    assert "monitor-suite-power.service" in text
    assert "monitor-suite-power.timer" in text
    assert 'x86_64|amd64)' in text
    assert 'systemctl disable --now "$POWER_TIMER_NAME"' in text


def test_documentation_describes_unprivileged_api_service() -> None:
    readme = (ROOT / "README.md").read_text()
    install = (ROOT / "docs/INSTALL.md").read_text()
    security = (ROOT / "docs/SECURITY.md").read_text()
    assert "unprivileged systemd service" in readme
    assert "hardened unprivileged Uvicorn API service" in install
    assert "root-only networkless SMART collector" in install
    assert "amd64-only root-only networkless RAPL power collector" in install
    assert "Separate root-only oneshot services" in security


def test_uninstall_removes_all_power_collector_units() -> None:
    text = INSTALLER.read_text()
    uninstall = text[text.index("uninstall_agent() {") : text.index("usage() {")]
    assert '"$POWER_TIMER_NAME"' in uninstall
    assert '"$POWER_SERVICE_NAME"' in uninstall
    assert '"/etc/systemd/system/$POWER_SERVICE_NAME"' in uninstall
    assert '"/etc/systemd/system/$POWER_TIMER_NAME"' in uninstall
