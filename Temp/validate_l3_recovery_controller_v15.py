"""Read the real recovered bank through the unchanged source-v6 evaluator."""
from pathlib import Path
import importlib.util
import json

import trimem_skhynix_architecture_pipeline as core

REPO = Path('/mnt/c/Users/jewon/esm-r23-d115-writer')
config_path = REPO / 'configs/skhynix_v1/architecture_002_pipeline_v15.json'
config = core.read(config_path)
source = core.check(config['pipeline_source_reference'], decode=False)
spec = importlib.util.spec_from_file_location('skhynix_frozen_recovery_controller_v15', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
controller = module.ReflectionRecoveryPipeline(config_path)
result = module.validate_recovered_bank(controller.config, controller.previous, controller.operations)
output = REPO / 'artifacts/skhynix_v1/architecture_scale_001/l3-recovery-001/startup-validation-v15.json'
if output.exists():
    raise ValueError('Startup validation receipt already exists')
reference = core.retain(output, result)
print(json.dumps({'validation_reference': reference, 'status': result['status'], 'layer_counts': result['layer_counts']}))
