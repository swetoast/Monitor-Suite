"""Root-only, networkless SMART collector."""
from __future__ import annotations
import argparse, json, os, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .telemetry import Paths, read_smart_devices, run_smartctl
DEFAULT_CACHE = Path("/run/monitor-suite-agent/smart.json")
def _previous(path: Path) -> list[dict[str, Any]]:
    try:
        value=json.loads(path.read_text(encoding="utf-8")).get("devices", [])
        return value if isinstance(value, list) else []
    except (OSError, ValueError, TypeError): return []
def write_cache(path: Path, devices: list[dict[str, Any]]) -> None:
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    payload={"schema_version":1,"generated_at":datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z"),"devices":devices}
    fd,temp=tempfile.mkstemp(prefix=".smart-",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(payload,f,separators=(",",":"),sort_keys=True); f.write("\n"); f.flush(); os.fsync(f.fileno())
        os.chmod(temp,0o640); os.replace(temp,path)
    finally:
        try: os.unlink(temp)
        except FileNotFoundError: pass
def collect(cache: Path=DEFAULT_CACHE, timeout: float=10.0) -> int:
    write_cache(cache,read_smart_devices(Paths().block_root,run_smartctl,timeout,_previous(cache))); return 0
def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--cache",type=Path,default=DEFAULT_CACHE); p.add_argument("--timeout",type=float,default=10.0); a=p.parse_args(); return collect(a.cache,a.timeout)
if __name__ == "__main__": raise SystemExit(main())
