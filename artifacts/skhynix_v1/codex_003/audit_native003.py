"""Independent native003 evidence audit. Writes only CENTRAL/audit.json.

No model, grader or container execution. Private grader outputs are never
printed or copied. Frozen training verifiers run in read-only Python children.
"""
import sys
sys.dont_write_bytecode = True
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess

CENTRAL = Path('/home/trimem-runner/skhynix-codex-003')
PREFIX = 'swebench_verified--sympy__sympy-'
TRAIN = {PREFIX + value for value in ('23262', '23413', '24066', '24213')}
SUPPORT = {PREFIX + value for value in ('24066', '24213')}
EVALUATION = {PREFIX + value for value in ('24443', '24539', '24562')}
ARMS = {'A': 'NO_MEMORY', 'B': 'EXISTING_M2', 'C': 'SKHYNIX'}
HISTORY = {
 '/home/trimem-runner/skhynix-codex-002/learned-bank.json': 'fa9c23658b26a10f21e56b7459bdb639d56643088a3e452ef668793d7290415f',
 '/home/trimem-runner/skhynix-codex-002/batch-report.json': '0974a6a27bcb4c76c38a375c614a2d2aab9fafec7392187b6c5a1a2f94446999',
 '/home/trimem-runner/skhynix-codex-002/batch-plan.json': '710673ff6aedc2123fc3779d0682ea9f2955b99263c34049140c9f270414f851',
 '/home/trimem-runner/skhynix-codex-002/audit.json': 'c9c71db01f7b4e2c0ddc9e192fd7f1c888c3842994bac89b25b03bc9dfa080b2',
 '/home/trimem-runner/skhynix-codex-002/supplemental-manifest.json': 'e074530fb006834d95aee2c4aff23aeb90a18b99c9136eff91fa22aa3fd65814',
 '/home/trimem-runner/skhynix-live-001/execution/report.json': 'a6fde126cdd0e545e6e478ce4740b7038803df10052ee23433e9f8439cba46e0',
 '/home/trimem-runner/skhynix-live-002/execution/report.json': '1971c9ebb9f5f8e7cbb7188ca33c031725c009240184fbb7fecf84f140a0f784',
}
EXPECTED_BANK_SHA = 'a99c31bbae74ea2bdd3aa45a905df5f8464cca4ea4c1ffe2cf16d089718486c9'


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


class Audit:
    def __init__(self):
        self.passed = 0
        self.failures = []
        self.pending = []
        self.rows = []
        self.sources = {}

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

    def reference(self, value, name):
        path = Path(value['path'])
        self.require(name + ': absolute unlinked file', path.is_absolute() and path.is_file()
                     and not any(part.is_symlink() for part in (path, *path.parents)))
        self.require(name + ': frozen bytes', file_digest(path) == value['sha256'])
        return path

    def plan_sources(self, run, plan):
        source = run.parent / 'source'
        self.require(str(run) + ': original source exists', source.is_dir())
        expected = plan['source_hashes']
        paths = [*source.glob('src/enterprise_memory/**/*.py'), *source.glob('scripts/*.py'),
                 source / 'configs/trimem_v1/m2_candidates/recall.json', source / 'artifacts/trimem_v1/freeze.json']
        observed = {path.relative_to(source).as_posix() for path in paths}
        self.require(str(run) + ': complete original source file set', observed == set(expected))
        for relative, value in expected.items():
            path = source / relative
            self.require(str(run) + ': source path containment', source.resolve() in path.resolve().parents)
            self.check(str(run) + ': source hash ' + relative, file_digest(path) == value)
        self.sources[str(run)] = len(expected)

    def plan(self, run):
        plan = read(run / 'plan.json')
        self.require(str(run) + ': canonical plan hash',
                     (run / 'plan.sha256').read_text().strip() == digest(canonical(plan)))
        self.plan_sources(run, plan)
        return plan


def read_only_db(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    return connection


def main():
    global ACTIVE_AUDIT
    audit = Audit()
    ACTIVE_AUDIT = audit
    for path, expected in HISTORY.items():
        audit.section('retained historical artifact', lambda path=path, expected=expected:
                      audit.check('historical bytes unchanged: ' + path, file_digest(path) == expected))
    source = CENTRAL / 'eval-24443/source'
    if not source.is_dir() or not (CENTRAL / 'batch-plan.json').is_file():
        audit.pending.append('Evaluation source and frozen batch plan are not prepared')
        finish(audit)
        return
    sys.path[:0] = [str(source / 'src'), str(source / 'scripts')]
    import trimem_skhynix_codex_batch as batch_module
    import trimem_skhynix_codex as broker
    from enterprise_memory.trimem.skill_memory import ProcedureTemplate, Skill
    broker.block_model_client()
    batch = read(CENTRAL / 'batch-plan.json')
    bank = read(CENTRAL / 'learned-bank.json')
    audit.require('final schema2 bank original hash', file_digest(CENTRAL / 'learned-bank.json') == EXPECTED_BANK_SHA)
    audit.require('batch canonical freeze hash', (CENTRAL / 'batch-plan.json.sha256').read_text().strip() == digest(canonical(batch)))
    audit.require('four distinct training tasks', {row['target_id'] for row in batch['training']} == TRAIN
                  and len(batch['training']) == 4)
    audit.require('three new evaluation tasks nine cells', {row['target_id'] for row in batch['evaluation']} == EVALUATION
                  and len(batch['evaluation']) == 3 and batch['planned_cells'] == 9)
    audit.check('declared train/evaluation split disjoint', not TRAIN & EVALUATION)
    audit.check('bank exact task split', set(bank['training_task_ids']) == TRAIN
                and set(bank['evaluation_task_ids']) == EVALUATION)
    audit.check('schema2 source owners and revisions preserved', bank['skill_projection']['source_episode_revisions_rebound'] is False
                and bank['skill_projection']['source_skill_owner_rebound'] is False
                and bank['skill_projection']['private_episode_copy_count'] == 0)
    audit.check('single actual Gate B skill', bank['gate_b']['verified_skill_count'] == 1)
    batch_module.validate_split(batch['contract'], TRAIN, EVALUATION)
    audit.check('batch supplemental roles and frozen bank match', True)
    supplemental = read(audit.reference(batch['contract']['supplemental_manifest'], 'supplemental manifest'))
    audit.check('new supplemental evaluation IDs', {row['target_id'] for row in supplemental['targets'] if row['role'] == 'EVALUATION'} == EVALUATION)
    launch = read(CENTRAL / 'launch-contract.json')
    audit.check('native model and fresh context declared', launch['requested_model'] == 'gpt-6-astra' and launch['fork_turns'] == 'none')
    audit.check('native usage not invented', launch['separate_model_api_calls'] == 0 and launch['codex_tokens_and_cost'] is None)
    audit.check('evaluation prompt frozen bytes', file_digest(CENTRAL / 'solver_prompt_template.txt') == launch['evaluation_template_sha256'])
    audit.check('training prompt frozen bytes', file_digest(CENTRAL / 'training_solver_prompt_template.txt') == launch['training_template_sha256'])

    export = read(audit.reference(bank['promoted_export'], 'actual promotion export'))
    fields = dict(export['promoted_skill'])
    fields['template'] = ProcedureTemplate(**fields['template'])
    skill = Skill(**fields)
    view = skill.execution_view()
    audit.check('public payload exactly actual Skill execution view', export['public_execution_view'] == view
                and digest(view.encode()) == export['public_execution_view_sha256']
                and len(view.encode()) == export['public_execution_view_bytes'])
    audit.check('actual promotion supports only predeclared tasks', set(export['training_task_ids']) == SUPPORT
                and skill.support_count == skill.contributor_count == 2)
    authority = audit.reference(export['authority_db'], 'private authority')
    authority_initial = file_digest(authority)
    audit.require('authority has no active mutable journal', not any(Path(str(authority) + suffix).exists()
                  and Path(str(authority) + suffix).stat().st_size > 0 for suffix in ('-wal', '-journal')))
    with read_only_db(authority) as connection:
        row = connection.execute("SELECT * FROM memory_records WHERE record_id=? AND kind='skill'", (skill.skill_id,)).fetchone()
        audit.require('actual authority contains nonrevoked skill', row is not None and row['revoked'] == 0)
        payload = json.loads(row['payload'])
        actual = {**payload, 'content_hash': row['content_hash']}
        audit.check('export joined to actual shared authority row', actual == export['promoted_skill']
                    and 'sha256:' + digest(canonical(payload)) == row['content_hash'])
        supports = connection.execute('SELECT e.* FROM skill_support s JOIN memory_records e ON s.episode_id=e.record_id '
                                      'WHERE s.skill_id=? ORDER BY e.record_id', (skill.skill_id,)).fetchall()
        audit.require('two actual support episode rows', len(supports) == 2)
        task_ids, users, verifiers, hashes = set(), set(), set(), []
        for row in supports:
            payload = json.loads(row['payload'])
            evidence = payload['evidence']
            task_ids.add(evidence['task_id']); users.add(evidence['user_id']); verifiers.add(evidence['verification_evidence_hash'])
            hashes.append(row['content_hash'])
            audit.check('canonical original support episode ' + evidence['task_id'],
                'sha256:' + digest(canonical(payload)) == row['content_hash'] and row['revoked'] == 0
                and row['org_id'] == skill.org_id == evidence['org_id']
                and row['owner_user_id'] == evidence['user_id'] and row['revision'] == evidence['revision']
                and evidence['procedure_hash'] == skill.template.content_hash and evidence['succeeded'] is True)
            rendered = skill.template.render(dict(evidence['parameter_bindings']))
            audit.check('support exact bound procedure ' + evidence['task_id'], tuple(evidence['actions']) == rendered.steps
                        and evidence['verification_command'] == rendered.verification_command)
        audit.check('actual independent task/session/verifier support', task_ids == SUPPORT and len(users) == len(verifiers) == 2)
        audit.check('actual evidence set content hash', skill.evidence_set_hash == 'sha256:' + digest(canonical(hashes)))
    audit.check('read-only authority audit preserved exact bytes', file_digest(authority) == authority_initial)

    declaration_path = audit.reference(export['declaration'], 'predeclared workflow')
    attestations = {}
    for reference in export['attestations']:
        content = read(audit.reference(reference, 'private verifier artifact'))
        attestation = content['attestation']
        task_id = attestation['task_id']
        attestations[task_id] = (reference, content)
        audit.check('verifier artifact canonical hash ' + task_id, digest(canonical(attestation))
                    == reference['attestation_sha256'] == content['attestation_sha256'])
    for training in batch['training']:
        run = Path(training['run_root'])
        plan = audit.plan(run)
        audit.check('training frozen receipt hashes ' + training['target_id'],
                    training['plan_sha256'] == digest(canonical(plan)) and
                    training['result_sha256'] == file_digest(run / 'cells' / training['cell'] / 'public-result.json'))
        batch_module.verify_result_receipt(plan, run, training['cell'], legacy_training=True)
        audit.check('training official receipt and broker chain ' + training['target_id'], True)
        if training['target_id'] in SUPPORT:
            audit.check('new training original authority and declaration', plan['experiment_id'] == skill.org_id
                        and plan['procedure_declaration'] == export['declaration'])
            child = """import sys; sys.dont_write_bytecode=True
from pathlib import Path
sys.path[:0]=[str(Path(sys.argv[1])/'src'),str(Path(sys.argv[1])/'scripts')]
import trimem_skhynix_codex_procedures as p
r=p.attest_procedure(Path(sys.argv[2]),sys.argv[3],Path(sys.argv[4]),sys.argv[5])
print(p.canonical({'attestation_sha256':r['attestation_sha256'],'episode_sha256':p.sha(p.canonical(r['episode_evidence'])),'stages':[x['stage'] for x in r['attestation']['stages']]}).decode())
"""
            output = subprocess.run([sys.executable, '-B', '-c', child, str(run.parent / 'source'), str(run), training['cell'],
                str(declaration_path), export['declaration']['sha256']], capture_output=True, text=True, timeout=60,
                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
            audit.require('frozen source verifier recomputation exits cleanly ' + training['target_id'], output.returncode == 0)
            recomputed = json.loads(output.stdout)
            reference, original = attestations[training['target_id']]
            audit.check('exact procedural attestation recomputed ' + training['target_id'],
                recomputed['attestation_sha256'] == reference['attestation_sha256'] and
                recomputed['episode_sha256'] == digest(canonical(original['episode_evidence'])) and
                recomputed['stages'] == ['INSPECT', 'ADD_REGRESSION', 'RED', 'REPAIR_IMPLEMENTATION', 'GREEN'])

    certificates = {}
    for reference in bank['compatibility_receipts']:
        receipt = read(audit.reference(reference, 'public workflow compatibility'))
        certificates[receipt['target']['task_id']] = receipt
        observation = read(audit.reference(receipt['evidence_ref'], 'actual public compatibility observation'))
        audit.check('compatibility actual command result hash ' + receipt['target']['task_id'],
                    digest(canonical(observation.get('result', observation))) == receipt['public_test']['observation_sha256'])
        audit.check('training and target public runner identical ' + receipt['target']['task_id'],
                    receipt['runner_sha256'] in export['training_runner_sha256'])

    for evaluation in batch['evaluation']:
        run = Path(evaluation['run_root'])
        plan = audit.plan(run)
        audit.check('evaluation original runner validates runtime and frozen bank ' + evaluation['target_id'],
                    broker.load_plan(run) == plan)
        task_id = evaluation['target_id']
        audit.check('evaluation exact frozen batch plan ' + task_id, digest(canonical(plan)) == evaluation['plan_sha256'])
        audit.check('evaluation receives no training procedure prompt ' + task_id, plan.get('procedure_declaration') is None)
        audit.check('equal model limits and memory bank ' + task_id, plan['requested_solver_model'] == 'gpt-6-astra'
                    and plan['limits'] == batch['contract']['limits'] and plan['frozen_memory_bank'] == batch['contract']['frozen_memory_bank'])
        audit.check('native context and inherited host access disclosed ' + task_id,
                    'native' in plan.get('l0_projection','').lower() and 'protocol' in plan.get('host_isolation','').lower())
        certificate = certificates[task_id]
        audit.check('exact target runtime Python join ' + task_id, plan['public_python'] == certificate['python_executable'])
        for cell, arm in ARMS.items():
            root = run / 'cells' / cell
            workspace = read(root / 'workspace.json')
            audit.check('exact target runtime image join ' + task_id + cell, workspace['image'] == certificate['source_image'])
            packet = read(root / 'public-task.json')
            audit.check('no training instructions in public evaluation packet ' + task_id + cell,
                        not any(key in packet for key in ('procedure_declaration', 'procedure_instructions',
                                                         'training_procedure', 'procedure_guidance')))
            if cell in ('B', 'C'):
                projection = read(root / 'memory-private/historical-source-projection.json')
                audit.check('identical actual skill bytes in source projection ' + task_id + cell,
                            projection['execution_views'].get(skill.skill_id) == view)
            if cell == 'C':
                with read_only_db(root / 'memory-private/source-memory.sqlite3') as connection:
                    counts = dict(connection.execute('SELECT kind,COUNT(*) FROM memory_records GROUP BY kind').fetchall())
                audit.check('skill projection copies no private episodes or skill rows ' + task_id,
                            counts.get('episode', 0) == counts.get('skill', 0) == 0)
                projection = read(root / 'bank-projection.json')
                audit.check('actual L3 projection count ' + task_id, projection['seed_skill_count'] == 1)
            state = read(root / 'state.json')
            if state.get('started_at') is not None:
                audit.check('launch fixed before evaluation start ' + task_id + cell,
                            launch['frozen_at_unix_seconds'] < state['started_at'])
            if not (root / 'public-result.json').exists():
                audit.pending.append(task_id + ':' + cell + ' official grade missing')
                continue
            row = batch_module.verify_result_receipt(plan, run, cell)
            audit.check('official grade and sealed chain verified ' + task_id + cell, True)
            audit.check('model API and native cost truthful ' + task_id + cell,
                        row['separate_model_api_calls'] == 0 and row['codex_tokens_and_cost'] is None)
            audit.check('action and memory count budgets ' + task_id + cell,
                        row['actions'] <= plan['limits']['repository_actions'] and row['memory_injections'] <= 3 and row['memory_bytes'] <= 12000)
            events, _tail = broker.audit_events(root)
            skill_exposures = 0
            for event in events:
                if event['request'].get('op') == 'recall' and event['result'].get('ok'):
                    for item in event['result']['result'].get('injections', []):
                        audit.check('injection exact UTF8/hash ' + task_id + cell + ':' + str(event['sequence']),
                            len(item['exact_text'].encode()) == item['byte_count'] and digest(item['exact_text'].encode()) == item['sha256'])
                        if item['memory_id'] == skill.skill_id:
                            skill_exposures += 1
                            audit.check('exposed workflow payload equality ' + task_id + cell,
                                item['exact_text'] == view and item['kind'] == ('SKILL' if cell == 'C' else 'ORG_SEMANTIC'))
            if cell == 'A':
                audit.check('baseline has zero memory exposure ' + task_id, row['memory_injections'] == 0 and row['memory_bytes'] == 0)
            audit.rows.append({'target_id': task_id, 'cell': cell, 'arm': arm, 'resolved': row['resolved'],
                'actions': row['actions'], 'memory_injections': row['memory_injections'], 'memory_bytes': row['memory_bytes'],
                'workflow_exposures_including_replay': skill_exposures, 'patch_sha256': row['patch_sha256']})
    audit.check('authority remains unchanged at audit completion', file_digest(authority) == authority_initial)
    report_path = CENTRAL / 'batch-report.json'
    if report_path.exists():
        report = read(report_path)
        complete = len(audit.rows) == 9
        audit.check('batch report completion count', report['completed_cells'] == len(audit.rows)
                    and report['status'] == ('COMPLETE' if complete else 'INCOMPLETE'))
        if complete:
            for arm in ARMS.values():
                selected = [row for row in audit.rows if row['arm'] == arm]
                comparison = report['comparison'][arm]
                audit.check('paired solve denominator and numerator ' + arm,
                            comparison['n'] == 3 and comparison['resolved'] == sum(row['resolved'] for row in selected))
    else:
        audit.pending.append('Final batch report absent')
    finish(audit)


def finish(audit):
    status = 'FAIL' if audit.failures else ('INCOMPLETE' if audit.pending or len(audit.rows) != 9 else 'PASS_FINAL')
    output = {'schema': 'skhynix/native003-independent-audit/1.0', 'status': status,
        'checks_passed': audit.passed, 'checks_failed': len(audit.failures), 'failures': audit.failures,
        'pending': audit.pending, 'completed_cells': len(audit.rows), 'source_hash_counts': audit.sources,
        'training_tasks': sorted(TRAIN), 'procedure_support_tasks': sorted(SUPPORT), 'evaluation_tasks': sorted(EVALUATION),
        'cells': audit.rows, 'model_api_calls': 0, 'grader_calls': 0, 'container_calls': 0,
        'authority_mutations': 0, 'private_payloads_exported': False,
        'limitations': ['Contributor independence means distinct Codex sessions, not distinct human users.',
            'Compatibility certifies public test workflow prerequisites, not target repair correctness.',
            'Native model selection is requested metadata, not independently attested backend snapshot.',
            'Host restrictions remain protocol rules; native context is not the PDF L0 projection.']}
    (CENTRAL / 'audit.json').write_bytes(canonical(output) + b'\n')
    print(json.dumps({'status': status, 'checks_passed': audit.passed, 'checks_failed': len(audit.failures),
                      'completed_cells': len(audit.rows), 'pending': len(audit.pending)}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        failure = globals().get('ACTIVE_AUDIT', Audit())
        if not isinstance(exc, AssertionError):
            failure.failures.append({'check': 'audit execution', 'error_type': type(exc).__name__})
        finish(failure)
