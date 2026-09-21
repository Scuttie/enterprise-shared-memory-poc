"""Native006 independent evidence auditor draft. Explicit --run required.
No solver, grader, container, broker request, or authority mutation is executed.
Private receipts are verified internally and never printed/exported. The only
outputs are audit.json and a first successful audit-preliminary.json receipt.
"""
import sys
sys.dont_write_bytecode=True
import argparse,hashlib,json,os,re,sqlite3,time
import xml.etree.ElementTree as ET
from pathlib import Path
CENTRAL=Path('/home/trimem-runner/skhynix-codex-006')
PREFIX='swebench_verified--sympy__sympy-'
TRAIN={PREFIX+n for n in ('19637','19783')}
EVALUATION={PREFIX+n for n in ('19954','20154','20428','20438','20801','21379')}
ARMS={'A':'NO_MEMORY','B':'EXISTING_M2','C':'SKHYNIX'}
LIMITS={'repository_actions':120,'wall_seconds':1200,'memory_injections':3,'memory_bytes':12000}
RUNNER='da4284cc210d8db5109f916248d97a8e82f725547e60c5d9a4d6c43573e3e9d5'
PUBLIC=Path('/mnt/c/Users/jewon/esm-r23-d115-writer/artifacts/skhynix_v1')
PRIOR={'codex_004':('16aed415a21123511e9ce2f7faacf17c0d83a812695d509a0ffb1374ed21f9d7',170),
'codex_005':('a8b05501be872776ab7a1e926349dcd9cd549a5f4da20856ea9443322e2eb1a5',136)}
HISTORY={}
INITIAL_NAMES=['training-19637-a1','training-19783-a1',*['eval-'+n for n in ('19954','20154','20428','20438','20801','21379')]]
ALL_TRAINING_NAMES=[f'training-{number}-a{attempt}' for number in ('19637','19783') for attempt in (1,2,3)]
VALIDATION_XML={'codex_006_integration_validation.xml':239,'codex_006_procedure_validation.xml':265}
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

def canonical_agent(value):
    # Root launch logs use canonical names; its public final-message transcript
    # uses the direct child's short name. Both name forms identify one session.
    if not isinstance(value,str) or not value:
        return None
    return value if value.startswith('/') else '/root/'+value

def read_only_db(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    return connection

class Audit:
    def __init__(self, phase='final'):
        self.passed, self.failures, self.pending = 0, [], []
        self.rows, self.training, self.sources, self.anchors = [], [], {}, {}
        self.bank, self.batch, self.launch, self.manifest = None, None, None, None
        self.available_observations, self.actual_promoted_skills = None, None
        self.self_attestations = None
        self.skill, self.skill_view, self.certificates = None, None, {}
        self.runtime_rows, self.gates = {}, {}
        self.terminal_gated = False
        self.attempts, self.accepted = [], {}
        self.source_freeze = None
        self.terminal_evidence, self.validation_evidence = None, None
        self.phase, self.ready_cells = phase, []
        self.source_snapshots, self.launch_receipts = {}, {}
        self.abort_receipt, self.early_abort_confirmed = None, False
        self.unexecuted_training_preparations = []
        prior = CENTRAL / 'audit.json'
        if prior.is_file():
            previous = read(prior)
            if previous.get('schema') == 'skhynix/native006-independent-audit/1.0':
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
        self.anchor(run/'plan.sha256')
        self.require(str(run) + ': canonical plan hash',
            (run / 'plan.sha256').read_text().strip() == digest(canonical(plan)))
        source = run.parent / 'source'
        expected = plan['source_hashes']
        if self.source_freeze is not None:
            self.check(str(run) + ': matches initial006 Python freeze',
                {k:v for k,v in expected.items() if k.endswith('.py')} == self.source_freeze['sha256'])
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
        run = Path(audit.accepted[task_id]['run_root'])
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
    if not (root/'public-result.json').is_file():
        if audit.phase == 'preliminary':
            audit.require('preliminary evaluation cell has never started ' + label,
                state['actions']==0 and state['started_at'] is None and state['status']=='OPEN'
                and not (root/'submission.json').exists())
            if audit.bank:
                projected_injection_views(audit,root,plan,cell)
            audit.ready_cells.append({'target_id':task_id,'cell':cell,'arm':ARMS[cell]})
        else:
            audit.pending.append(label+' official grade missing; live cell evidence not inspected')
        return
    expected_injections = projected_injection_views(audit, root, plan, cell) if audit.bank else {}
    if state.get('started_at') is not None:
        frozen_paths = [CENTRAL / 'launch-contract.json', CENTRAL / 'batch-plan.json', run / 'plan.json',
            Path(plan['frozen_memory_bank']['path']), Path(plan['supplemental_manifest']['path']),
            CENTRAL / 'skill-delivery-preflight.json', CENTRAL / 'synthetic-query-contract.json',
            CENTRAL / 'compatibility/before-training-gate.json', CENTRAL/'audit-preliminary.json']
        audit.check('all contracts bank manifest and batch frozen before first cell action ' + label,
            audit.launch['frozen_at_unix_seconds'] < state['started_at']
            and all(p.stat().st_mtime < state['started_at'] for p in frozen_paths))
    audit.require('preliminary audit precedes every evaluation grade '+label,audit.phase!='preliminary')
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
    if audit.phase=='final':
        preliminary_path=CENTRAL/'audit-preliminary.json'
        audit.anchor(preliminary_path);preliminary=read(preliminary_path)
        audit.require('successful preliminary audit retained before evaluation execution',
            preliminary['schema']=='skhynix/native006-independent-audit/1.0'
            and preliminary['status']=='PASS_PRE_EVALUATION' and preliminary['audit_phase']=='preliminary'
            and preliminary['checks_failed']==0 and preliminary['pending']==[]
            and preliminary['completed_cells']==0 and len(preliminary['unstarted_evaluation_cells_verified'])==18
            and preliminary['first_observed_artifact_hashes'].get(str(CENTRAL/'batch-plan.json'))==file_digest(CENTRAL/'batch-plan.json'))
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
    if audit.phase=='preliminary':
        if path.exists():
            report=read(path)
            audit.check('preliminary report contains no evaluation outcomes',
                report['status']=='INCOMPLETE' and report['completed_cells']==0
                and report['planned_cells']==18 and report['planned_targets']==6)
        return
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


def prior_public(audit):
    seen = set()
    for folder, (expected, count) in PRIOR.items():
        root = PUBLIC / folder
        manifest_path = root / 'public-artifact-manifest.json'
        audit.require('retained prior public manifest ' + folder, file_digest(manifest_path) == expected)
        manifest = read(manifest_path)
        audit.require('complete original prior public file count ' + folder, manifest['file_count'] == len(manifest['files']) == count)
        audit.check('exact retained prior public directory inventory '+folder,
            {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
            =={row['path'] for row in manifest['files']}|{'public-artifact-manifest.json'})
        for row in manifest['files']:
            copied = root / row['path']
            audit.require('prior public file containment', root.resolve() in copied.resolve().parents)
            for path in (copied, Path(row['source'])):
                if str(path) in seen:
                    continue
                seen.add(str(path))
                audit.check('prior original bytes ' + str(path), path.stat().st_size == row['bytes'] and file_digest(path) == row['sha256'])


def launch_contract(audit):
    required = ('launch-contract.json', 'source-freeze.json', 'supplemental-manifest.json', 'procedure-declaration.json',
        'solver_prompt_template.txt', 'training_solver_prompt_template.txt', 'synthetic-query-contract.json', 'cold-bank.json',
        'training-task-descriptors.json','evaluation-task-descriptors.json','prior-experiment-provenance.json')
    missing = [p for p in required if audit.pending_file(CENTRAL / p, p + ' not yet frozen')]
    if missing:
        return False
    for name in required:
        audit.anchor(CENTRAL / name)
    launch = audit.launch = read(CENTRAL / 'launch-contract.json')
    freeze = audit.source_freeze = read(CENTRAL / 'source-freeze.json')
    audit.require('explicit006 native model and planned cohort', launch['schema'] == 'skhynix/native006-launch-contract/1.0'
        and set(launch['training_instances']) == TRAIN and set(launch['evaluation_instances']) == EVALUATION
        and launch['planned_evaluation_cells'] == 18 and launch['requested_model'] == 'gpt-6-astra'
        and launch['fork_turns'] == 'none' and launch['prior_memory_reused'] is False
        and launch['separate_model_api_calls'] == 0 and launch['codex_tokens_and_cost'] is None)
    audit.check('root-pinned initial006 contract and v2 declaration',
        file_digest(CENTRAL/'launch-contract.json')=='2ee5e9cc316deb96caace00799e42b3cd105c290ae0bc6bae9a32383f8d882e9'
        and file_digest(CENTRAL/'procedure-declaration.json')=='70437a961574d980293c8cbce99fdc871d788606da590513a5c71cae76868c94')
    audit.check('bounded first qualifying attempt policy frozen before solvers',
        launch['training_acceptance'] == {'max_fresh_attempts_per_task':3, 'attempt_order':[1,2,3],
        'accept':'FIRST_ATTEMPT_PER_DISTINCT_TASK_WITH_ACTUAL_V2_ATTESTATION_AND_OFFICIAL_RESOLVED_TRUE',
        'retain_all_failed_attempts':True, 'retry_feedback':'NONE; SAME_FROZEN_TEMPLATE_AND_EMPTY_MEMORY_EACH_ATTEMPT',
        'stop_retries_after_first_qualifier':True, 'if_either_task_has_no_qualifier':'STOP_BEFORE_EVALUATION; NO_FALLBACK_OR_THRESHOLD_CHANGE'})
    audit.check('unchanged public selected cohort and evaluation prompt',
        file_digest(CENTRAL / 'supplemental-manifest.json') == launch['manifest_sha256'] == '57f369ee641b923ec551698fb52f043e7cf8569e4872f0f691883f47d399f6b9'
        and file_digest(CENTRAL / 'solver_prompt_template.txt') == launch['evaluation_template_sha256'] == '745986f93d449b91163f634ac85e91875f426948d68518239f3d99263b3a5c05'
        and file_digest(CENTRAL / 'training_solver_prompt_template.txt') == launch['training_template_sha256']
        and file_digest(CENTRAL / 'source-freeze.json') == launch['source_freeze_sha256'])
    audit.check('initial327 source freeze explicit identity', freeze['schema'] == 'skhynix/native006-source-freeze/1.0'
        and freeze['head'] == 'd4fd304339687b42c645ae84872a72eddddcda97'
        and len(freeze['sha256']) == freeze['source_files'] == 327 and freeze['frozen_before_all_new_solver_calls'] is True)
    prior=read(CENTRAL/'prior-experiment-provenance.json')
    audit.check('known005 training reuse and outcome-informed redesign disclosed',
        prior['prior_training_outcomes_used_for_procedure_redesign'] is True
        and prior['prior_patches_or_memory_reused'] is False
        and prior['prior_evaluation_solver_calls']==prior['prior_evaluation_grades']==0
        and prior['prior_manifest_sha256']==launch['manifest_sha256']
        and prior['prior_audit_sha256']==file_digest(PUBLIC/'codex_005/audit.json')
        and 'KNOWN_TRAINING_REUSED' in launch['cohort_scope']
        and 'INFORMED_BY_NATIVE005_TRAINING_FAILURES' in launch['design_origin'])
    abort_path=CENTRAL/'abort-observer-defect.json'
    if abort_path.is_file():
        audit.anchor(abort_path);audit.abort_receipt=read(abort_path)
    return True


def public_validation_and_launch_readiness(audit):
    path=CENTRAL/'validation-evidence.json'
    audit.anchor(path);value=read(path)
    audit.require('exact504 public validation receipt shape',set(value)=={'status','distinct_passed_tests','xml'}
        and value['status']=='PASS' and value['distinct_passed_tests']==504
        and len(value['xml'])==2 and {row['name'] for row in value['xml']}==set(VALIDATION_XML))
    identities=set();observed=[]
    for row in value['xml']:
        audit.require('finite named public XML reference',set(row)=={'name','sha256','test_cases'}
            and row['test_cases']==VALIDATION_XML[row['name']])
        xml_path=PUBLIC/row['name']
        audit.require('public validation XML exact bytes '+row['name'],audit.anchor(xml_path)==row['sha256'])
        root=ET.fromstring(xml_path.read_bytes());cases=list(root.iter('testcase'))
        local={(case.get('classname'),case.get('name')) for case in cases}
        audit.require('public XML counts unique clean passing cases '+row['name'],
            len(cases)==len(local)==row['test_cases'] and not identities&local
            and all(all(case.find(tag) is None for tag in ('failure','error','skipped')) for case in cases))
        identities.update(local);observed.append(dict(row))
    audit.check('504 distinct cases counted across both XML reports',len(identities)==504)
    audit.validation_evidence={'status':'PASS','distinct_passed_tests':len(identities),'xml':observed}
    ready_path=CENTRAL/'launch-readiness.json';audit.anchor(ready_path);ready=read(ready_path)
    audit.require('actual launch-readiness filename and immutable006 prerequisites',
        ready['schema']=='skhynix/native006-launch-readiness/1.0' and ready['status']=='PASS'
        and ready['validation']==value and ready['launch_contract_sha256']==file_digest(CENTRAL/'launch-contract.json')
        and ready['source_freeze_sha256']==file_digest(CENTRAL/'source-freeze.json')
        and ready['solver_model_calls_so_far']==ready['grader_calls_so_far']==ready['executed_evaluation_cells']==0
        and len(ready['initial_training'])==2 and {row['name'] for row in ready['initial_training']}==set(INITIAL_NAMES[:2]))
    for row in ready['initial_training']:
        plan=read(CENTRAL/row['name']/'execution/plan.json')
        audit.check('initial training readiness bound to frozen plan '+row['name'],
            row['cell']=='A' and row['plan_sha256']==digest(canonical(plan))
            and row['requested_model']==plan['requested_solver_model']=='gpt-6-astra'
            and row['solver_user_id']==plan['solver_user_id']=='native-codex-006-'+row['name'])


def operational_source_snapshots(audit):
    manifest=read(CENTRAL/'supplemental-manifest.json')
    expected=dict(audit.source_freeze['sha256'])
    excluded={row['path']:row['raw_sha256'] for row in manifest['excluded_manifests']}
    for number in ('002','003','004'):
        name='configs/skhynix_v1/codex_'+number+'_manifest.json';expected[name]=excluded[name]
    expected['configs/skhynix_v1/codex_005_manifest.json']=file_digest(CENTRAL/'supplemental-manifest.json')
    names=list(INITIAL_NAMES)
    names.extend(name for name in ALL_TRAINING_NAMES if name not in names and (CENTRAL/name/'source-snapshot.json').is_file())
    for name in names:
        path=CENTRAL/name/'source-snapshot.json';audit.anchor(path);receipt=read(path)
        source=CENTRAL/name/'source'
        audit.require('operational snapshot exact331 frozen inputs '+name,
            receipt['schema']=='skhynix/native006-operational-source-snapshot/1.0'
            and receipt['source']==str(source) and receipt['copied_from']=='/mnt/c/Users/jewon/esm-r23-d115-writer'
            and receipt['source_freeze_sha256']==file_digest(CENTRAL/'source-freeze.json')
            and receipt['copied_file_sha256']==expected and len(expected)==331)
        for relative,sha256 in expected.items():
            target=source/relative
            audit.require('snapshot input remains contained '+name+':'+relative,
                source.resolve() in target.resolve().parents and not any(p.is_symlink() for p in (target,*target.parents)))
            audit.check('operational source bytes remain frozen '+name+':'+relative,file_digest(target)==sha256)
        audit.source_snapshots[name]={'copied_files':len(expected),'receipt_sha256':file_digest(path),
            'source_freeze_sha256':receipt['source_freeze_sha256']}


def solver_launch_receipts(audit):
    directory=CENTRAL/'solver-launches'
    expected={(row['name'],'A') for row in audit.attempts}
    expected.update(('eval-'+row['target_id'].rsplit('-',1)[1],row['cell']) for row in audit.rows)
    allowed={(name,'A') for name in ALL_TRAINING_NAMES}
    allowed.update((name,cell) for name in INITIAL_NAMES[2:] for cell in ARMS)
    seen=set();agents=set()
    for path in sorted(directory.glob('*.json')):
        receipt=read(path);identity=(receipt.get('name'),receipt.get('cell'))
        audit.require('finite public solver-launch identity',identity in allowed
            and path.name==identity[0]+'-'+identity[1]+'.json' and identity not in seen)
        # A launch receipt is immutable; active solver journals and states are
        # never anchored here. The filled prompt contains only the public template.
        audit.anchor(path);name,cell=identity
        template=CENTRAL/('training_solver_prompt_template.txt' if name.startswith('training-') else 'solver_prompt_template.txt')
        expected_prompt=template.read_text().replace('{{BASE}}',str(CENTRAL/name)).replace('{{CELL}}',cell).encode()
        prompt_path=directory/(name+'-'+cell+'-prompt.txt')
        audit.check('fresh native launch and unchanged exact filled prompt '+name+':'+cell,
            receipt['schema']=='skhynix/native006-solver-launch/1.0'
            and receipt['requested_model']=='gpt-6-astra' and receipt['fork_turns']=='none'
            and receipt['reasoning_effort']=='INHERITED_PARENT_UNCHANGED'
            and receipt['root_cross_cell_feedback'] is False and receipt['separate_model_api_calls']==0
            and receipt['template_sha256']==file_digest(template)
            and receipt['filled_prompt_sha256']==digest(expected_prompt)==file_digest(prompt_path)
            and prompt_path.read_bytes()==expected_prompt
            and isinstance(receipt['agent'],str) and canonical_agent(receipt['agent']) not in agents
            and receipt['recorded_at_unix_seconds']>audit.launch['frozen_at_unix_seconds'])
        if name.startswith('training-'):
            plan=read(CENTRAL/name/'execution/plan.json')
            audit.check('unique fresh training attempt authority and solver user '+name,
                plan['experiment_id']=='skhynix-native-codex-006-training'
                and plan['solver_user_id']=='native-codex-006-'+name)
        seen.add(identity);agents.add(canonical_agent(receipt['agent']))
        audit.launch_receipts[name+':'+cell]={'agent':canonical_agent(receipt['agent']),'receipt_sha256':file_digest(path),
            'filled_prompt_sha256':receipt['filled_prompt_sha256']}
    audit.check('every officially graded solver has one public launch receipt',expected<=seen)
    if audit.phase=='preliminary' or audit.abort_receipt is not None:
        audit.check('no evaluation solver launched before preliminary audit',seen==expected and all(name.startswith('training-') for name,cell in seen))


def frozen_sources(audit, run, plan):
    expected = {k:v for k,v in plan['source_hashes'].items() if k.endswith('.py')}
    audit.check('all attempts and evaluations use initial frozen Python bytes ' + str(run), expected == audit.source_freeze['sha256'])
    for filename in ('launch-contract.json', 'source-freeze.json', 'procedure-declaration.json', 'training_solver_prompt_template.txt', 'compatibility/before-training-gate.json'):
        root = run / 'cells/A'
        state = read(root / 'state.json')
        if state.get('started_at') is not None:
            audit.check('prerequisite freeze precedes first training action ' + filename + ':' + str(run),
                (CENTRAL / filename).stat().st_mtime < state['started_at'])


def readiness(audit):
    path = CENTRAL / 'compatibility/before-training-gate.json'
    if audit.pending_file(path, 'eight named public prerequisites not yet complete'):
        return
    audit.anchor(path)
    gate = read(path)
    rows = gate['all_eight_runtime_checks']
    audit.require('all8 complete clean full and named public prerequisites', gate['status'] == 'PASS'
        and gate['all_clean'] is gate['same_runner_and_python'] is gate['all_named_probes_exactly_one_pass'] is True
        and gate['solver_model_calls'] == gate['grader_calls'] == gate['plans_created'] == 0
        and len(rows) == 8 and {r['target_id'] for r in rows} == TRAIN | EVALUATION)
    import trimem_skhynix_codex_skill_bank as skills
    descriptors = read(CENTRAL / 'training-task-descriptors.json') + read(CENTRAL / 'evaluation-task-descriptors.json')
    targets = [learning._task_descriptor(r) for r in descriptors]
    refs = []
    for row in rows:
        certificate_path = Path(row['certificate'])
        refs.append({'path':str(certificate_path), 'sha256':audit.anchor(certificate_path)})
        certificate = read(certificate_path)
        audit.check('prerequisite named and whole public counts ' + row['target_id'], row['status'] == 'PASS'
            and row['named_public_passed'] == 1 and row['full_public_passed'] > 0
            and row['runner_sha256'] == RUNNER and row['python_version'] == '3.9.20'
            and certificate['named_public_test']['passed_count'] == row['named_public_passed']
            and certificate['public_test']['passed_count'] == row['full_public_passed'])
        audit.reference(certificate['evidence_ref'], 'original named public observation')
    skills._compatibility(refs, targets, {'procedure_id':procedures.NAMED_PROCEDURE_ID, 'training_runner_sha256':[RUNNER]})
    audit.check('unchanged production validator accepts all8 exact named compatibility observations', True)


def training_attempts(audit):
    first_plan = None
    for number in ('19637','19783'):
        qualified, prior_complete = False, True
        for attempt in (1,2,3):
            name = f'training-{number}-a{attempt}'
            run = CENTRAL / name / 'execution'
            if not (run / 'plan.json').is_file():
                if attempt == 1:
                    audit.pending.append(name + ' not yet prepared')
                prior_complete = False
                continue
            audit.require('attempt numbering contiguous and no retry after first qualifier ' + name, prior_complete and not qualified)
            plan = audit.plan(run)
            first_plan = first_plan or plan
            frozen_sources(audit, run, plan)
            audit.check('attempt task identity empty memory and fixed procedure ' + name,
                plan['public_task']['task_id'] == PREFIX+number and plan['procedure_declaration']['sha256'] == audit.launch['procedure_declaration']['sha256']
                and file_digest(plan['frozen_memory_bank']['path']) == file_digest(CENTRAL/'cold-bank.json'))
            for cell in ('B','C'):
                state = read(run / 'cells' / cell / 'state.json')
                audit.check('unexecuted alternate training arm ' + name + cell, state['actions'] == 0 and state['started_at'] is None
                    and not (run/'cells'/cell/'public-result.json').exists())
            if not (run/'cells/A/public-result.json').is_file() and audit.abort_receipt is not None:
                audit.require('only explicitly unused a3 preparation has no official grade',name=='training-19637-a3')
                audit.unexecuted_training_preparations.append({'name':name,'run_root':str(run),
                    'plan_sha256':digest(canonical(plan)),'solver_launched':False})
                prior_complete=False
                continue
            if audit.pending_file(run/'cells/A/public-result.json', name + ' actual grade absent'):
                prior_complete = False
                continue
            row = batch_module.verify_result_receipt(plan, run, 'A', legacy_training=True)
            observed = {'name':name,'task_id':row['target_id'],'attempt':attempt,'run_root':str(run),'cell':'A',
                'official_resolved':row['resolved'],'patch_sha256':row['patch_sha256'],
                'public_result_sha256':file_digest(run/'cells/A/public-result.json')}
            try:
                result = procedures.attest_procedure(run,'A',CENTRAL/'procedure-declaration.json',plan['procedure_declaration']['sha256'])
                observed.update(procedure_attested=True,attestation_sha256=result['attestation_sha256'])
                audit.check('actual namedv2 five-stage evidence verified ' + name, result['attestation']['procedure_id'] == procedures.NAMED_PROCEDURE_ID
                    and result['attestation']['official_training_resolved'] is True)
            except procedures.ProcedureEvidenceError as exc:
                observed.update(procedure_attested=False,error_type=type(exc).__name__,reason=str(exc))
            receipt_path = CENTRAL / (name+'-acceptance.json')
            if not audit.pending_file(receipt_path, name + ' acceptance receipt absent'):
                audit.anchor(receipt_path)
                audit.check('exact independently recomputed attempt acceptance ' + name, read(receipt_path) == observed)
            audit.check('actual attempt budget and no memory ' + name, row['actions'] <= 120 and row['memory_injections'] == row['memory_bytes'] == 0
                and row['separate_model_api_calls'] == 0 and row['codex_tokens_and_cost'] is None)
            audit.attempts.append(observed)
            if row['resolved'] and observed['procedure_attested']:
                qualified = True
                audit.accepted[row['target_id']] = {'run_root':str(run),'cell':'A','name':name}
    audit.training = list(audit.attempts)
    if first_plan:
        binding = first_plan['supplemental_manifest']
        targets, private, images, manifest = dataset.load_supplemental_rows(Path(binding['path']),
            Path(first_plan['paths']['dataset_cache_root']),expected_sha256=binding['sha256'],root=SOURCE)
        del private
        audit.check('frozen selected dataset loader verifies original public cohort and ancestry',
            len(targets)==8 and len(manifest['ancestry'])==13 and manifest['selection']==dataset.NATIVE005_SELECTION)
    accepted_path = CENTRAL/'accepted-training.json'
    if audit.abort_receipt is not None:
        audit.require('early observer abort preserves zero accepted procedures',not audit.accepted)
        return
    if audit.accepted.keys() == TRAIN:
        if audit.pending_file(accepted_path,'two first qualifiers not yet frozen into acceptance gate'):
            return
        audit.anchor(accepted_path)
        accepted = read(accepted_path)
        audit.require('only first qualifier per distinct task accepted',accepted['status']=='PASS_READY_TO_PROMOTE'
            and accepted['selected']==[audit.accepted[PREFIX+n] for n in ('19637','19783')]
            and accepted['checks']==audit.attempts and accepted['retry_feedback_provided'] is False
            and accepted['official_training_grades']==len(audit.attempts))
    else:
        gate_paths = sorted(CENTRAL.glob('training-gate-after-*-grades.json'))
        gates = [read(p) for p in gate_paths]
        terminal = next((g for g in gates if g['status']=='STOPPED_BEFORE_EVALUATION'),None)
        if terminal:
            exhausted={n for n in ('19637','19783') if sum(r['task_id']==PREFIX+n for r in audit.attempts)==3
                and PREFIX+n not in audit.accepted}
            audit.require('terminal training exhaustion retains every attempted grade', terminal['checks']==audit.attempts
                and terminal['max_fresh_attempts_per_task']==3 and terminal['executed_evaluation_cells']==0
                and terminal['evaluation_solve_rates'] is None and set(terminal['exhausted_task_ids'])==exhausted and exhausted)
            audit.terminal_gated = True
            for name in ('accepted-training.json','learned-bank.json','observation-bank.json','batch-plan.json','batch-report.json','skill-delivery-preflight.json'):
                audit.check('terminal gate blocks downstream artifact '+name,not (CENTRAL/name).exists())
            audit.check('terminal gate blocks all evaluation plans and promotion',not list(CENTRAL.glob('eval-*/execution/plan.json'))
                and not list(CENTRAL.glob('*/promoted-procedure.json')))
        else:
            audit.pending.append('training retry/qualification policy not yet resolved')


def observer_defect_abort(audit):
    receipt=audit.abort_receipt
    if receipt is None:return
    abort_path=CENTRAL/'abort-observer-defect.json'
    audit.require('explicit immutable early observer-defect abort receipt',
        file_digest(abort_path)=='3a3b8bc9ddbca9041932e3e88841c92de11b405e6f3de7d5ccf1eca1986014b8'
        and receipt['schema']=='skhynix/native006-observer-defect-abort/1.0'
        and receipt['status']=='EARLY_ABORT_OBSERVER_DEFECT'
        and receipt['early_abort_reason']=='VERIFIED_OBSERVER_FALSE_NEGATIVE; NOT_MODEL_EXHAUSTION_OR_SUCCESS'
        and receipt['launch_contract_sha256']==file_digest(CENTRAL/'launch-contract.json')
        and receipt['guards_relaxed'] is receipt['results_relabelled'] is receipt['model_feedback_provided'] is False
        and receipt['frozen_source_unchanged'] is True and receipt['max_attempts_exhausted'] is False
        and receipt['planned_max_training_attempts_per_task']==3
        and receipt['planned_evaluation_cells']==18 and receipt['executed_evaluation_cells']==0
        and receipt['comparison_goal_completed'] is False and receipt['evaluation_solve_rates'] is None
        and receipt['accepted_training']==receipt['promoted_skills']==receipt['separate_model_api_calls']==0
        and receipt['codex_tokens_and_cost'] is None)
    expected_names={f'training-{n}-a{a}' for n in ('19637','19783') for a in (1,2)}
    audit.require('exact four sealed graded attempts retained without relabelling',
        len(audit.attempts)==receipt['official_training_grades']==receipt['native_solver_sessions']==4
        and {row['name'] for row in audit.attempts}==expected_names
        and sum(row['official_resolved'] for row in audit.attempts)==receipt['training_official_resolved']==2
        and not any(row['procedure_attested'] for row in audit.attempts)
        and receipt['graded_training']==[{'name':row['name'],'cell':'A','public_result_sha256':row['public_result_sha256']} for row in audit.attempts])
    gate_path=audit.reference(receipt['training_gate_ref'],'unchanged four-grade training gate')
    gate=read(gate_path)
    audit.require('original gate remains training-in-progress and not exhaustion',
        gate['status']=='TRAINING_IN_PROGRESS' and gate['checks']==audit.attempts
        and gate['official_training_grades']==4 and gate['selected']==[] and gate['exhausted_task_ids']==[]
        and gate['max_fresh_attempts_per_task']==3 and gate['retry_feedback_provided'] is False)
    for count in range(7):
        path=CENTRAL/('training-gate-after-'+str(count)+'-grades.json')
        if path.is_file():audit.anchor(path)
    diagnostic_path=audit.reference(receipt['diagnostic_ref'],'public frozen-verifier diagnostic')
    diagnostic=read(diagnostic_path)
    audit.require('original false-negative diagnostic remains unchanged',
        receipt['diagnostic_ref']['sha256']=='b6710e4d4cf28b01750e8b781950be6387948bc12ff7f872bc0ea69fc436078e'
        and diagnostic['classification']=='OBSERVER_FALSE_NEGATIVE_FOR_STANDARD_ZERO_PASSED_RED_SUMMARY'
        and diagnostic['official_resolved'] is True and diagnostic['frozen_procedure_attested'] is False
        and diagnostic['promotion_or_acceptance_overrides'] is False)
    for key,ref in diagnostic['source_references'].items():audit.reference(ref,'diagnostic frozen public source '+key)
    diagnostic_root=CENTRAL/'training-19637-a2/execution/cells/A'
    events,tail=broker.audit_events(diagnostic_root)
    begin=[event for event in events if event['request'].get('op')=='begin_procedure']
    audit.require('diagnosed attempt has exactly one successful procedure binding',len(begin)==1 and begin[0]['result']['ok'] is True)
    bound=begin[0]['result']['result'];bindings=bound['bindings'];argv=json.loads(bindings['test_argv'])
    red=next(event for event in events if event['sequence']==diagnostic['red_sequence'])
    result=red['result']['result'];snapshot=result['procedure_snapshot'];base=bound['workspace_snapshot']
    addition=procedures._named_addition(base,snapshot,bindings['test_name'])
    text=str(result.get('stdout',''))+'\n'+str(result.get('stderr',''))
    summaries=re.findall(r'(?m)^[ =]*tests finished:[ \t]*([^\r\n]*?)[ \t]*, in [0-9]+(?:\.[0-9]+)? seconds[ =]*$',text)
    frames=re.findall(r'File "([^"\r\n]+)", line ([0-9]+), in ([A-Za-z_][A-Za-z0-9_]*)',text)
    audit.require('replayed public RED is one direct assertion with unchanged implementation',
        addition is not None and result['argv']==argv and result['cwd']=='.' and type(result['exit_code']) is int and result['exit_code']==1
        and result['timed_out'] is result['output_truncated'] is False
        and snapshot==result['procedure_snapshot_before'] and snapshot['changed_paths']==[bindings['test_path']]
        and snapshot['source_sha256']==base['source_sha256'] and snapshot['runner_sha256']==base['runner_sha256']==RUNNER
        and snapshot['test_sha256']!=base['test_sha256']
        and frames[-1][0]=='/testbed/'+argv[2] and frames[-1][2]==bindings['test_name'] and int(frames[-1][1]) in addition['direct_assert_lines'])
    audit.require('frozen parser false-negative reproduced without modified inputs',
        summaries==['0 passed, 1 failed']==diagnostic['observed_summary_payloads']
        and procedures._counts(text,'passed')==[0] and procedures._counts(text,'failed')==[1]
        and procedures.named_runner_outcome(result,argv,red=True,test_name=bindings['test_name'],assertion_lines=addition['direct_assert_lines']) is False
        and diagnostic['public_red_stdout']==result['stdout'] and diagnostic['public_red_stderr']==result['stderr']
        and diagnostic['red_request_sha256']==digest(canonical(red['request']))
        and diagnostic['red_result_sha256']==digest(canonical(result)) and diagnostic['journal_event_tail_sha256']==tail)
    for observed in diagnostic['green_observations']:
        event=next(event for event in events if event['sequence']==observed['sequence']);green=event['result']['result'];state=green['procedure_snapshot']
        audit.check('replayed identical-test GREEN '+str(observed['sequence']),
            procedures.named_runner_outcome(green,argv) is True and state['test_sha256']==snapshot['test_sha256']
            and state['source_sha256']!=base['source_sha256'] and state['runner_sha256']==RUNNER
            and state==green['procedure_snapshot_before'] and digest(canonical(green))==observed['result_sha256'])
    unused=receipt['unused_prepared_cells']
    expected_unused={(name,cell) for name in expected_names for cell in ('B','C')}|{('training-19637-a3',cell) for cell in ARMS}
    audit.require('exact eleven unused prepared cells, including unlaunched a3',len(unused)==11
        and {(row['name'],row['cell']) for row in unused}==expected_unused
        and [row['name'] for row in audit.unexecuted_training_preparations]==['training-19637-a3'])
    for row in unused:
        run=CENTRAL/row['name']/'execution';root=run/'cells'/row['cell'];state=read(root/'state.json')
        audit.require('unused preparation remains unstarted and ungraded '+row['name']+':'+row['cell'],
            state['status']=='OPEN' and state['actions']==0 and state['started_at'] is None
            and digest(canonical(read(run/'plan.json')))==row['plan_sha256']
            and file_digest(root/'state.json')==row['state_sha256']
            and not (root/'submission.json').exists() and not (root/'public-result.json').exists()
            and not (CENTRAL/'solver-launches'/(row['name']+'-'+row['cell']+'.json')).exists()
            and (not (root/'tool-events.jsonl').exists() or not (root/'tool-events.jsonl').read_bytes().strip()))
        audit.anchor(root/'state.json')
    forbidden=('accepted-training.json','observation-bank.json','learned-bank.json','batch-plan.json','batch-plan.json.sha256',
        'batch-report.json','skill-delivery-preflight.json','audit-preliminary.json')
    for name in forbidden:audit.check('early abort retains absence of downstream artifact '+name,not (CENTRAL/name).exists())
    audit.check('early abort has no promotion or evaluation plans',not list(CENTRAL.glob('*/promoted-procedure.json'))
        and not list(CENTRAL.glob('eval-*/execution/plan.json')))
    status_path=CENTRAL/'experiment-status.json';audit.anchor(status_path);status=read(status_path)
    audit.require('public experiment result reports early abort and no solve-rate claim',
        status['schema']=='skhynix/native006-result/1.0' and status['status']=='EARLY_ABORT_OBSERVER_DEFECT'
        and status['abort_receipt_sha256']==file_digest(abort_path) and status['comparison_goal_completed'] is False
        and status['native_solver_sessions']==4 and status['completed_evaluation_cells']==0 and status['planned_evaluation_cells']==18
        and status['promoted_skills']==0 and status['training']==audit.attempts
        and set(status['comparison'])==set(ARMS.values())
        and all(row['status']=='NOT_RUN' and row['planned_targets']==6 and row['completed_targets']==0
            and row['resolved'] is row['solve_rate'] is row['difference_percentage_points'] is None for row in status['comparison'].values()))
    audit.early_abort_confirmed=True;audit.actual_promoted_skills=0;audit.available_observations=0
    audit.terminal_evidence={'status':'EARLY_ABORT_OBSERVER_DEFECT','abort_receipt_sha256':file_digest(abort_path),
        'diagnostic_sha256':file_digest(diagnostic_path),'official_training_grades':4,'max_attempts_exhausted':False,
        'unused_prepared_cells':unused,'comparison_goal_completed':False}


def synthetic_delivery(audit):
    path=CENTRAL/'skill-delivery-preflight.json'
    if audit.pending_file(path,'separate synthetic skill-delivery prerequisite absent'):
        return
    audit.anchor(path); receipt=read(path); contract=read(CENTRAL/'synthetic-query-contract.json')
    audit.require('synthetic delivery frozen query and bank exact match', receipt['schema']=='skhynix/native006-synthetic-delivery/1.0'
        and receipt['status']=='PASS' and receipt['procedure_id']==procedures.NAMED_PROCEDURE_ID
        and receipt['synthetic_query_contract_sha256']==file_digest(CENTRAL/'synthetic-query-contract.json')
        and receipt['bank_sha256']==file_digest(CENTRAL/'learned-bank.json') and receipt['query']==contract['query']
        and receipt['query']['objective']==procedures.NAMED_TEMPLATE.subgoal_signature
        and receipt['actual_evaluation_actions_consumed']==receipt['solver_model_calls']==receipt['grader_calls']==0
        and receipt['synthetic_results_not_counted_as_solver_injections'] is True
        and receipt['actual_evaluation_state_hashes_before']==receipt['actual_evaluation_state_hashes_after'])
    rows=receipt['records']
    audit.require('exact eighteen synthetic arm checks distinct from live results',len(rows)==18
        and {(r['target_id'],r['arm']) for r in rows}=={(t,a) for t in EVALUATION for a in ARMS.values()})
    for row in rows:
        audit.check('same exact available promoted public payload in synthetic prerequisite '+row['target_id']+row['arm'],
            row['eligible_skill_id']==audit.skill.skill_id and row['eligible_public_view_sha256']==digest(audit.skill_view.encode())
            and row['eligible_public_view_bytes']==len(audit.skill_view.encode()) and row['candidate_view_equal'] is True)
        matched=[x for x in row['synthetic_injections'] if x['memory_id']==audit.skill.skill_id]
        audit.check('synthetic selection reported from actual returned injections',row['selected_skill']==bool(matched))
        if row['arm']=='NO_MEMORY':audit.check('synthetic baseline empty',row['synthetic_injections']==[])
        if row['arm']=='SKHYNIX':audit.check('synthetic PDF actually selects one skill',len(matched)==1 and matched[0]['kind']=='SKILL')
        for item in matched:
            audit.check('synthetic exact promoted bytes',item['exact_text']==audit.skill_view and item['sha256']==digest(audit.skill_view.encode())
                and item['byte_count']==len(audit.skill_view.encode()))


def self_attestations(audit):
    path=CENTRAL/'solver-attestations.json'
    if audit.pending_file(path,'actual solver self-attestations absent'):return
    wrapper=read(path)
    if audit.abort_receipt is not None or len(audit.rows)==18:audit.anchor(path)
    audit.require('self-attestation requested native identity',wrapper['requested_model']=='gpt-6-astra' and wrapper['fork_turns']=='none'
        and wrapper['source']=='ROOT_TRANSCRIPTION_OF_ACTUAL_AGENT_FINAL_MESSAGES')
    expected={(r['name'],'A') for r in audit.attempts}
    expected.update(('eval-'+r['target_id'].rsplit('-',1)[1],r['cell']) for r in audit.rows)
    seen,agents=set(),set()
    for row in wrapper['attestations']:
        identity=(row['run'],row['cell'])
        audit.require('unique actual completed solver identity',identity in expected and identity not in seen and canonical_agent(row['agent']) not in agents)
        seen.add(identity);agents.add(canonical_agent(row['agent']))
        root=CENTRAL/row['run']/'execution/cells'/row['cell']
        audit.check('actual solver self-report joined to sealed patch',row['only_assigned_broker'] is row['no_subagents'] is row['no_external_access'] is True
            and row['patch_sha256']==read(root/'submission.json')['patch_sha256']==file_digest(root/'submission.diff'))
        audit.check('self-report agent joins its immutable launch receipt',
            audit.launch_receipts.get(row['run']+':'+row['cell'],{}).get('agent')==canonical_agent(row['agent']))
    if seen!=expected:audit.pending.append('some completed actual solver self-attestations absent')
    audit.self_attestations={'actual_completed_sessions':len(expected),'collected_sessions':len(seen),'distinct_agents':len(agents),
        'scope':'SELF_REPORTED_PROTOCOL_NOT_INDEPENDENT_HOST_OR_BACKEND_ATTESTATION'}


def finish(audit):
    complete=len(audit.rows)==18
    preliminary=(audit.phase=='preliminary' and len(audit.ready_cells)==18 and len(audit.rows)==0
        and audit.accepted.keys()==TRAIN and audit.bank is not None and audit.batch is not None)
    status='FAIL' if audit.failures else ('PENDING' if audit.pending else ('PASS_EARLY_ABORT_OBSERVER_DEFECT' if audit.early_abort_confirmed else ('PASS_GATED_BEFORE_EVALUATION' if audit.terminal_gated else ('PASS_FINAL' if complete else ('PASS_PRE_EVALUATION' if preliminary else 'PENDING')))))
    output={'schema':'skhynix/native006-independent-audit/1.0','status':status,'audit_helper_sha256':file_digest(__file__),
        'audit_at_unix_seconds':time.time(),'checks_passed':audit.passed,'checks_failed':len(audit.failures),'failures':audit.failures,'pending':audit.pending,
        'planned_cells':18,'completed_cells':len(audit.rows),'evaluation_comparison_goal_fulfilled':complete,
        'evaluation_solve_rates':{arm:sum(r['resolved'] for r in audit.rows if r['arm']==arm)/6 for arm in ARMS.values()} if complete else None,
        'training_attempts':audit.attempts,'accepted_training':audit.accepted,'cells':audit.rows,'source_hash_counts':audit.sources,
        'actual_promoted_skill_count':audit.actual_promoted_skills,'available_observation_records':audit.available_observations,
        'first_observed_artifact_hashes':audit.anchors,'prior_public_manifests':PRIOR,'solver_self_attestations':audit.self_attestations,
        'audit_phase':audit.phase,'unstarted_evaluation_cells_verified':audit.ready_cells,
        'operational_source_snapshots':audit.source_snapshots,'public_solver_launch_receipts':audit.launch_receipts,
        'validation_evidence':audit.validation_evidence,
        'terminal_evidence':audit.terminal_evidence,'unexecuted_training_preparations':audit.unexecuted_training_preparations,
        'model_api_calls':0,'grader_calls':0,'container_calls':0,'authority_mutations':0,'private_payloads_exported':False,
        'limitations':['Known training tasks may have up to three preregistered fresh attempts; all outcomes retained and only first actual qualifiers accepted.',
            'Evaluation tasks were unexecuted in005; v2 procedure design was informed by005 training outcomes.',
            'Synthetic delivery is a prerequisite and is never counted as actual live memory injection.',
            'No evaluation solve rate exists before all18 paired official grades; gating is not a0percent solve rate.',
            'Native model and host restrictions remain requested/self-reported protocol metadata, not independent backend or OS attestation.']}
    raw=canonical(output)+b'\n'
    if status=='PASS_PRE_EVALUATION':
        with (CENTRAL/'audit-preliminary.json').open('xb') as stream:stream.write(raw)
    (CENTRAL/'audit.json').write_bytes(raw)
    print(json.dumps({k:output[k] for k in ('status','checks_passed','checks_failed','planned_cells','completed_cells')}))


def main(phase='final'):
    global SOURCE,broker,batch_module,dataset,learning,procedures,ACTIVE_AUDIT
    audit=ACTIVE_AUDIT=Audit(phase)
    if phase=='preliminary':
        audit.check('preliminary audit receipt is write-once',not (CENTRAL/'audit-preliminary.json').exists())
    audit.section('archived004and005 public evidence',lambda:prior_public(audit))
    if not launch_contract(audit):finish(audit);return
    SOURCE=CENTRAL/'training-19637-a1/source'
    if not SOURCE.is_dir():audit.pending.append('initial frozen006source absent');finish(audit);return
    sys.path[:0]=[str(SOURCE/'src'),str(SOURCE/'scripts')]
    import trimem_skhynix_codex as broker
    import trimem_skhynix_codex_batch as batch_module
    import trimem_skhynix_native_dataset as dataset
    import trimem_skhynix_codex_learning as learning
    import trimem_skhynix_codex_procedures as procedures
    broker.block_model_client()
    declaration=procedures.load_declaration(CENTRAL/'procedure-declaration.json',audit.launch['procedure_declaration']['sha256'])
    audit.check('separately versioned exact namedv2 template',declaration['procedure_id']==procedures.NAMED_PROCEDURE_ID
        and declaration['template_hash']==procedures.NAMED_TEMPLATE.content_hash=='sha256:000c8c3d3b8d19d23cd1dfa7eccc328aa4d3929bf10254141225dc2b7b07fab2')
    cold=read(CENTRAL/'cold-bank.json')
    audit.check('all new training attempts start from empty memory',cold['cold_start'] is True and cold['records']==[]
        and cold['training_task_ids']==[] and set(cold['evaluation_task_ids'])==TRAIN and cold['gate_b']['verified_skill_count']==0)
    audit.section('504 public checks and original launch-readiness',lambda:public_validation_and_launch_readiness(audit))
    audit.section('all8 operational source snapshots and any later fresh attempts',lambda:operational_source_snapshots(audit))
    audit.section('all8 named public prerequisites',lambda:readiness(audit))
    audit.section('all training attempts and first qualifier gate',lambda:training_attempts(audit))
    audit.section('explicit early abort for immutable observer defect',lambda:observer_defect_abort(audit))
    if audit.accepted.keys()==TRAIN and (CENTRAL/'accepted-training.json').is_file():
        audit.section('actual named GateB promotion',lambda:promotion(audit))
        audit.section('schema2 learned bank from accepted sources only',lambda:learned_bank(audit))
        if audit.bank:
            audit.section('synthetic delivery prerequisite',lambda:synthetic_delivery(audit))
            audit.section('18 official evaluation cells',lambda:evaluation(audit))
            audit.section('complete paired report',lambda:final_report(audit))
    audit.section('public actual solver-launch receipts',lambda:solver_launch_receipts(audit))
    audit.section('all completed solver attestations',lambda:self_attestations(audit))
    finish(audit)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true',help='Run only after root authorization; writes audit.json and the first successful preliminary receipt only.')
    parser.add_argument('--phase',choices=('preliminary','final'),default='final',help='Preliminary requires all18 evaluation cells prepared but never started.')
    args=parser.parse_args()
    if not args.run:parser.error('Draft is inert without explicit --run authorization')
    try:
        main(args.phase)
    except Exception as exc:
        audit=globals().get('ACTIVE_AUDIT',Audit())
        audit.failures.append({'check':'audit execution','error_type':type(exc).__name__})
        finish(audit)
