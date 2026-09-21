"""Pin monitor-only accounting correction; keep the running controller unchanged."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET

REPO = Path('C:/Users/jewon/esm-r23-d115-writer')
BASE = REPO / 'artifacts/skhynix_v1/architecture_scale_001'
CONT = BASE / 'l3-recovery-001/evaluation-continuation-001'

def ref(path):
    path = path.resolve()
    name = path.as_posix()
    assert name.startswith('C:/')
    return {'path': '/mnt/c/' + name[3:], 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

health = ref(REPO / 'scripts/trimem_skhynix_scale_health.py')
assert health['sha256'] == '33cfb598ce953bd8d58269af63d9f0b51beb728586e913c8926211e27b440210'
test_path = CONT / 'health-count-validation-003.xml'
suite = ET.fromstring(test_path.read_bytes()).find('testsuite')
assert suite is not None
assert (int(suite.attrib['tests']), int(suite.attrib['failures']), int(suite.attrib['errors'])) == (64, 0, 0)
archive = BASE / 'active-controller-v16.json'
active = BASE / 'active-controller.json'
assert archive.read_bytes() == active.read_bytes()
value = json.loads(archive.read_bytes())
assert value['configuration_name'] == 'architecture_002_pipeline_v16.json'
assert value['configuration_reference'] == ref(REPO / 'configs/skhynix_v1/architecture_002_pipeline_v16.json')
value.update(
    health_helper_reference=health,
    health_tests_reference=ref(REPO / 'tests/unit/test_trimem_skhynix_scale_health.py'),
    health_validation_reference=ref(test_path),
    superseded_monitor_metadata_reference=ref(archive),
    monitor_metadata_updated_at=datetime.now(timezone.utc).isoformat(),
    monitor_metadata_reason='Monitor-only correction: count actual CELL_COMPLETE events separately from authenticated unscored holds; controller, native solver, grading, memory and budgets unchanged.',
    health_validation_note='64 passed with repository scripts and src on PYTHONPATH. The retained health-count-validation-002.xml is a test-launch import error from missing PYTHONPATH, unrelated to the running controller.',
)
raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode() + b'\n'
new = BASE / 'active-controller-v16-health2.json'
with new.open('xb') as stream:
    stream.write(raw)
pending = BASE / 'active-controller-v16-health2.next.json'
with pending.open('xb') as stream:
    stream.write(raw)
pending.replace(active)
print(json.dumps(ref(new)))
