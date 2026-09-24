"""Independent native004 evidence audit; only writes CENTRAL/audit.json.

No model, grader, container, patch replay, or authority mutation. Frozen
loaders/verifiers inspect existing evidence internally; private payloads are
never printed or included in the public audit. Pending cells remain pending.
"""
import sys
sys.dont_write_bytecode = True
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

CENTRAL = Path('/home/trimem-runner/skhynix-codex-004')
PREFIX = 'swebench_verified--sympy__sympy-'
TRAIN = {PREFIX + x for x in ('14976', '16766')}
EVALUATION = {PREFIX + x for x in ('19346', '20916', '21930', '22080', '22456', '22914')}
ARMS = {'A': 'NO_MEMORY', 'B': 'EXISTING_M2', 'C': 'SKHYNIX'}
LIMITS = {'repository_actions': 120, 'wall_seconds': 1200, 'memory_injections': 3, 'memory_bytes': 12000}
HISTORY = {
  "/home/trimem-runner/skhynix-codex-001/audit.json": "f92167ea8d1969c69bf5c0e72db6575978a458cb9aa1a937aadcd8a638d87c6a",
  "/home/trimem-runner/skhynix-codex-001/execution/report.json": "275c639e31f6f077345d7f99d4d58ef6e17ff086e2217ae48d7e0170c5c60aa2",
  "/home/trimem-runner/skhynix-codex-001/memory-preflight.json": "307751228f3085c83d2663efc1f9d4bf911344eebc028b2f835e1ecfdac82f35",
  "/home/trimem-runner/skhynix-codex-002/audit-preliminary.json": "1bf6c58f3678ab4501c0f0568757d31c369a3d190eb1b2bdf94ff0672f4e6973",
  "/home/trimem-runner/skhynix-codex-002/audit.json": "c9c71db01f7b4e2c0ddc9e192fd7f1c888c3842994bac89b25b03bc9dfa080b2",
  "/home/trimem-runner/skhynix-codex-002/audit_native002.py": "00ee9361ebcecce48a1bf83780f16e46f718ff05ef55f5d88974b046c9068696",
  "/home/trimem-runner/skhynix-codex-002/batch-plan.json": "710673ff6aedc2123fc3779d0682ea9f2955b99263c34049140c9f270414f851",
  "/home/trimem-runner/skhynix-codex-002/batch-plan.json.sha256": "574725d0f16bafa7d9139342863821879dec74ac7ae2714af89bd76f3856915b",
  "/home/trimem-runner/skhynix-codex-002/batch-report.json": "0974a6a27bcb4c76c38a375c614a2d2aab9fafec7392187b6c5a1a2f94446999",
  "/home/trimem-runner/skhynix-codex-002/cold-bank.gate-a-private.sqlite3": "2cdbec63300d268dccd140a66eaf8c780b1eac656b9b2c5eebf757e787dc3ad7",
  "/home/trimem-runner/skhynix-codex-002/cold-bank.json": "3a4bc6a59c3fb902dda6ba3b046628688009ded9146588c52febfe6480fdce00",
  "/home/trimem-runner/skhynix-codex-002/failure-diagnostics.json": "9eb7087c76b04caab13ca304fe5dab1b022be4c9438441578ee89d07773e07f3",
  "/home/trimem-runner/skhynix-codex-002/launch-contract.json": "43315c54c02e972ffbb22641e8a6be7d7a4e4f0702ad0afd8dc18a4045476636",
  "/home/trimem-runner/skhynix-codex-002/learned-bank-spec.json": "9b63bcbf99e00ba985f57d92b73deaacca2aa70a7b9ba45369d32b0bc16b1cfd",
  "/home/trimem-runner/skhynix-codex-002/learned-bank.gate-a-private.sqlite3": "5f6ba71b79ef3357be5a3db72fb6e9f1a263c5bf4862e35d2a91cf949e459a11",
  "/home/trimem-runner/skhynix-codex-002/learned-bank.json": "fa9c23658b26a10f21e56b7459bdb639d56643088a3e452ef668793d7290415f",
  "/home/trimem-runner/skhynix-codex-002/public-task-descriptors.json": "037edd66a56dd75c1c5fd5046dbf6eaecd819a12512c1145e9ed5e0b47a36cfc",
  "/home/trimem-runner/skhynix-codex-002/solver-attestations.json": "3c561736b2634d1b3119902c244500f0406342755857c070415291cc85bb15c5",
  "/home/trimem-runner/skhynix-codex-002/solver_prompt_template.txt": "11663ba89df76b5c2c94d1f31b3a7e05a44244d78b96f973743b84f7015f65ea",
  "/home/trimem-runner/skhynix-codex-002/supplemental-manifest.json": "e074530fb006834d95aee2c4aff23aeb90a18b99c9136eff91fa22aa3fd65814",
  "/home/trimem-runner/skhynix-codex-003/audit.json": "e971424fcc8f11ab1be758c4eea8a2d93dd0178b0c1a543e3ab5d1f1829705ad",
  "/home/trimem-runner/skhynix-codex-003/audit_native003.py": "e7aac69a9f2531b67368f514df89226e1e804e1b416e3bc85530ff9934cbd7de",
  "/home/trimem-runner/skhynix-codex-003/batch-plan.json": "1080b0909a2c56a5de69beeeaaffff9cf699602139afbf957f43a34d2c723710",
  "/home/trimem-runner/skhynix-codex-003/batch-plan.json.sha256": "8bad324a13aedb11474ca4f0c5b10174ce8b9d69aec5af9826f1b7e1db6ed2a7",
  "/home/trimem-runner/skhynix-codex-003/batch-report.json": "2043b8e7ef12510df0126a9c607c9ac9d92c3654b137ee1e03e1c4252c8312ce",
  "/home/trimem-runner/skhynix-codex-003/cold-bank.gate-a-private.sqlite3": "2cdbec63300d268dccd140a66eaf8c780b1eac656b9b2c5eebf757e787dc3ad7",
  "/home/trimem-runner/skhynix-codex-003/cold-bank.json": "25ec3998594fd287f6e0e86f36c9648a0143598726640e295c6b7436bff576ea",
  "/home/trimem-runner/skhynix-codex-003/dataset-preliminary-validation.json": "be195072d8dcd970c10fe224273cf5a99cf43d63dc9ad7f367c5f5a13d277b62",
  "/home/trimem-runner/skhynix-codex-003/dataset-validation.json": "e95e8696d79c87dbb4c6498cad0027d3be11b92d79176daf2a82d0af042a6f77",
  "/home/trimem-runner/skhynix-codex-003/evaluation-task-descriptors.json": "a1fdee091da97f5dd54a5f3086f5387f1fc47989718ad85c99c7538599eaa3dd",
  "/home/trimem-runner/skhynix-codex-003/launch-contract.json": "5297ab304759ab405374c1d753b9f7b1c894cc21a3e3be78904362288bbc551c",
  "/home/trimem-runner/skhynix-codex-003/learned-bank-spec.json": "0b7b10046ee2a75cb3ab639dbf12f76bcbbed7cb5e9d5c9ffe114df78641f04f",
  "/home/trimem-runner/skhynix-codex-003/learned-bank.json": "a99c31bbae74ea2bdd3aa45a905df5f8464cca4ea4c1ffe2cf16d089718486c9",
  "/home/trimem-runner/skhynix-codex-003/manifest-supersession.json": "c6598db19e3f0c6e6781e9038c772e94fdad1983ae140a2552d4b376f7c87c81",
  "/home/trimem-runner/skhynix-codex-003/observation-bank.gate-a-private.sqlite3": "26368a619e1b8aca8ca45fbf51c06900a78969f9476aabceeac652f6b1a5e34e",
  "/home/trimem-runner/skhynix-codex-003/observation-bank.json": "fe4c3b3c9d8753c29073cb23775d3552f5bba892dc87e61a2069ac84fabed4b0",
  "/home/trimem-runner/skhynix-codex-003/procedure-declaration-final.json": "d9b624e3db77154d952fa9a6bbd115c8c30ff9ecb055dc9bff7751d7e7ca8529",
  "/home/trimem-runner/skhynix-codex-003/procedure-declaration-supersession.json": "eefbb40afe17ef528cff4c7ef68cbf9f8a9daaacf6e97b40ed6b773112803704",
  "/home/trimem-runner/skhynix-codex-003/procedure-declaration.json": "3be288c74113f9ea8e3a83aade1f7534b0e38f3111ee6bcc8867168a4a10d77f",
  "/home/trimem-runner/skhynix-codex-003/procedure-training-public-summary.json": "835640759e4d86e13341d795d5a800b52cbd565b3e1671e999b9d9ab9f34dc3c",
  "/home/trimem-runner/skhynix-codex-003/skill-bank-memory-validation.xml": "7655bda7acd3113075d8f0ddb558431d61026de0dcad52c4f3a8e0953b34a025",
  "/home/trimem-runner/skhynix-codex-003/solver-attestations.json": "f89543f01d48dfa1198f29825d630ada64bf5723b57fc2077d877a8431ba4f15",
  "/home/trimem-runner/skhynix-codex-003/solver_prompt_template.txt": "745986f93d449b91163f634ac85e91875f426948d68518239f3d99263b3a5c05",
  "/home/trimem-runner/skhynix-codex-003/supplemental-manifest.json": "84990cef1f5bb420f37b14f2d829a172385cfa1fa9ba618963316e8c22768cd5",
  "/home/trimem-runner/skhynix-codex-003/supplemental-preliminary-manifest.json": "03df50e021b09ab490e48d840da418f8a2e3c52182468d18a41a3947ede6f413",
  "/home/trimem-runner/skhynix-codex-003/training-public-tasks.json": "91c4953a35ac1f1d796f1673ac7e4315f46cf3789c5a1e6f15e4d0d93ee71240",
  "/home/trimem-runner/skhynix-codex-003/training-task-descriptors.json": "012cb7b2e727c9db20d7c96afe3e1dd04c6a0b409b2370da2984a45bfa1ca964",
  "/home/trimem-runner/skhynix-codex-003/training_solver_prompt_template.txt": "c3df9d16f7219fb3d302a0f583df25ac45a7f312bc237f39c3e6398e24dd36cc",
  "/home/trimem-runner/skhynix-live-001/audit-final.json": "eff6a91663bf44e211a0d3fa64080f3f7aa83756ffffcfe6fc6e60aa8045547d",
  "/home/trimem-runner/skhynix-live-001/audit-interim.json": "3ac972db1f1f8c76ada2dd1dc1cae5b20980d5e4b1fd6d24da2945d366b3f160",
  "/home/trimem-runner/skhynix-live-001/execution/report.json": "a6fde126cdd0e545e6e478ce4740b7038803df10052ee23433e9f8439cba46e0",
  "/home/trimem-runner/skhynix-live-001/final-source-overlay.json": "e2f1ed6c51d36011d5e7f29330a4391c862f63cecac6d4fd03a7970416549586",
  "/home/trimem-runner/skhynix-live-001/initial-source-overlay.json": "4fcdc72947c27a59df902443f17d461144ad32b8da21837efd63dfffbaac4dee",
  "/home/trimem-runner/skhynix-live-002/audit-final.json": "0a68e5546fe26a853fedfe37614e1fc26c14c6760bdd40f8e190f9eec0dbec36",
  "/home/trimem-runner/skhynix-live-002/execution/report.json": "1971c9ebb9f5f8e7cbb7188ca33c031725c009240184fbb7fecf84f140a0f784",
  "/home/trimem-runner/skhynix-live-002/source-overlay-final.json": "a462a78c189ecf158809540540481f080919f929ea49131b718b54063e564070"
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def instance(task_id):
    return task_id.removeprefix('swebench_verified--')


def read_only_db(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    return connection


class Audit:
    def __init__(self):
        self.passed, self.failures, self.pending = 0, [], []
        self.rows, self.training, self.sources, self.anchors = [], [], {}, {}
        self.bank, self.batch, self.launch, self.manifest = None, None, None, None
        self.available_observations, self.actual_promoted_skills = None, None
        self.self_attestations = None
        prior = CENTRAL / 'audit.json'
        if prior.is_file():
            previous = read(prior)
            if previous.get('schema') == 'skhynix/native004-independent-audit/1.0':
                self.anchors = previous.get('first_observed_artifact_hashes', {})

    def check(self, name, condition):
        if condition:
            self.passed += 1
            return True
        self.failures.append({'check': name})
        return False

    def require(self, name, condition):
        if not self.check(name, condition):
            raise AssertionError(name)

    def section(self, name, function):
        try:
            function()
        except AssertionError:
            pass
        except Exception as exc:
            self.failures.append({'check': name, 'error_type': type(exc).__name__})

    def pending_file(self, path, name):
        if not Path(path).is_file():
            self.pending.append(name)
            return True
        return False

    def anchor(self, path):
        path = Path(path)
        current = file_digest(path)
        if str(path) not in self.anchors:
            self.anchors[str(path)] = current
        self.require('artifact bytes retained: ' + str(path), current == self.anchors[str(path)])
        return current

    def reference(self, value, name):
        path = Path(value['path'])
        self.require(name + ': absolute unlinked file', path.is_absolute() and path.is_file()
            and not any(p.is_symlink() for p in (path, *path.parents)))
        self.require(name + ': frozen bytes', self.anchor(path) == value['sha256'])
        return path

    def plan(self, run):
        plan_path = run / 'plan.json'
        self.anchor(plan_path)
        plan = read(plan_path)
        self.require(str(run) + ': canonical plan hash',
            (run / 'plan.sha256').read_text().strip() == digest(canonical(plan)))
        source = run.parent / 'source'
        expected = plan['source_hashes']
        paths = [*source.glob('src/enterprise_memory/**/*.py'), *source.glob('scripts/*.py'),
            source / 'configs/trimem_v1/m2_candidates/recall.json', source / 'artifacts/trimem_v1/freeze.json']
        self.require(str(run) + ': complete frozen source file set',
            {p.relative_to(source).as_posix() for p in paths} == set(expected))
        for relative, value in expected.items():
            path = source / relative
            self.require(str(run) + ': source containment', source.resolve() in path.resolve().parents)
            self.check(str(run) + ': source hash ' + relative, file_digest(path) == value)
        self.sources[str(run)] = len(expected)
        self.require(str(run) + ': frozen loader validates plan', broker.load_plan(run) == plan)
        self.check(str(run) + ': fixed model limits and arms', plan['limits'] == LIMITS
            and plan['requested_solver_model'] == 'gpt-6-astra' and plan['cells'] == ARMS)
        self.check(str(run) + ': native limitation disclosure', 'native' in plan.get('l0_projection', '').lower()
            and 'protocol' in plan.get('host_isolation', '').lower())
        for key in ('supplemental_manifest', 'frozen_memory_bank', 'procedure_declaration'):
            if plan.get(key):
                path = self.reference(plan[key], str(run) + ': ' + key)
                self.check(str(run) + ': independent input containment ' + key, CENTRAL in path.parents)
        return plan


def contracts(audit):
    for name in ('launch-contract-preliminary.json', 'launch-contract.json', 'pre-execution-supersession.json',
                 'ancestry-preflight.json', 'replacement-ancestry-preflight.json'):
        if audit.pending_file(CENTRAL / name, name + ' absent'):
            return
        audit.anchor(CENTRAL / name)
    launch = audit.launch = read(CENTRAL / 'launch-contract.json')
    supersession = read(CENTRAL / 'pre-execution-supersession.json')
    audit.check('final independent cohort launch', set(launch['training_instances']) == {instance(x) for x in TRAIN}
        and set(launch['evaluation_instances']) == {instance(x) for x in EVALUATION}
        and launch['planned_evaluation_cells'] == 18 and launch['prior_memory_reused'] is False)
    audit.check('native fresh model context', launch['requested_model'] == 'gpt-6-astra'
        and launch['fork_turns'] == 'none' and launch['separate_model_api_calls'] == 0
        and launch['codex_tokens_and_cost'] is None)
    audit.check('fixed budget declaration', launch['limits'] ==
        {'actions': 120, 'wall_seconds': 1200, 'memory_injections': 3, 'memory_bytes': 12000})
    audit.check('pre-execution supersession exact cohorts',
        supersession['original_training_ids'] == ['sympy__sympy-16766', 'sympy__sympy-18763']
        and set(supersession['final_training_ids']) == {instance(x) for x in TRAIN}
        and set(supersession['evaluation_ids_unchanged']) == {instance(x) for x in EVALUATION}
        and supersession['solver_actions'] == supersession['grader_runs'] == supersession['frozen_plans'] == 0)
    audit.check('supersession exact launch references',
        supersession['final_launch_sha256'] == file_digest(CENTRAL / 'launch-contract.json')
        and supersession['preliminary_launch_sha256'] == file_digest(CENTRAL / 'launch-contract-preliminary.json'))
    for ref in supersession['preflight_evidence']:
        audit.reference(ref, 'ancestry supersession reference')
    original = read(CENTRAL / 'ancestry-preflight.json')
    replacement = read(CENTRAL / 'replacement-ancestry-preflight.json')
    rejected = [x for x in original['pairs'] if x['source'] == 'sympy__sympy-18763']
    audit.check('superseded public base is unmerged into all evaluation bases', len(rejected) == 6
        and {x['target'] for x in rejected} == {instance(x) for x in EVALUATION}
        and all(x['returncode'] == 1 for x in rejected))
    audit.check('replacement public base ancestry preflight passes',
        replacement['candidate']['id'] == 'sympy__sympy-14976'
        and len(replacement['pairs']) == 7 and all(x['returncode'] == 0 for x in replacement['pairs']))
    for kind, key in [('solver_prompt_template.txt', 'evaluation_template_sha256'),
                      ('training_solver_prompt_template.txt', 'training_template_sha256')]:
        audit.check('unchanged common native003 prompt: ' + kind, audit.anchor(CENTRAL / kind) == launch[key]
            and file_digest(CENTRAL / kind) == HISTORY['/home/trimem-runner/skhynix-codex-003/' + kind])


def manifest_and_sources(audit, plans):
    if not plans:
        audit.pending.append('Frozen training plans absent')
        return
    first = plans[0][1]
    binding = first['supplemental_manifest']
    path = audit.reference(binding, 'final supplemental manifest')
    targets, private_rows, images, manifest = dataset.load_supplemental_rows(path,
        Path(first['paths']['dataset_cache_root']), expected_sha256=binding['sha256'], root=SOURCE)
    del private_rows
    audit.manifest = manifest
    audit.check('frozen dataset loader validates source rows public candidates ancestry and images', True)
    audit.check('manifest exact final task roles', {t['target_id'] for t in targets if t['role'] == 'TRAINING'} == TRAIN
        and {t['target_id'] for t in targets if t['role'] == 'EVALUATION'} == EVALUATION and len(targets) == 8)
    audit.check('manifest has no reused training', manifest['prior_training_target'] is None
        and manifest['additional_prior_training_targets'] == [] and manifest['selection'] == dataset.NATIVE004_SELECTION)
    evidence = manifest['selection_evidence']
    audit.check('all 64 public candidates declared and hashed', len(evidence['candidates']) == 64
        and digest(canonical(evidence['candidates'])) == evidence['candidates_canonical_sha256'])
    audit.check('selection public title informed without outcome selection claim',
        manifest['selection']['content_fields_used_for_selection'] == ['problem_statement:first_line']
        and manifest['planner_llm_involved_at_selection'] is True and manifest['model_calls_at_selection'] is None
        and manifest['solver_model_calls_at_selection'] == manifest['new_target_grader_runs_at_selection'] == 0)
    final_images = read(CENTRAL / 'dataset-preparation-final/images.json')
    audit.check('final registry contains only the final eight tasks',
        {r['instance_id'] for r in final_images} == {instance(x) for x in TRAIN | EVALUATION})
    for row in final_images:
        registry = CENTRAL / 'dataset-preparation-final' / ('registry-' + row['instance_id'].rsplit('-', 1)[1] + '.json')
        audit.check('retained final registry hash: ' + row['instance_id'], file_digest(registry) == row['registry_response_sha256'])
    old_source = Path('/home/trimem-runner/skhynix-codex-003/eval-24443/source')
    guards = ['scripts/trimem_skhynix_codex_procedures.py', 'scripts/trimem_skhynix_codex_skill_bank.py',
        'scripts/trimem_skhynix_codex_memory.py', 'src/enterprise_memory/trimem/skill_memory.py']
    for relative in guards:
        audit.check('Gate B runtime and privacy guard bytes unchanged: ' + relative,
            file_digest(SOURCE / relative) == file_digest(old_source / relative))
    for run, plan in plans:
        audit.check('all runs share final manifest and frozen source ' + str(run),
            plan['supplemental_manifest'] == binding and plan['source_hashes'] == first['source_hashes'])


def runtime_evidence(audit):
    path = CENTRAL / 'dataset-preparation-final/public-runner-compatibility.json'
    if audit.pending_file(path, 'Final public runner metadata absent'):
        return
    audit.anchor(path)
    value = read(path)
    rows = {x['instance_id']: x for x in value['public_runner_fingerprints']}
    audit.check('final runner fingerprints exact cohort', set(rows) == {instance(x) for x in TRAIN | EVALUATION})
    training_hashes = {rows[instance(x)]['public_bin_test_sha256'] for x in TRAIN}
    audit.check('training public runner equal and all six evaluation runners incompatible', len(training_hashes) == 1
        and all(rows[instance(x)]['public_bin_test_sha256'] not in training_hashes for x in EVALUATION))
    audit.check('runtime evidence does not certify target fixes', value['no_problem_patch_or_test_fields_read'] is True
        and value['all_public_runner_hashes_equal'] is False)


def training_plan(audit, run):
    if audit.pending_file(run / 'plan.json', str(run) + ' plan absent'):
        return None
    plan = audit.plan(run)
    audit.check('training target is independently predeclared ' + str(run), plan['public_task']['task_id'] in TRAIN)
    cold = read(Path(plan['frozen_memory_bank']['path']))
    audit.check('training uses only new empty cold bank ' + str(run), cold['cold_start'] is True
        and cold['records'] == [] and cold['training_task_ids'] == []
        and set(cold['evaluation_task_ids']) == TRAIN and cold['gate_b']['verified_skill_count'] == 0)
    audit.check('training real procedure predeclared ' + str(run), plan['procedure_declaration'] is not None)
    for cell in ARMS:
        root = run / 'cells' / cell
        if not (root / 'state.json').is_file():
            audit.pending.append(str(root) + ' state not yet prepared')
            continue
        state = read(root / 'state.json')
        if cell != 'A':
            audit.check('only A training used ' + str(root), state['actions'] == 0 and state['started_at'] is None)
        if state.get('started_at') is not None and audit.launch:
            audit.check('contract and source frozen before training starts ' + str(root),
                audit.launch['frozen_at_unix_seconds'] < state['started_at']
                and (CENTRAL / 'pre-execution-supersession.json').stat().st_mtime < state['started_at']
                and (run / 'plan.json').stat().st_mtime < state['started_at'])
    if not audit.pending_file(run / 'cells/A/public-result.json', plan['public_task']['task_id'] + ':A training grade absent'):
        row = batch_module.verify_result_receipt(plan, run, 'A', legacy_training=True)
        audit.check('official training receipt sealed patch and broker chain ' + row['target_id'], True)
        audit.training.append({'target_id': row['target_id'], 'cell': 'A', 'resolved': row['resolved'],
            'actions': row['actions'], 'memory_injections': row['memory_injections'], 'memory_bytes': row['memory_bytes']})
        audit.check('training budget and no memory ' + row['target_id'], row['actions'] <= 120
            and row['memory_injections'] == row['memory_bytes'] == 0 and row['separate_model_api_calls'] == 0)
    return plan


def promotion(audit):
    exports = list(CENTRAL.glob('*/promoted-procedure.json'))
    if not exports:
        audit.pending.append('Actual Gate B promotion export absent')
        return
    audit.require('one independent real promotion export', len(exports) == 1)
    path = exports[0]
    audit.anchor(path)
    export = read(path)
    from enterprise_memory.trimem.skill_memory import ProcedureTemplate, Skill
    fields = dict(export['promoted_skill'])
    fields['template'] = ProcedureTemplate(**fields['template'])
    skill = Skill(**fields)
    view = skill.execution_view()
    audit.check('actual promotion status and two independent training supports',
        export['status'] == 'ACTUALLY_PROMOTED_BY_GATE_B' and export['verified_skill_count'] == 1
        and set(export['training_task_ids']) == TRAIN and skill.support_count == skill.contributor_count == 2)
    audit.check('exact public execution view without source revision rebinding', view == export['public_execution_view']
        and digest(view.encode()) == export['public_execution_view_sha256']
        and len(view.encode()) == export['public_execution_view_bytes'] and export['source_revisions_rebound'] is False)
    audit.actual_promoted_skills = export['verified_skill_count']
    authority = audit.reference(export['authority_db'], 'original private Gate AB authority')
    authority_hash = file_digest(authority)
    audit.require('authority no active mutable journals', not any(Path(str(authority) + suffix).exists()
        and Path(str(authority) + suffix).stat().st_size > 0 for suffix in ('-wal', '-journal')))
    with read_only_db(authority) as connection:
        row = connection.execute("SELECT * FROM memory_records WHERE record_id=? AND kind='skill'", (skill.skill_id,)).fetchone()
        audit.require('actual nonrevoked original promoted skill row', row is not None and row['revoked'] == 0)
        payload = json.loads(row['payload'])
        audit.check('public export exactly joins private authority hash', {**payload, 'content_hash': row['content_hash']} == export['promoted_skill']
            and 'sha256:' + digest(canonical(payload)) == row['content_hash'])
        supports = connection.execute('SELECT e.* FROM skill_support s JOIN memory_records e ON s.episode_id=e.record_id '
            'WHERE s.skill_id=? ORDER BY e.record_id', (skill.skill_id,)).fetchall()
        task_ids, users, verifiers, hashes = set(), set(), set(), []
        audit.require('two original private support rows', len(supports) == 2)
        for row in supports:
            payload = json.loads(row['payload']); evidence = payload['evidence']
            task_ids.add(evidence['task_id']); users.add(evidence['user_id']); verifiers.add(evidence['verification_evidence_hash'])
            hashes.append(row['content_hash'])
            rendered = skill.template.render(dict(evidence['parameter_bindings']))
            audit.check('original authority support hash owner revision and procedure ' + evidence['task_id'],
                'sha256:' + digest(canonical(payload)) == row['content_hash'] and row['revoked'] == 0
                and row['org_id'] == skill.org_id == evidence['org_id'] and row['owner_user_id'] == evidence['user_id']
                and row['revision'] == evidence['revision'] and evidence['procedure_hash'] == skill.template.content_hash
                and evidence['succeeded'] is True and tuple(evidence['actions']) == rendered.steps
                and evidence['verification_command'] == rendered.verification_command)
        audit.check('independent exact support and evidence hash set', task_ids == TRAIN and len(users) == len(verifiers) == 2
            and skill.evidence_set_hash == 'sha256:' + digest(canonical(hashes)))
    declaration = audit.reference(export['declaration'], 'original predeclared procedure')
    import trimem_skhynix_codex_procedures as procedures
    seen = set()
    for ref in export['attestations']:
        private = read(audit.reference(ref, 'private verifier artifact'))
        attestation = private['attestation']; task_id = attestation['task_id']; seen.add(task_id)
        run = Path(attestation['source_provenance']['run_root'])
        recomputed = procedures.attest_procedure(run, 'A', declaration, export['declaration']['sha256'])
        audit.check('frozen verifier recomputes actual RED GREEN attestation ' + task_id,
            recomputed['attestation_sha256'] == ref['attestation_sha256'] == private['attestation_sha256']
            and canonical(recomputed) == canonical(private) and digest(canonical(attestation)) == ref['attestation_sha256']
            and [x['stage'] for x in attestation['stages']] == ['INSPECT', 'ADD_REGRESSION', 'RED', 'REPAIR_IMPLEMENTATION', 'GREEN'])
    audit.check('attestations exact new cohort', seen == TRAIN)
    audit.check('authority bytes unchanged after read-only audit', file_digest(authority) == authority_hash)


def learned_bank(audit):
    path = CENTRAL / 'learned-bank.json'
    if audit.pending_file(path, 'Final frozen learned bank absent'):
        return
    audit.anchor(path)
    bank = audit.bank = read(path)
    learning._validate_observation_manifest(bank)
    audit.check('schema1 observation fallback keeps workflow unavailable', bank['schema'] == learning.SCHEMA
        and bank['gate_b']['verified_skill_count'] == 0 and bank['evaluation_private_episode_count'] == 0
        and bank['online_learning'] is False and bank['target_version_applicability_verified'] is False)
    audit.check('frozen bank exact disjoint cohort without old memory', set(bank['training_task_ids']) == TRAIN
        and set(bank['evaluation_task_ids']) == EVALUATION and not TRAIN & EVALUATION and bank['cold_start'] is False)
    audit.available_observations = len(bank['records'])
    audit.check('same public observations policy and no private payload imports',
        bank['knowledge_payload_identical_between_memory_arms'] is True and bank['patch_content_imported'] is False
        and bank['grader_test_content_imported'] is False and bank['source_selection_uses_evaluation_outcomes'] is False)
    private_store = path.with_name(bank['gate_a']['private_store_filename'])
    audit.reference({'path': str(private_store), 'sha256': bank['gate_a']['private_store_sha256']}, 'actual Gate A store')
    episodes = bank['gate_a']['episodes']
    audit.check('only two new Gate A episodes recorded', bank['gate_a']['episode_count'] == len(episodes) == 2
        and {x['source']['task_id'] for x in episodes} == TRAIN)
    admissible = {}
    for task_id in TRAIN:
        run = CENTRAL / ('training-' + task_id.rsplit('-', 1)[1]) / 'execution'
        recomputed = learning._read_training(run, 'A')
        if recomputed['admissible_shared_knowledge']:
            admissible[task_id] = recomputed
    audit.check('bank includes all and only actually admissible completed observations',
        {r['source']['task_id'] for r in bank['records']} == set(admissible)
        and len(bank['records']) == len(admissible))
    for record in bank['records']:
        original = admissible[record['source']['task_id']]
        audit.check('exact recomputed public observation bytes and original provenance ' + record['source']['task_id'],
            original['provenance'] == record['source'] and original['content'] == record['content']
            and record['content_sha256'] == digest(record['content'].encode())
            and record['content_bytes'] == len(record['content'].encode()))


def projected_injection_views(audit, root, plan, cell):
    """Join raw shared observations to each arm's exact frozen wire format."""
    from enterprise_memory.trimem.skill_memory import RepositoryKnowledge
    from enterprise_memory.trimem.skill_runtime import SkillFirstMemoryController, SkillLayer
    label = plan['public_task']['task_id'] + ':' + cell
    records = audit.bank['records']
    originals = {x['memory_id']: x for x in records}
    expected_raw_views = {key: row['content'] for key, row in originals.items()}
    report = read(root / 'bank-projection.json')
    bank_report = report['bank']
    audit.check('actual available candidate count ' + label,
        bank_report['records'] == (0 if cell == 'A' else len(originals))
        and bank_report['verified_skill_count'] == 0 and bank_report['imported_episode_count'] == 0)
    audit.check('projection outer identity and privacy contract ' + label,
        report['arm'] == ARMS[cell] and report['task_id'] == plan['public_task']['task_id']
        and report['seed_episode_count'] == report['seed_skill_count'] == 0
        and report['experience_writes'] is False and report['model_api_calls'] == 0)
    if cell == 'A':
        return {}
    projection = read(root / 'memory-private/historical-source-projection.json')
    audit.check('exact identical available public observation candidates ' + label,
        projection['execution_views'] == expected_raw_views and projection['validation']['verified_skill_count'] == 0
        and bank_report['source_projection_sha256'] == digest(canonical(projection))
        and bank_report['frozen_bank_sha256'] == plan['frozen_memory_bank']['sha256']
        and set(bank_report['training_task_ids']) == TRAIN)
    if cell == 'B':
        return {key: (row['content'], 'ORG_SEMANTIC') for key, row in originals.items()}
    database = root / 'memory-private/source-memory.sqlite3'
    initial = file_digest(database)
    with read_only_db(database) as connection:
        counts = dict(connection.execute('SELECT kind,COUNT(*) FROM memory_records GROUP BY kind').fetchall())
        knowledge = connection.execute("SELECT * FROM memory_records WHERE kind='knowledge'").fetchall()
    audit.check('evaluation C contains exactly public knowledge and no private episodes or skills ' + label,
        counts == {'knowledge': len(originals)})
    audit.check('evaluation source DB remains unchanged by audit ' + label, file_digest(database) == initial)
    entries = bank_report['entries']
    audit.require('C transfer entries preserve exact shared source set ' + label,
        len(entries) == len(originals) and {x['memory_id'] for x in entries} == set(originals)
        and len({x['knowledge_id'] for x in entries}) == len(originals))
    by_knowledge_id = {x['record_id']: x for x in knowledge}
    audit.require('C exact knowledge authority row set ' + label,
        set(by_knowledge_id) == {x['knowledge_id'] for x in entries})
    expected_injections = {}
    for entry in entries:
        original = originals[entry['memory_id']]
        audit.check('C historical provenance and content bytes preserved ' + label + ':' + entry['memory_id'],
            entry['shared_source_content_bytes'] == original['content_bytes'] == len(original['content'].encode())
            and entry['shared_source_content_sha256'] == original['content_sha256'] == digest(original['content'].encode())
            and entry['source_revision'] == original['source']['revision']
            and entry['transfer_view_revision'] == plan['public_task']['commit'])
        data = {'org_id': plan['experiment_id'], 'repository': plan['public_task']['repository'],
            'title': original['title'], 'content': original['content'], 'revision': plan['public_task']['commit'],
            'language': original['language']}
        expected_id = 'knowledge:' + digest(canonical(data))
        payload = {'knowledge_id': expected_id, **data}
        row = by_knowledge_id[entry['knowledge_id']]
        audit.require('C immutable authority content identity and target projection ' + label + ':' + entry['memory_id'],
            row['record_id'] == entry['knowledge_id'] == expected_id and json.loads(row['payload']) == payload
            and row['content_hash'] == 'sha256:' + digest(canonical(payload)) and row['revoked'] == 0
            and row['org_id'] == plan['experiment_id'] and row['repository'] == plan['public_task']['repository']
            and row['revision'] == plan['public_task']['commit'] and row['owner_user_id'] is None)
        public_row = RepositoryKnowledge(**payload, content_hash=row['content_hash'])
        # This pure renderer reads no store and executes no procedure.
        view = SkillFirstMemoryController._execution_view(None, public_row, SkillLayer.REPOSITORY_SEMANTIC)
        audit.check('C exact frozen serialized execution view preserves raw observation ' + label + ':' + entry['memory_id'],
            json.loads(view) == {'layer': 'REPOSITORY_SEMANTIC', 'title': original['title'],
                'content': original['content'], 'revision': plan['public_task']['commit']})
        expected_injections[expected_id] = (view, 'REPOSITORY_SEMANTIC')
    return expected_injections


def evaluation_cell(audit, run, plan, cell):
    task_id = plan['public_task']['task_id']; label = task_id + ':' + cell
    root = run / 'cells' / cell
    if audit.pending_file(root / 'state.json', label + ' state absent'):
        return
    state = read(root / 'state.json')
    public = read(root / 'public-task.json')
    audit.check('evaluation has no private training instructions ' + label,
        not any(k in public for k in ('procedure_declaration', 'procedure_instructions', 'training_procedure', 'procedure_guidance')))
    expected_injections = projected_injection_views(audit, root, plan, cell) if audit.bank else {}
    if state.get('started_at') is not None:
        frozen_paths = [CENTRAL / 'launch-contract.json', CENTRAL / 'batch-plan.json', run / 'plan.json',
            Path(plan['frozen_memory_bank']['path']), Path(plan['supplemental_manifest']['path'])]
        audit.check('all contracts bank manifest and batch frozen before first cell action ' + label,
            audit.launch['frozen_at_unix_seconds'] < state['started_at']
            and all(p.stat().st_mtime < state['started_at'] for p in frozen_paths))
    if audit.pending_file(root / 'public-result.json', label + ' official grade missing'):
        return
    row = batch_module.verify_result_receipt(plan, run, cell)
    audit.check('official verdict sealed patch and complete broker chain ' + label, True)
    audit.check('actual action and memory budgets ' + label, row['actions'] <= 120
        and row['memory_injections'] <= 3 and row['memory_bytes'] <= 12000)
    audit.check('native cost and API disclosure ' + label,
        row['separate_model_api_calls'] == 0 and row['codex_tokens_and_cost'] is None)
    events, tail = broker.audit_events(root)
    exposure_count, workflow_count = 0, 0
    for event in events:
        if event['request'].get('op') != 'recall' or not event['result'].get('ok'):
            continue
        for item in event['result']['result'].get('injections', []):
            exposure_count += 1
            workflow_count += int(item['kind'] == 'SKILL')
            audit.check('actual injection exact UTF8 hash and frozen public payload ' + label + ':' + str(event['sequence']),
                len(item['exact_text'].encode()) == item['byte_count'] and digest(item['exact_text'].encode()) == item['sha256']
                and expected_injections.get(item['memory_id']) == (item['exact_text'], item['kind']))
    audit.check('zero actual workflow skill injection for incompatible evaluation ' + label, workflow_count == 0)
    if cell == 'A':
        audit.check('baseline has zero actual memory exposure ' + task_id, row['memory_injections'] == row['memory_bytes'] == 0)
    audit.rows.append({'target_id': task_id, 'cell': cell, 'arm': ARMS[cell], 'status': 'COMPLETE',
        'resolved': row['resolved'], 'actions': row['actions'], 'memory_injections': row['memory_injections'],
        'memory_bytes': row['memory_bytes'], 'observation_exposures_including_replay': exposure_count,
        'workflow_exposures_including_replay': workflow_count, 'available_observation_candidates': 0 if cell == 'A' else audit.available_observations,
        'available_workflow_candidates': 0, 'patch_sha256': row['patch_sha256']})


def evaluation(audit):
    if audit.pending_file(CENTRAL / 'batch-plan.json', 'Evaluation batch freeze absent'):
        return
    audit.anchor(CENTRAL / 'batch-plan.json')
    batch = audit.batch = read(CENTRAL / 'batch-plan.json')
    audit.require('batch canonical freeze hash',
        (CENTRAL / 'batch-plan.json.sha256').read_text().strip() == digest(canonical(batch)))
    audit.check('exact two training tasks six evaluation tasks and 18-cell denominator',
        {x['target_id'] for x in batch['training']} == TRAIN and len(batch['training']) == 2
        and {x['target_id'] for x in batch['evaluation']} == EVALUATION and len(batch['evaluation']) == 6
        and batch['planned_cells'] == 18 and batch['planned_targets'] == 6)
    batch_module.validate_split(batch['contract'], TRAIN, EVALUATION)
    audit.check('frozen batch manifest and bank task joins validate', True)
    for training in batch['training']:
        run = Path(training['run_root'])
        audit.check('batch training original plan and receipt hash ' + training['target_id'], training['cell'] == 'A'
            and training['plan_sha256'] == digest(canonical(read(run / 'plan.json')))
            and training['result_sha256'] == file_digest(run / 'cells/A/public-result.json'))
    for entry in batch['evaluation']:
        run = Path(entry['run_root'])
        def inspect_run():
            plan = audit.plan(run)
            audit.check('evaluation batch original plan hash ' + entry['target_id'],
                digest(canonical(plan)) == entry['plan_sha256'])
            audit.check('all evaluation common frozen contract ' + entry['target_id'],
                plan['limits'] == batch['contract']['limits'] and plan['source_hashes'] == batch['contract']['source_hashes']
                and plan['frozen_memory_bank'] == batch['contract']['frozen_memory_bank']
                and plan['supplemental_manifest'] == batch['contract']['supplemental_manifest']
                and plan['procedure_declaration'] is None)
            binding = plan['frozen_memory_bank']
            loaded = learning.load_frozen_bank(Path(binding['path']), binding['sha256'], broker.task_from_plan(plan))
            audit.check('frozen bank loader validates exact evaluation identity ' + entry['target_id'], loaded.promoted_skill is None)
            for cell in ARMS:
                audit.section('evaluation cell ' + entry['target_id'] + ':' + cell,
                    lambda cell=cell: evaluation_cell(audit, run, plan, cell))
        audit.section('evaluation plan ' + entry['target_id'], inspect_run)


def final_report(audit):
    path = CENTRAL / 'batch-report.json'
    if audit.pending_file(path, 'Final batch report absent'):
        return
    report = read(path)
    complete = len(audit.rows) == 18
    audit.check('batch report retains complete planned denominator', report['planned_cells'] == 18
        and report['planned_targets'] == 6 and report['completed_cells'] == len(audit.rows)
        and report['status'] == ('COMPLETE' if complete else 'INCOMPLETE'))
    if complete:
        for arm in ARMS.values():
            selected = [x for x in audit.rows if x['arm'] == arm]
            comparison = report['comparison'][arm]
            audit.check('actual paired denominator and measured outcomes ' + arm, comparison['n'] == len(selected) == 6
                and comparison['resolved'] == sum(x['resolved'] for x in selected)
                and comparison['memory_injections'] == sum(x['memory_injections'] for x in selected)
                and comparison['memory_bytes'] == sum(x['memory_bytes'] for x in selected))


def solver_attestations(audit):
    path = CENTRAL / 'solver-attestations.json'
    if audit.pending_file(path, 'Solver self-attestations not yet collected'):
        return
    wrapper = read(path)
    audit.require('self-attestation wrapper native identity',
        wrapper['schema'] == 'skhynix/native-solver-self-attestations/1.0'
        and wrapper['requested_model'] == 'gpt-6-astra' and wrapper['fork_turns'] == 'none'
        and wrapper['source'] == 'ROOT_TRANSCRIPTION_OF_ACTUAL_AGENT_FINAL_MESSAGES')
    rows = wrapper['attestations']
    planned = {('training-' + t.rsplit('-', 1)[1], 'A') for t in TRAIN}
    planned.update(('eval-' + t.rsplit('-', 1)[1], cell) for t in EVALUATION for cell in ARMS)
    seen, agents = set(), set()
    for row in rows:
        identity = row['run'], row['cell']
        label = ':'.join(identity)
        audit.require('self-attestation unique predeclared cell and native agent ' + label,
            identity in planned and identity not in seen and row['agent'] not in agents)
        seen.add(identity); agents.add(row['agent'])
        root = CENTRAL / row['run'] / 'execution/cells' / row['cell']
        submission = read(root / 'submission.json')
        audit.check('self-reported protocol and original sealed patch join ' + label,
            row['only_assigned_broker'] is True and row['no_subagents'] is True and row['no_external_access'] is True
            and row['patch_sha256'] == submission['patch_sha256'] == file_digest(root / 'submission.diff'))
    missing = planned - seen
    if missing:
        audit.pending.append('Solver self-attestations not yet collected for ' + str(len(missing)) + ' planned cells')
    audit.self_attestations = {'path': str(path), 'sha256': file_digest(path),
        'planned_sessions': len(planned), 'collected_sessions': len(seen), 'distinct_agent_ids': len(agents),
        'missing_sessions': [':'.join(x) for x in sorted(missing)],
        'scope': 'SELF_REPORTED_PROTOCOL_EVIDENCE_NOT_INDEPENDENT_BACKEND_OR_HOST_ATTESTATION'}


def finish(audit):
    status = 'FAIL' if audit.failures else ('PENDING' if audit.pending or len(audit.rows) != 18 else 'PASS_FINAL')
    completed = {(x['target_id'], x['cell']): x for x in audit.rows}
    cells = [completed.get((target, cell), {'target_id': target, 'cell': cell, 'arm': ARMS[cell], 'status': 'PENDING'})
        for target in sorted(EVALUATION) for cell in ARMS]
    output = {'schema': 'skhynix/native004-independent-audit/1.0', 'status': status,
        'audit_at_unix_seconds': time.time(), 'audit_helper_sha256': file_digest(__file__),
        'checks_passed': audit.passed, 'checks_failed': len(audit.failures),
        'failures': audit.failures, 'pending': audit.pending, 'planned_cells': 18, 'completed_cells': len(audit.rows),
        'source_hash_counts': audit.sources, 'training_tasks': sorted(TRAIN), 'evaluation_tasks': sorted(EVALUATION),
        'training_results': audit.training, 'cells': cells, 'actual_promoted_skill_count': audit.actual_promoted_skills,
        'available_observation_records': audit.available_observations, 'evaluation_workflow_candidate_count': 0,
        'first_observed_artifact_hashes': audit.anchors, 'historical_artifact_hashes': HISTORY,
        'solver_self_attestations': audit.self_attestations, 'model_api_calls': 0, 'grader_calls': 0, 'container_calls': 0,
        'authority_mutations': 0, 'private_payloads_exported': False,
        'audit_schema_correction': {
            'preserved_preliminary_path': str(CENTRAL / 'audit-preliminary-schema-error.json'),
            'preserved_preliminary_sha256': file_digest(CENTRAL / 'audit-preliminary-schema-error.json'),
            'changes': ['Read bank projection counts from the actual nested bank object.',
                'Validate B raw observation injections and C exact serialized repository-semantic execution views.',
                'Join C execution views to immutable knowledge rows and original shared content and provenance hashes.',
                'Read actual solver self-attestations from their wrapper list and join each sealed submission.'],
            'frozen_experiment_artifacts_modified_for_correction': False},
        'limitations': ['Public-title-informed hand-selected exploratory cohort; not random or a proven difficulty sample.',
            'Ancestry certifies historical base commits, not upstream merge of native training patches.',
            'Actual training promotion does not imply compatible evaluation workflow injection.',
            'B and C share raw observation candidates; C serializes a repository-semantic wrapper, so injection bytes can differ.',
            'All 18 planned cells remain in the denominator; no required solve rate or assumed lift.',
            'Contributor independence means distinct native sessions, not distinct human users.',
            'Requested native model is metadata, not an independently attested backend snapshot.',
            'Host restrictions are protocol rules and native context is not the PDF L0 projection.',
            'Private payloads are checked internally by frozen verifiers and authority joins, never exported.']}
    (CENTRAL / 'audit.json').write_bytes(canonical(output) + b'\n')
    print(json.dumps({'status': status, 'checks_passed': audit.passed, 'checks_failed': len(audit.failures),
        'completed_cells': len(audit.rows), 'planned_cells': 18, 'pending': len(audit.pending)}))


def main():
    global ACTIVE_AUDIT, SOURCE, broker, batch_module, dataset, learning
    audit = ACTIVE_AUDIT = Audit()
    for path, expected in HISTORY.items():
        audit.section('historical retention', lambda path=path, expected=expected:
            audit.check('historical bytes retained: ' + path, file_digest(path) == expected))
    audit.section('launch and supersession', lambda: contracts(audit))
    SOURCE = CENTRAL / 'training-14976/source'
    if not SOURCE.is_dir():
        audit.pending.append('Original frozen implementation absent')
        finish(audit)
        return
    sys.path[:0] = [str(SOURCE / 'src'), str(SOURCE / 'scripts')]
    import trimem_skhynix_codex as broker
    import trimem_skhynix_codex_batch as batch_module
    import trimem_skhynix_native_dataset as dataset
    import trimem_skhynix_codex_learning as learning
    broker.block_model_client()
    plans = []
    for number in ('14976', '16766'):
        run = CENTRAL / ('training-' + number) / 'execution'
        def inspect_training():
            plan = training_plan(audit, run)
            if plan:
                plans.append((run, plan))
        audit.section('training-' + number, inspect_training)
    audit.section('manifest and source guards', lambda: manifest_and_sources(audit, plans))
    audit.section('public runtime evidence', lambda: runtime_evidence(audit))
    audit.section('actual Gate B promotion', lambda: promotion(audit))
    audit.section('learned observation bank', lambda: learned_bank(audit))
    audit.section('evaluation batch', lambda: evaluation(audit))
    audit.section('reported outcomes', lambda: final_report(audit))
    audit.section('solver self-attestation joins', lambda: solver_attestations(audit))
    finish(audit)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        failure = globals().get('ACTIVE_AUDIT', Audit())
        if not isinstance(exc, AssertionError):
            failure.failures.append({'check': 'audit execution', 'error_type': type(exc).__name__})
        finish(failure)
