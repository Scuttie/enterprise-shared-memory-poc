"""Independent native005 evidence audit; only writes CENTRAL/audit.json.

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
import re
import sqlite3
import subprocess
import time
import xml.etree.ElementTree as ET

CENTRAL = Path('/home/trimem-runner/skhynix-codex-005')
PREFIX = 'swebench_verified--sympy__sympy-'
TRAIN = {PREFIX + x for x in ('19637', '19783')}
EVALUATION = {PREFIX + x for x in ('19954', '20154', '20428', '20438', '20801', '21379')}
ARMS = {'A': 'NO_MEMORY', 'B': 'EXISTING_M2', 'C': 'SKHYNIX'}
LIMITS = {'repository_actions': 120, 'wall_seconds': 1200, 'memory_injections': 3, 'memory_bytes': 12000}
RUNNER = 'da4284cc210d8db5109f916248d97a8e82f725547e60c5d9a4d6c43573e3e9d5'
PYTHON_VERSION = 'Python 3.9.20'
PUBLIC004 = Path('/mnt/c/Users/jewon/esm-r23-d115-writer/artifacts/skhynix_v1/codex_004')
PUBLIC004_MANIFEST_SHA = '16aed415a21123511e9ce2f7faacf17c0d83a812695d509a0ffb1374ed21f9d7'
INITIAL_NATIVE005_HASHES = {
    'public-selection-final.json': 'c5213c1b93ae018e7b0c08bc80f498f9b64e45912308c52fae8004f75860065e',
    'launch-contract.json': '0aa79fa5e8fea1d2534ace2999825065314e6a91bd545a3216fa0676f3b27f08',
    'dataset-preparation-final/runtime-screening.json': '3c860c2964a4f679c417eabc9855cec0b88e11bbb2f44c926cd10c35e284f0a3',
    'synthetic-query-contract.json': '66b7e99489fefc3bac7d64bfa4a64f8ddb1de5e9eaff5e9488059ff24c29f862',
    'supplemental-manifest.json': '57f369ee641b923ec551698fb52f043e7cf8569e4872f0f691883f47d399f6b9',
    'procedure-declaration.json': '33a2a7641f77cf8b93afe003d59c1c1e88d1749ff70fb28cdd6b07fcdc06e687',
    'cold-bank.json': '27f4a3c58fcbacd91658505b9459a1dc264c6106099f237b06b413e2a374d600',
}
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
        self.skill, self.skill_view, self.certificates = None, None, {}
        self.runtime_rows, self.gates = {}, {}
        self.terminal_gated = (CENTRAL / 'training-gate-decision.json').is_file()
        self.terminal_evidence, self.validation_evidence = None, None
        prior = CENTRAL / 'audit.json'
        if prior.is_file():
            previous = read(prior)
            if previous.get('schema') == 'skhynix/native005-independent-audit/1.0':
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


def retained_native004(audit):
    manifest_path = PUBLIC004 / 'public-artifact-manifest.json'
    audit.require('native004 public manifest original bytes', file_digest(manifest_path) == PUBLIC004_MANIFEST_SHA)
    manifest = read(manifest_path)
    audit.require('native004 all 170 public files retained', len(manifest['files']) == manifest['file_count'] == 170)
    for row in manifest['files']:
        path = PUBLIC004 / row['path']
        audit.require('native004 artifact path containment', PUBLIC004.resolve() in path.resolve().parents)
        audit.check('native004 retained public bytes ' + row['path'], file_digest(path) == row['sha256']
            and path.stat().st_size == row['bytes'])
        audit.check('native004 retained original bytes ' + row['path'], file_digest(row['source']) == row['sha256'])


def contracts(audit):
    for name in ('launch-contract-preliminary.json', 'launch-contract.json', 'pre-execution-supersession.json',
                 'public-selection.json', 'public-selection-final.json'):
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
    audit.check('pre-execution supersession exact cohorts and no outcomes',
        set(supersession['new_training']) == {instance(x) for x in TRAIN}
        and set(supersession['new_evaluation']) == {instance(x) for x in EVALUATION}
        and supersession['solver_model_calls'] == supersession['grader_calls'] == supersession['plans_created'] == 0
        and supersession['manifest_created'] is False and supersession['guards_relaxed'] is False
        and supersession['prior_artifacts_preserved'] is True)
    audit.check('supersession exact launch references',
        supersession['new_contract_sha256'] == file_digest(CENTRAL / 'launch-contract.json')
        and supersession['old_contract_sha256'] == file_digest(CENTRAL / 'launch-contract-preliminary.json')
        and supersession['new_public_selection_sha256'] == file_digest(CENTRAL / 'public-selection-final.json')
        and supersession['old_public_selection_sha256'] == file_digest(CENTRAL / 'public-selection.json'))
    audit.check('same unchanged strict prerequisites declared before training',
        launch['before_training_gate']['all_eight_runner_sha256'] == RUNNER
        and launch['before_training_gate']['all_eight_python_version'] == '3.9.20'
        and launch['before_training_gate']['ancestry_checks'] == 13
        and 'no observation-only fallback' in launch['before_evaluation_gate'].lower())
    for name, expected in INITIAL_NATIVE005_HASHES.items():
        audit.check('externally pinned pre-model artifact ' + name, audit.anchor(CENTRAL / name) == expected)
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
        and manifest['additional_prior_training_targets'] == [] and manifest['selection'] == dataset.NATIVE005_SELECTION)
    evidence = manifest['selection_evidence']
    audit.check('all 56 public candidates declared and hashed', len(evidence['candidates']) == 56
        and digest(canonical(evidence['candidates'])) == evidence['candidates_canonical_sha256'])
    ancestry = manifest['ancestry']
    audit.check('all thirteen chronological ancestral base pairs validated', len(ancestry) == 13
        and all(r['returncode'] == 0 and r['source_commit_unix_seconds'] < r['target_commit_unix_seconds']
            for r in ancestry))
    audit.check('selection without outcome selection claim',
        manifest['selection']['content_fields_used_for_selection'] == ['public_git:bin/test:sha256']
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
        'scripts/trimem_skhynix_codex_memory.py', 'scripts/trimem_skhynix_codex_learning.py',
        'src/enterprise_memory/trimem/skill_memory.py', 'src/enterprise_memory/trimem/skill_runtime.py']
    for relative in guards:
        audit.check('Gate B runtime and privacy guard bytes unchanged: ' + relative,
            file_digest(SOURCE / relative) == file_digest(old_source / relative))
    for run, plan in plans:
        audit.check('all runs share final manifest and frozen source ' + str(run),
            plan['supplemental_manifest'] == binding and plan['source_hashes'] == first['source_hashes'])


def runtime_evidence(audit):
    path = CENTRAL / 'dataset-preparation-final/runtime-screening.json'
    if audit.pending_file(path, 'Final public runtime screening absent'):
        return
    audit.anchor(path)
    screening = read(path)
    selection = read(CENTRAL / 'public-selection-final.json')
    audit.check('all public candidates and runner evidence frozen', len(selection['candidates']) == 56
        and digest(canonical(selection['candidates'])) == selection['candidate_canonical_sha256']
        and len(selection['runner_evidence']) == 56
        and digest(canonical(selection['runner_evidence'])) == selection['runner_evidence_canonical_sha256'])
    candidates = {r['instance_id']: r for r in selection['candidates']}
    runners = {r['instance_id']: r for r in selection['runner_evidence']}
    audit.require('candidate and public runner identities exactly joined', len(candidates) == len(runners) == 56
        and set(candidates) == set(runners))
    for key, row in runners.items():
        audit.check('public runner source identity ' + key,
            row['base_commit'] == candidates[key]['base_commit'] and row['runner_path'] == 'bin/test')
    eligible_runner = {k for k, r in runners.items() if r['runner_sha256'] == RUNNER}
    audit.check('public runner screening count and unavailable candidate retained', len(eligible_runner) == 14
        and len([r for r in runners.values() if r['runner_sha256'] == '973e3cf784388b8e7821e4962da8eeb4b615447cd652af920452b322bd63588c']) == 41
        and runners['sympy__sympy-20590']['runner_sha256'] is None)
    rows = audit.runtime_rows = {r['instance_id']: r for r in screening['images']}
    audit.require('all 14 matching-runner images inspected before selection', set(rows) == eligible_runner
        and len(rows) == screening['requested_image_count'] == screening['screened_image_count'] == 14)
    audit.check('runtime screening original bytes and no solver or grader calls',
        selection['runtime_screening'] == screening
        and selection['runtime_screening_raw_sha256'] == file_digest(path)
        and screening['solver_model_calls'] == screening['new_grader_calls'] == 0
        and selection['solver_model_calls'] == selection['grader_calls'] == 0)
    for key, row in rows.items():
        runtime = audit.reference({'path': row['runtime_evidence_path'], 'sha256': row['runtime_evidence_sha256']}, 'public runtime ' + key)
        receipt = read(runtime)
        audit.reference({'path': row['registry_evidence_path'], 'sha256': row['registry_response_sha256']}, 'registry ' + key)
        verification = read(audit.reference({'path': row['digest_verification_evidence_path'],
            'sha256': row['digest_verification_evidence_sha256']}, 'image digest receipt ' + key))
        audit.check('actual pinned image digest inspected ' + key, verification['instance_id'] == key
            and verification['image'] == row['image'] and verification['pull_returncode'] == 0
            and row['image'] in verification['repo_digests'])
        audit.check('exact observed public image runtime ' + key, receipt == row['public_preflight']
            and receipt['instance_id'] == key and receipt['image'] == row['image']
            and receipt['network'] == 'none' and receipt['read_only_container'] is True
            and receipt['returncode'] == row['public_runner_preflight_returncode'] == 0
            and receipt['stdout'].splitlines() == [RUNNER + '  /testbed/bin/test', row['python_version']]
            and row['runner_sha256'] == RUNNER and row['repo_digest_verified'] is True
            and '@' + row['image_digest'] in row['image'])
        eligible = row['runner_sha256'] == RUNNER and row['python_version'] == PYTHON_VERSION
        audit.check('strict original Python predicate applied ' + key, row['eligible'] is eligible)
    eligible_ids = {k for k, r in rows.items() if r['eligible']}
    audit.check('exact one incompatible image and thirteen eligible', len(eligible_ids) == screening['eligible_image_count'] == 13
        and set(rows) - eligible_ids == {'sympy__sympy-19495'}
        and rows['sympy__sympy-19495']['python_version'] == 'Python 3.9.21'
        and set(selection['runtime_screening_eligible_ids']) == eligible_ids)
    audit.check('final selection exact eligible cohort without prior memory',
        set(selection['training_ids']) == {instance(x) for x in TRAIN}
        and set(selection['evaluation_ids']) == {instance(x) for x in EVALUATION}
        and set(selection['selected_ids']) == {instance(x) for x in TRAIN | EVALUATION}
        and set(selection['selected_ids']) <= eligible_ids)
    for name in ('compatibility/before-training-gate.json', 'synthetic-query-contract.json'):
        if not audit.pending_file(CENTRAL / name, name + ' not yet frozen'):
            audit.anchor(CENTRAL / name)
            audit.gates[name] = read(CENTRAL / name)


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
                and (CENTRAL / 'synthetic-query-contract.json').stat().st_mtime < state['started_at']
                and (CENTRAL / 'compatibility/before-training-gate.json').stat().st_mtime < state['started_at']
                and (run / 'plan.json').stat().st_mtime < state['started_at'])
    if not audit.pending_file(run / 'cells/A/public-result.json', plan['public_task']['task_id'] + ':A training grade absent'):
        row = batch_module.verify_result_receipt(plan, run, 'A', legacy_training=True)
        audit.check('official training receipt sealed patch and broker chain ' + row['target_id'], True)
        audit.training.append({'target_id': row['target_id'], 'cell': 'A', 'resolved': row['resolved'],
            'actions': row['actions'], 'memory_injections': row['memory_injections'], 'memory_bytes': row['memory_bytes']})
        audit.check('training budget and no memory ' + row['target_id'], row['actions'] <= 120
            and row['memory_injections'] == row['memory_bytes'] == 0 and row['separate_model_api_calls'] == 0
            and row['codex_tokens_and_cost'] is None and (audit.terminal_gated or row['resolved'] is True))
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
    audit.skill, audit.skill_view = skill, view
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
    import trimem_skhynix_codex_skill_bank as skill_bank
    base, export, skill, receipts = skill_bank._validate_manifest(bank)
    audit.check('strict schema2 authority and runtime loader validates unchanged composition', True)
    audit.check('schema2 actual promoted workflow retained without fallback', bank['schema'] == skill_bank.SCHEMA
        and bank['gate_b']['verified_skill_count'] == 1 and bank['evaluation_private_episode_count'] == 0
        and bank['online_learning'] is False and bank['target_version_applicability_verified'] is False)
    audit.reference(bank['base_observation_bank'], 'original observation bank')
    audit.reference(bank['promoted_export'], 'original promotion export')
    audit.check('strict skill privacy projection policy unchanged', bank['skill_projection'] == skill_bank.POLICY
        and audit.skill == skill and audit.skill_view == export['public_execution_view'])
    audit.certificates = receipts
    audit.check('exact six compatible evaluation targets', set(receipts) == EVALUATION)
    for ref in bank['compatibility_receipts']:
        receipt = read(audit.reference(ref, 'public workflow compatibility'))
        observation = read(audit.reference(receipt['evidence_ref'], 'actual public compatibility observation'))
        audit.check('actual observed clean public test result hash ' + receipt['target']['task_id'],
            digest(canonical(observation.get('result', observation))) == receipt['public_test']['observation_sha256'])
        audit.check('exact unchanged training and evaluation runner match ' + receipt['target']['task_id'],
            receipt['runner_sha256'] == RUNNER and export['training_runner_sha256'] == [RUNNER])
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
    from dataclasses import asdict
    initial = file_digest(private_store)
    with read_only_db(private_store) as connection:
        rows = connection.execute('SELECT * FROM memory_records').fetchall()
    by_id = {r['record_id']: r for r in rows}
    audit.require('Gate A contains only the two independently observed private episodes', len(rows) == 2
        and set(by_id) == {r['episode_id'] for r in episodes} and all(r['kind'] == 'episode' for r in rows))
    for episode in episodes:
        original = admissible[episode['source']['task_id']]
        row = by_id[episode['episode_id']]
        payload = json.loads(row['payload'])
        audit.check('actual Gate A private episode hash and original evidence ' + episode['source']['task_id'],
            payload['episode_id'] == row['record_id'] == episode['episode_id']
            and canonical(payload['evidence']) == canonical(asdict(original['episode']))
            and row['content_hash'] == episode['content_hash'] == 'sha256:' + digest(canonical(payload))
            and episode['source'] == original['provenance'] and row['revoked'] == 0
            and row['owner_user_id'] == original['episode'].user_id and row['revision'] == original['episode'].revision)
    audit.check('Gate A private authority bytes unchanged by audit', file_digest(private_store) == initial)


def pre_evaluation_gate(audit):
    path = CENTRAL / 'skill-delivery-preflight.json'
    if audit.pending_file(path, 'Synthetic delivery gate not yet recorded'):
        return
    audit.anchor(path)
    # The root is preparing this independent non-evaluation receipt. Do not
    # silently accept an unknown future schema as proof of successful delivery.
    audit.pending.append('Synthetic delivery receipt exists; exact receipt schema audit integration required')


def before_training_gate(audit):
    gate_path = CENTRAL / 'compatibility/before-training-gate.json'
    gate = read(gate_path)
    audit.anchor(gate_path)
    rows = gate['all_eight_runtime_checks']
    audit.require('eight actual public smoke checks precede training plans', gate['status'] == 'PASS'
        and gate['all_clean'] is True and gate['same_runner_and_python'] is True
        and gate['solver_model_calls'] == gate['grader_calls'] == gate['plans_created'] == 0
        and len(rows) == 8 and {r['target_id'] for r in rows} == TRAIN | EVALUATION)
    path_list = CENTRAL / 'compatibility/all-public-preflight-paths.json'
    audit.anchor(path_list)
    audit.check('eight original compatibility certificate paths', set(read(path_list)) == {r['certificate'] for r in rows})
    argv = ['/opt/miniconda3/envs/testbed/bin/python', 'bin/test', 'sympy/core/tests/test_basic.py', '--no-colors', '--no-subprocess']
    for row in rows:
        path = Path(row['certificate'])
        audit.require('public certificate contained in this independent run', CENTRAL in path.parents)
        audit.anchor(path)
        certificate = read(path)
        evidence_path = audit.reference(certificate['evidence_ref'], 'pre-training public evidence ' + row['target_id'])
        evidence = read(evidence_path)
        result = evidence['result']
        image = audit.runtime_rows[instance(row['target_id'])]['image']
        audit.check('exact successful clean runtime receipt ' + row['target_id'],
            row['role'] == ('TRAINING' if row['target_id'] in TRAIN else 'EVALUATION')
            and row['status'] == certificate['status'] == 'PASS'
            and row['python_version'] == certificate['python_version'] == evidence['python_version'] == '3.9.20'
            and row['runner_sha256'] == certificate['runner_sha256'] == evidence['runner_sha256'] == RUNNER
            and certificate['target'] == evidence['target'] and certificate['target']['task_id'] == row['target_id']
            and certificate['source_image'] == evidence['source_image'] == image
            and certificate['clean_checkout_before_after'] is evidence['clean_checkout_before_after'] is True
            and certificate['target_fix_validated'] is evidence['target_fix_validated'] is False
            and certificate['solver_actions_used'] == evidence['solver_actions_used'] == evidence['model_api_calls'] == 0
            and result['argv'] == evidence['argv'] == certificate['public_test']['argv'] == argv
            and certificate['public_test']['exit_code'] == result['exit_code'] == 0
            and result['timed_out'] is False and result['output_truncated'] is False
            and certificate['public_test']['observation_sha256'] == digest(canonical(result))
            and certificate['public_test']['passed_count'] == row['passed'] > 0
            and re.search(r'\b' + str(row['passed']) + r' passed\b', result['stdout']) is not None
            and evidence['python_version_result']['exit_code'] == 0
            and evidence['python_version_result']['stdout'].strip() == '3.9.20'
            and path.stat().st_mtime <= gate_path.stat().st_mtime
            and evidence_path.stat().st_mtime <= gate_path.stat().st_mtime)
    for task_id in TRAIN:
        run = CENTRAL / ('training-' + task_id.rsplit('-', 1)[1]) / 'execution'
        audit.check('all eight public checks finished before training plan ' + task_id,
            gate_path.stat().st_mtime < (run / 'plan.json').stat().st_mtime)


def validation_xml(audit):
    base = PUBLIC004.parent
    expected = {
        'codex_005_dataset_validation.xml': ('4fe8201eeb2155977090c7dfaa8c3fdb8c2b429e2fc4c466815e045088ec0f9a', 166),
        'codex_005_integration_validation.xml': ('063b3892557b14941950158f2b70bdc9622d872a8aff894773f22e6c16a346bf', 158),
    }
    seen, receipts = set(), []
    for name, (expected_sha, count) in expected.items():
        path = base / name
        audit.require('original regression validation XML bytes ' + name, audit.anchor(path) == expected_sha)
        root = ET.parse(path).getroot()
        cases = root.findall('.//testcase')
        suites = root.findall('.//testsuite')
        audit.check('successful original regression validation ' + name, len(cases) == count
            and sum(int(x.get('tests')) for x in suites) == count
            and all(int(x.get('errors')) == int(x.get('failures')) == int(x.get('skipped')) == 0 for x in suites)
            and all(not list(x) for x in cases))
        ids = {(x.get('classname'), x.get('name')) for x in cases}
        audit.check('distinct executed regression test identities ' + name, len(ids) == count and not seen & ids)
        seen.update(ids)
        receipts.append({'path': str(path), 'sha256': expected_sha, 'passed': count})
    audit.check('324 distinct passing regression tests', len(seen) == 324)
    audit.validation_evidence = receipts


def terminal_training_gate(audit, plans):
    path = CENTRAL / 'training-gate-decision.json'
    audit.anchor(path)
    decision = read(path)
    audit.require('terminal stop reports no evaluation measurements',
        decision['schema'] == 'skhynix/native005-training-gate-decision/1.0'
        and decision['status'] == 'STOPPED_BEFORE_EVALUATION'
        and decision['planned_evaluation_cells'] == 18 and decision['executed_evaluation_cells'] == 0
        and decision['evaluation_solve_rates'] is None
        and decision['observation_only_fallback'] is False and decision['guards_relaxed'] is False
        and decision['patch_retries'] == 0 and decision['promoted_skills'] == decision['verified_training_procedures'] == 0)
    audit.require('both actual training submissions and official grades retained', len(plans) == len(audit.training) == 2
        and decision['official_training_grades'] == 2
        and sum(r['resolved'] for r in audit.training) == decision['training_official_resolved'] == 1)
    records = {str(run): plan for run, plan in plans}
    audit.require('exact two declared terminal training checks', len(decision['training_checks']) == 2
        and {r['run_root'] for r in decision['training_checks']} == set(records))
    import trimem_skhynix_codex_procedures as procedures
    rejections = []
    for check in decision['training_checks']:
        run = Path(check['run_root']); plan = records[str(run)]
        root = run / 'cells/A'
        public_result = read(root / 'public-result.json')
        audit.check('gated outcome joins sealed patch and original grade ' + plan['public_task']['task_id'],
            check['cell'] == 'A' and check['procedure_attested'] is False
            and check['official_resolved'] == public_result['resolved']
            and check['patch_sha256'] == public_result['patch_sha256'] == file_digest(root / 'submission.diff')
            and check['public_result_sha256'] == file_digest(root / 'public-result.json'))
        refs = {p: file_digest(p) for p in [root / 'submission.diff', root / 'submission.json', root / 'public-result.json',
            root / 'grader-private.json', root / 'state.json', root / 'tool-events.jsonl', root / 'procedure-binding.json']}
        binding = plan['procedure_declaration']
        observed = None
        try:
            procedures.attest_procedure(run, 'A', Path(binding['path']), binding['sha256'])
        except procedures.ProcedureEvidenceError as exc:
            observed = {'error_type': type(exc).__name__, 'reason': str(exc)}
        audit.require('unchanged frozen procedure verifier independently rejects ' + plan['public_task']['task_id'],
            observed == {'error_type': check['error_type'], 'reason': check['reason']})
        audit.check('read-only failed attestation preserves every source receipt ' + plan['public_task']['task_id'],
            all(file_digest(p) == h for p, h in refs.items()))
        events, tail = broker.audit_events(root)
        submits = [e for e in events if e['request'].get('op') == 'submit' and e['result']['ok']]
        intent = read(root / 'grader-pending.json')
        submission = read(root / 'submission.json')
        audit.check('one final submission no later solver action ' + plan['public_task']['task_id'],
            len(submits) == 1 and submits[0] == events[-1])
        # The frozen grader deliberately retains its durable invocation marker
        # after public-result.json exists; cached reads then return that result.
        audit.check('one retained grader intent joins completed original receipt ' + plan['public_task']['task_id'],
            intent['patch_sha256'] == submission['patch_sha256'] == public_result['patch_sha256']
            and submission['submitted_at'] < intent['started_at'] <= (root / 'public-result.json').stat().st_mtime)
        rejections.append({'target_id': plan['public_task']['task_id'], **observed})
    audit.check('recorded promotion rejection matches prerequisite failure',
        decision['promotion_attempt_rejected'] == {k: rejections[0][k] for k in ('error_type', 'reason')})
    for name in ('learned-bank.json', 'observation-bank.json', 'batch-plan.json', 'batch-report.json', 'skill-delivery-preflight.json'):
        audit.check('gate blocks downstream artifact ' + name, not (CENTRAL / name).exists())
    audit.check('no promoted export or private authority created',
        not list(CENTRAL.glob('*/promoted-procedure.json')) and not list(CENTRAL.glob('*/gate-ab-private.sqlite3')))
    first_sources = plans[0][1]['source_hashes']
    for task_id in EVALUATION:
        base = CENTRAL / ('eval-' + task_id.rsplit('-', 1)[1])
        source = base / 'source'
        audit.check('evaluation execution never prepared ' + task_id, not (base / 'execution').exists())
        for relative, expected in first_sources.items():
            audit.check('unexecuted evaluation source preserved ' + task_id + ':' + relative,
                file_digest(source / relative) == expected)
        audit.sources[str(base / 'execution')] = len(first_sources)
    actual_results = list(CENTRAL.glob('training-*/execution/cells/*/public-result.json'))
    actual_submissions = list(CENTRAL.glob('training-*/execution/cells/*/submission.json'))
    audit.check('only two actual solver submissions and completed official receipts',
        len(actual_results) == len(actual_submissions) == 2
        and {p.parent.name for p in actual_results + actual_submissions} == {'A'})
    audit.actual_promoted_skills, audit.available_observations = 0, 0
    audit.terminal_evidence = {'decision_path': str(path), 'decision_sha256': file_digest(path),
        'status': decision['status'], 'official_training_grades': 2, 'official_training_resolved': 1,
        'independently_recomputed_verifier_rejections': rejections,
        'promotion_replayed_by_auditor': False, 'evaluation_goal_fulfilled': False,
        'planned_evaluation_cells': 18, 'executed_evaluation_cells': 0, 'evaluation_solve_rates': None}


def public_baseline_diagnostic(audit):
    path = CENTRAL / 'public-training-baseline-diagnostic.json'
    expected = '3d8c0d6c61885e160bb40f17212fbaa347bd1f5ee604688c4bd54e90820d89fc'
    audit.require('original public baseline diagnostic receipt', audit.anchor(path) == expected)
    diagnostic = read(path)
    decision = read(CENTRAL / 'training-gate-decision.json')
    run = CENTRAL / 'training-19637/execution'
    plan = read(run / 'plan.json')
    binding_path = run / 'cells/A/procedure-binding.json'
    binding = read(binding_path)
    result = diagnostic['result']
    audit.check('clean public diagnostic uses exact original bound test command and source',
        diagnostic['schema'] == 'skhynix/public-training-baseline-diagnostic/1.0'
        and diagnostic['task_id'] == plan['public_task']['task_id']
        and diagnostic['base_commit'] == plan['public_task']['commit']
        and diagnostic['argv'] == result['argv'] == json.loads(binding['bindings']['test_argv'])
        and diagnostic['image'] == audit.runtime_rows['sympy__sympy-19637']['image']
        and diagnostic['original_training_binding_sha256'] == file_digest(binding_path)
        and diagnostic['clean_checkout_before_after'] is True
        and diagnostic['evaluation_solvers_started'] is diagnostic['official_regrade'] is diagnostic['used_to_change_training_patch'] is False
        and diagnostic['model_api_calls'] == 0
        and decision['public_baseline_error_diagnostic_sha256'] == expected
        and result['exit_code'] == 1 and result['timed_out'] is result['output_truncated'] is False)
    work = CENTRAL / 'public-training-baseline-diagnostic/workspaces/NO_MEMORY' / plan['public_task']['task_id'] / 'checkouts' / plan['public_task']['task_id']
    git = ['git', '--no-replace-objects', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=/dev/null', '-C', str(work)]
    status = subprocess.run([*git, 'status', '--porcelain=v1', '--untracked-files=all'], capture_output=True, text=True,
        timeout=30, env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    head = subprocess.run([*git, 'rev-parse', 'HEAD'], capture_output=True, text=True,
        timeout=30, env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    audit.check('diagnostic current checkout independently clean at exact base',
        status.returncode == head.returncode == 0 and not status.stdout.strip()
        and head.stdout.strip() == diagnostic['base_commit'])
    events, _tail = broker.audit_events(run / 'cells/A')
    full = [e['result']['result'] for e in events if e['request'].get('name') == 'run_command'
        and e['result'].get('ok') and e['request']['arguments']['argv'] == diagnostic['argv']]
    audit.require('actual submitted training retained full bound command output', len(full) >= 2)
    error = "ValueError: Name node can't be used with 'False' constant"
    names = {'test_evaluate_false', 'test_issue_17811'}
    def signatures(text):
        return {n for n in names if 'test_sympify.py:' + n in text}
    audit.check('same public AST errors independently observed on clean base and repaired training',
        signatures(result['stdout']) == signatures(full[-1]['stdout']) == names
        and result['stdout'].count(error) == full[-1]['stdout'].count(error) == 2
        and '41 passed, 5 skipped, 2 expected to fail, 2 exceptions' in result['stdout']
        and '42 passed, 5 skipped, 2 expected to fail, 2 exceptions' in full[-1]['stdout']
        and full[-1]['exit_code'] != 0)
    audit.check('public baseline diagnostic occurred after sealed original training',
        path.stat().st_mtime > read(run / 'cells/A/submission.json')['submitted_at'])


def projected_injection_views(audit, root, plan, cell):
    """Join shared observations and actual promoted skill to exact frozen wire formats."""
    from enterprise_memory.trimem.skill_memory import RepositoryKnowledge
    from enterprise_memory.trimem.skill_runtime import SkillFirstMemoryController, SkillLayer
    label = plan['public_task']['task_id'] + ':' + cell
    records = audit.bank['records']
    originals = {x['memory_id']: x for x in records}
    expected_raw_views = {key: row['content'] for key, row in originals.items()}
    expected_raw_views[audit.skill.skill_id] = audit.skill_view
    report = read(root / 'bank-projection.json')
    bank_report = report['bank']
    audit.check('actual available candidate count ' + label,
        bank_report['records'] == (0 if cell == 'A' else len(originals) + (1 if cell == 'B' else 0))
        and bank_report['verified_skill_count'] == (1 if cell == 'C' else 0)
        and bank_report['imported_episode_count'] == 0)
    audit.check('projection outer identity and privacy contract ' + label,
        report['arm'] == ARMS[cell] and report['task_id'] == plan['public_task']['task_id']
        and report['seed_episode_count'] == 0 and report['seed_skill_count'] == (1 if cell == 'C' else 0)
        and report['verified_skill_payload_count'] == (0 if cell == 'A' else 1)
        and report['experience_writes'] is False and report['model_api_calls'] == 0)
    if cell == 'A':
        return {}
    projection = read(root / 'memory-private/historical-source-projection.json')
    audit.check('exact identical available public observation candidates ' + label,
        projection['execution_views'] == expected_raw_views and projection['validation']['verified_skill_count'] == 1
        and bank_report['source_projection_sha256'] == digest(canonical(projection))
        and bank_report['frozen_bank_sha256'] == plan['frozen_memory_bank']['sha256']
        and set(bank_report['training_task_ids']) == TRAIN)
    if cell == 'B':
        return {key: (view, 'ORG_SEMANTIC') for key, view in expected_raw_views.items()}
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
    expected_injections = {audit.skill.skill_id: (audit.skill_view, 'SKILL')}
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
    certificate = audit.certificates[task_id]
    workspace = read(root / 'workspace.json')
    audit.check('exact target public runtime joins ' + label,
        plan['public_python'] == certificate['python_executable']
        and workspace['image'] == certificate['source_image'])
    public = read(root / 'public-task.json')
    audit.check('evaluation has no private training instructions ' + label,
        not any(k in public for k in ('procedure_declaration', 'procedure_instructions', 'training_procedure', 'procedure_guidance')))
    expected_injections = projected_injection_views(audit, root, plan, cell) if audit.bank else {}
    if state.get('started_at') is not None:
        frozen_paths = [CENTRAL / 'launch-contract.json', CENTRAL / 'batch-plan.json', run / 'plan.json',
            Path(plan['frozen_memory_bank']['path']), Path(plan['supplemental_manifest']['path']),
            CENTRAL / 'skill-delivery-preflight.json', CENTRAL / 'synthetic-query-contract.json',
            CENTRAL / 'compatibility/before-training-gate.json']
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
    exposure_count, workflow_count, skill_kind_count = 0, 0, 0
    for event in events:
        if event['request'].get('op') != 'recall' or not event['result'].get('ok'):
            continue
        for item in event['result']['result'].get('injections', []):
            exposure_count += 1
            workflow_count += int(item['memory_id'] == audit.skill.skill_id)
            skill_kind_count += int(item['kind'] == 'SKILL')
            audit.check('actual injection exact UTF8 hash and frozen public payload ' + label + ':' + str(event['sequence']),
                len(item['exact_text'].encode()) == item['byte_count'] and digest(item['exact_text'].encode()) == item['sha256']
                and expected_injections.get(item['memory_id']) == (item['exact_text'], item['kind']))
    audit.check('actual L3 kind is available only in PDF controller ' + label,
        skill_kind_count == workflow_count if cell == 'C' else skill_kind_count == 0)
    if cell == 'A':
        audit.check('baseline has zero actual memory exposure ' + task_id, row['memory_injections'] == row['memory_bytes'] == 0)
    audit.rows.append({'target_id': task_id, 'cell': cell, 'arm': ARMS[cell], 'status': 'COMPLETE',
        'resolved': row['resolved'], 'actions': row['actions'], 'memory_injections': row['memory_injections'],
        'memory_bytes': row['memory_bytes'], 'observation_exposures_including_replay': exposure_count - workflow_count,
        'workflow_exposures_including_replay': workflow_count, 'available_observation_candidates': 0 if cell == 'A' else audit.available_observations,
        'actual_skill_kind_exposures_including_replay': skill_kind_count,
        'available_workflow_candidates': 0 if cell == 'A' else 1, 'patch_sha256': row['patch_sha256']})


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
            audit.check('frozen bank loader validates exact evaluation identity ' + entry['target_id'],
                loaded.promoted_skill == audit.skill and loaded.promoted_skill.execution_view() == audit.skill_view)
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
        wrapper['schema'] == ('skhynix/native-solver-attestations/1.0' if audit.terminal_gated else 'skhynix/native-solver-self-attestations/1.0')
        and wrapper['requested_model'] == 'gpt-6-astra' and wrapper['fork_turns'] == 'none'
        and wrapper['source'] == 'ROOT_TRANSCRIPTION_OF_ACTUAL_AGENT_FINAL_MESSAGES')
    rows = wrapper['attestations']
    planned = {('training-' + t.rsplit('-', 1)[1], 'A') for t in TRAIN}
    if not audit.terminal_gated:
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
        'planned_sessions_before_gate': 20, 'expected_executed_sessions': len(planned),
        'collected_sessions': len(seen), 'distinct_agent_ids': len(agents),
        'missing_sessions': [':'.join(x) for x in sorted(missing)],
        'scope': 'SELF_REPORTED_PROTOCOL_EVIDENCE_NOT_INDEPENDENT_BACKEND_OR_HOST_ATTESTATION'}


def finish(audit):
    status = 'FAIL' if audit.failures else ('PASS_GATED_BEFORE_EVALUATION' if audit.terminal_gated
        and audit.terminal_evidence and not audit.pending else ('PENDING' if audit.pending or len(audit.rows) != 18 else 'PASS_FINAL'))
    completed = {(x['target_id'], x['cell']): x for x in audit.rows}
    cells = [completed.get((target, cell), {'target_id': target, 'cell': cell, 'arm': ARMS[cell],
        'status': 'NOT_EXECUTED_TRAINING_GATE' if audit.terminal_gated else 'PENDING', 'resolved': None})
        for target in sorted(EVALUATION) for cell in ARMS]
    output = {'schema': 'skhynix/native005-independent-audit/1.0', 'status': status,
        'audit_at_unix_seconds': time.time(), 'audit_helper_sha256': file_digest(__file__),
        'checks_passed': audit.passed, 'checks_failed': len(audit.failures),
        'failures': audit.failures, 'pending': audit.pending, 'planned_cells': 18, 'completed_cells': len(audit.rows),
        'source_hash_counts': audit.sources, 'training_tasks': sorted(TRAIN), 'evaluation_tasks': sorted(EVALUATION),
        'training_results': audit.training, 'cells': cells, 'actual_promoted_skill_count': audit.actual_promoted_skills,
        'available_observation_records': audit.available_observations, 'evaluation_workflow_candidate_count': 1 if audit.bank else None,
        'terminal_gate': audit.terminal_evidence, 'validation_xml': audit.validation_evidence,
        'preserved_initial_audit': {'path': str(CENTRAL / 'audit-preliminary.json'),
            'sha256': file_digest(CENTRAL / 'audit-preliminary.json')} if (CENTRAL / 'audit-preliminary.json').is_file() else None,
        'evaluation_comparison_goal_fulfilled': len(audit.rows) == 18,
        'evaluation_solve_rates': None if audit.terminal_gated else 'See complete batch report when available',
        'first_observed_artifact_hashes': audit.anchors, 'historical_artifact_hashes': HISTORY,
        'solver_self_attestations': audit.self_attestations, 'model_api_calls': 0, 'grader_calls': 0, 'container_calls': 0,
        'authority_mutations': 0, 'private_payloads_exported': False,
        'limitations': ['Public runtime screened ascending-ID ancestral cohort; public titles inspected but not used by selection algorithm; not random or difficulty-proven.',
            'Ancestry certifies historical base commits, not upstream merge of native training patches.',
            'No L3 skill, learned evaluation bank, synthetic delivery result or live evaluation projection was created.' if audit.terminal_gated else 'Actual available L3 projection and synthetic delivery do not imply live controller selection or repair correctness.',
            'The training-gate audit passed; the requested baseline-versus-memory comparison was not performed.' if audit.terminal_gated else 'B and C share identical procedure bytes and raw observations; C observation wrappers can differ in byte length.',
            'The planned 18 evaluation cells are unexecuted after the terminal training gate; no measured solve denominator or lift exists.' if audit.terminal_gated else 'All 18 planned cells remain in the denominator; no required solve rate or assumed lift.',
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
    audit.check('central and executed auditor byte identity', file_digest(CENTRAL / 'audit_native005.py') == file_digest(__file__))
    for path, expected in HISTORY.items():
        audit.section('historical retention', lambda path=path, expected=expected:
            audit.check('historical bytes retained: ' + path, file_digest(path) == expected))
    audit.section('native004 all public evidence retained', lambda: retained_native004(audit))
    audit.section('launch and supersession', lambda: contracts(audit))
    audit.section('public runtime evidence', lambda: runtime_evidence(audit))
    SOURCE = CENTRAL / 'training-19637/source'
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
    for number in ('19637', '19783'):
        run = CENTRAL / ('training-' + number) / 'execution'
        def inspect_training():
            plan = training_plan(audit, run)
            if plan:
                plans.append((run, plan))
        audit.section('training-' + number, inspect_training)
    audit.section('manifest and source guards', lambda: manifest_and_sources(audit, plans))
    if audit.terminal_gated:
        audit.section('all eight before-training readiness receipts', lambda: before_training_gate(audit))
        audit.section('324 original regression validation tests', lambda: validation_xml(audit))
        audit.section('terminal gate and independent verifier rejections', lambda: terminal_training_gate(audit, plans))
        audit.section('independent clean public baseline diagnosis', lambda: public_baseline_diagnostic(audit))
        audit.section('actual two solver self-attestation joins', lambda: solver_attestations(audit))
        finish(audit)
        return
    audit.section('actual Gate B promotion', lambda: promotion(audit))
    audit.section('learned schema2 skill bank', lambda: learned_bank(audit))
    audit.section('synthetic delivery preflight', lambda: pre_evaluation_gate(audit))
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
