"""Regression evidence checks for the supplied Raspberry Pi RAID and SMART probe."""
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "raid_smart_probe_pi5.txt"

def test_verified_raid_probe_evidence_is_preserved() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    required = (
        "Monitor Suite Agent RAID and SMART probe",
        "md0 : active raid0 sda[1] sdb[0]",
        "array_state=clean",
        "level=raid0",
        "raid_disks=2",
        "dev-sda state=in_sync",
        "dev-sdb state=in_sync",
        '"passed": true',
    )
    for marker in required:
        assert marker in text
    assert text.count('"serial_number": "REDACTED"') >= 4
