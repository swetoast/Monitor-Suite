"""Installer contract and management-action tests."""

from pathlib import Path
import os
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
