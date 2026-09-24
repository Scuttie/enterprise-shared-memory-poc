"""Run the frozen loader API and transport its exact evidence to Windows."""
import base64
from pathlib import Path
import sys

SOURCE = Path('/mnt/c/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-source-v6')
sys.path[:0] = [str(SOURCE / 'scripts'), str(SOURCE / 'src')]
import trimem_official_harness_loader_preflight as loader

assert Path(loader.__file__).resolve().is_relative_to(SOURCE.resolve())
result = loader.run_official_harness_loader_preflight(
    python_binary=Path('/opt/trimem-rehearsals/e932-preflight/venv/bin/python'),
    swe_harness_root=Path('/opt/trimem-rehearsals/e932-preflight/harnesses/swebench_verified'),
    multi_harness_root=Path('/opt/trimem-rehearsals/e932-preflight/harnesses/multi'))
print(base64.b64encode(loader._canonical_bytes(result)).decode())
