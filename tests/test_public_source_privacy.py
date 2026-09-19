"""Prevent private deployment and device data from entering public releases."""

from pathlib import Path
import re


ROOT = Path(__file__).parents[1]
TEXT_SUFFIXES = {".md", ".py", ".toml", ".txt", ".service", ".sh"}
ALLOWED_PRIVATE_NETWORK_TEXT = {
    "127.0.0.1",
    "127.0.0.0/8",
    "10.0.0.0",
}
SYNTHETIC_RAID_UUID = "11111111:22222222:33333333:44444444"


def source_text() -> dict[Path, str]:
    return {
        path: path.read_text(errors="ignore")
        for path in ROOT.rglob("*")
        if path.is_file()
        and path.suffix in TEXT_SUFFIXES
        and ".git" not in path.parts
        and "__pycache__" not in path.parts
    }


def test_private_identity_and_deployment_values_are_absent() -> None:
    forbidden_hex = (
        "506574657220536b6f7061",
        "31302e302e302e35",
        "426f72c3a573",
        "56c3a473746572c3a573",
        "4b656e6e657468204a61636f62736f6e",
        "4c6f74746120546865726e204e7962657267",
        "6879706572696f6e",
        "574443205744333134304c4d43572d31314439475333",
        "4b494e4753544f4e20534b43333030305335313247",
        "53414d53554e47204d5a564c57313238484547522d3030304c32",
    )
    forbidden = tuple(bytes.fromhex(value).decode("utf-8") for value in forbidden_hex)
    for path, text in source_text().items():
        for value in forbidden:
            assert value not in text, f"private identity or deployment value found in {path}"


def test_documentation_uses_public_placeholders() -> None:
    install = (ROOT / "docs/INSTALL.md").read_text()
    security = (ROOT / "docs/SECURITY.md").read_text()
    assert "<nas-ip-address>" in install
    assert "<homeassistant-server>" in install
    assert "<nas-ip-address>" in security


def test_no_unapproved_private_ipv4_addresses() -> None:
    private_ip = re.compile(
        r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
        r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b"
    )
    for path, text in source_text().items():
        for address in private_ip.findall(text):
            assert address in ALLOWED_PRIVATE_NETWORK_TEXT, (
                f"private address {address} found in {path}"
            )


def test_no_email_addresses_or_user_home_paths() -> None:
    email = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
    home_path = re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+")
    for path, text in source_text().items():
        matches = {match.group(0) for match in email.finditer(text)}
        assert matches <= {"git@github.com"}, f"email address found in {path}: {matches}"
        assert not home_path.search(text), f"user home path found in {path}"


def test_hardware_fixture_identifiers_are_scrubbed() -> None:
    fixture = (ROOT / "tests/fixtures/raid_smart_probe_pi5.txt").read_text()
    raid_uuids = re.findall(
        r"\b[0-9a-fA-F]{8}(?::[0-9a-fA-F]{8}){3}\b", fixture
    )
    assert raid_uuids
    assert set(raid_uuids) == {SYNTHETIC_RAID_UUID}
    assert re.findall(r'"serial_number"\s*:\s*"(.*?)"', fixture)
    assert set(re.findall(r'"serial_number"\s*:\s*"(.*?)"', fixture)) == {"REDACTED"}
    wwn_lines = [line.strip() for line in fixture.splitlines() if '"wwn"' in line]
    assert wwn_lines
    assert all(line.startswith('"wwn": REDACTED') for line in wwn_lines)
    assert "Linux test-host " in fixture
    assert "Name : test-host:0  (local to host test-host)" in fixture
    assert set(re.findall(r'"model_name"\s*:\s*"(.*?)"', fixture)) == {
        "GENERIC USB HDD 300GB",
        "GENERIC NVME SSD 512GB",
        "GENERIC NVME SSD 128GB",
    }


def test_no_committed_secrets() -> None:
    concrete_secret = re.compile(
        r"(?m)^\s*(?:MONITOR_SUITE_API_KEY|API_KEY|TOKEN|PASSWORD|SECRET)="
        r"(?!<|\$|none\b|null\b|redacted\b|generated\b)([^#\s]+)"
    )
    private_key = "-----BEGIN " + "PRIVATE KEY-----"
    for path, text in source_text().items():
        assert not concrete_secret.search(text), f"possible committed secret in {path}"
        assert private_key not in text, f"private key found in {path}"
