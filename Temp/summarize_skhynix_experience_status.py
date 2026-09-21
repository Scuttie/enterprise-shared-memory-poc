"""Read receipt metadata only and export a current collection status snapshot."""
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path('/home/trimem-runner/skhynix-architecture-scale-001')
OUT = Path('/mnt/c/Users/jewon/esm-r23-d115-writer/artifacts/skhynix_v1/architecture_scale_001')
LEARNING = ROOT / 'pipeline-v13/learning-240'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def reference(path):
    path = Path(path)
    return {'path': str(path), 'sha256': digest(path.read_bytes())}


def checked(ref):
    raw = Path(ref['path']).read_bytes()
    assert digest(raw) == ref['sha256'], ref['path']
    return json.loads(raw)


def main():
    observed = datetime.now(timezone.utc)
    state_bytes = (LEARNING / 'learning-state.json').read_bytes()
    catalog_bytes = (LEARNING / 'catalog.json').read_bytes()
    state, catalog = json.loads(state_bytes), json.loads(catalog_bytes)
    enrollment = read(LEARNING / 'learning-enrollment.json')
    old_tasks = set(read(ROOT / 'pipeline-v13/learning-120/learning-enrollment.json')['training_tasks'])
    tasks, episodes, evidence = [], [], []
    episode_tasks = {}
    for ref in state['cells'].values():
        cell = checked(ref)
        task = cell['task_id']
        directory = Path(cell['cell_path']).parent
        result_path = directory / 'public-result.json'
        hold_path = directory / 'training-grade-undetermined.json'
        pending_path = directory / 'grader-pending.json'
        memory_injections = None
        if result_path.is_file():
            result = read(result_path)
            assert result['official'] is True and type(result['resolved']) is bool
            assert result['task_id'] == task
            outcome = 'RESOLVED' if result['resolved'] else 'UNRESOLVED'
            outcome_ref = reference(result_path)
            memory_injections = result.get('broker_status', {}).get('memory_injections')
        elif hold_path.is_file():
            hold = read(hold_path)
            assert hold['resolved'] is None and hold['official'] is False
            outcome, outcome_ref = 'UNDETERMINED', reference(hold_path)
        else:
            assert pending_path.is_file(), directory
            outcome, outcome_ref = 'UNDETERMINED', reference(pending_path)
        kinds = Counter()
        verified = 0
        knowledge = set()
        for capture in cell['captures']:
            r, checkpoint = capture['receipt'], capture['checkpoint']
            assert r['source_task_id'] == task
            assert r['capture_id'] in catalog['captures']
            assert r['episode_id'] not in episode_tasks
            episode_tasks[r['episode_id']] = task
            knowledge.update(r['knowledge_ids'])
            kinds[checkpoint['kind']] += 1
            verified += r['succeeded'] is True
            episodes.append({'task_id': task, 'official_outcome': outcome,
                'capture_id': r['capture_id'], 'episode_id': r['episode_id'],
                'node_id': checkpoint['node_id'], 'checkpoint_kind': checkpoint['kind'],
                'cutoff_step': checkpoint['cutoff_step'],
                'public_test_outcome': checkpoint['public_test_outcome'],
                'public_green_verifier': r['succeeded'],
                'semantic_completion': capture['semantic_completion'],
                'knowledge_references': len(r['knowledge_ids']),
                'capture_path': catalog['captures'][r['capture_id']]['path']})
        tasks.append({'task_id': task, 'repository': task.split('--', 1)[1].rsplit('-', 1)[0].replace('__', '/'),
            'group': 'inherited_120' if task in old_tasks else 'new_240',
            'official_outcome': outcome, 'capture_status': cell['status'],
            'episodes': len(cell['captures']), 'public_green_verified_episodes': verified,
            'public_test_red': sum(c['checkpoint']['kind'] == 'PUBLIC_TEST_OBSERVATION' and c['checkpoint']['public_test_outcome'] == 'RED' for c in cell['captures']),
            'public_test_green': sum(c['checkpoint']['kind'] == 'PUBLIC_TEST_OBSERVATION' and c['checkpoint']['public_test_outcome'] == 'GREEN' for c in cell['captures']),
            'completed_subgoal': kinds['COMPLETED_SUBGOAL'],
            'terminal_partial_attempt': kinds['TERMINAL_ACTIVE'],
            'checkpoint_counts': dict(kinds), 'l2_unique_nodes_referenced': len(knowledge),
            'capture_failures': len(cell['failures']), 'empty_checkpoints': len(cell['empty_checkpoints']),
            'memory_injections': memory_injections})
        evidence.append({'task_id': task, 'learning_receipt_reference': ref, 'outcome_reference': outcome_ref})
    assert len({r['task_id'] for r in tasks}) == len(tasks)
    assert len({r['capture_id'] for r in episodes}) == len(episodes) == len(catalog['captures'])
    nodes, edges = Counter(), Counter()
    for value in catalog['knowledge'].values():
        nodes[episode_tasks[value['source_episode_id']]] += 1
    for value in catalog['edges']:
        edges[episode_tasks[value['source_episode_id']]] += 1
    grouped = {}
    for outcome in ('RESOLVED', 'UNRESOLVED', 'UNDETERMINED'):
        group = [r for r in tasks if r['official_outcome'] == outcome]
        grouped[outcome] = {'tasks': len(group), 'episodes': sum(r['episodes'] for r in group),
            'tasks_with_episodes': sum(r['episodes'] > 0 for r in group),
            'public_green_verified_episodes': sum(r['public_green_verified_episodes'] for r in group),
            'checkpoint_counts': dict(sum((Counter(r['checkpoint_counts']) for r in group), Counter()))}
    for row in tasks:
        row['l2_nodes_by_catalog_source_episode'] = nodes[row['task_id']]
        row['l2_edges_by_source_episode'] = edges[row['task_id']]
    summary = {'collected_tasks': len(tasks), 'target_tasks': len(enrollment['training_tasks']),
        'collection_progress_percent': 100 * len(tasks) / len(enrollment['training_tasks']),
        'inherited_tasks': sum(r['group'] == 'inherited_120' for r in tasks),
        'new_tasks': sum(r['group'] == 'new_240' for r in tasks),
        'L1_episodes': len(episodes), 'L2_nodes': len(catalog['knowledge']),
        'L2_relations': len(catalog['edges']), 'L3_skills': len(catalog['skills']),
        'proposals': len(catalog['proposals']), 'observations': len(catalog['observations']),
        'reflections': len(state['reflections']), 'ingestions': len(state['ingestions']),
        'capture_failures': sum(r['capture_failures'] for r in tasks),
        'capture_status_counts': dict(Counter(r['capture_status'] for r in tasks)),
        'checkpoint_counts': dict(Counter(r['checkpoint_kind'] for r in episodes)),
        'public_test_checkpoint_outcomes': dict(Counter(r['public_test_outcome'] for r in episodes if r['checkpoint_kind'] == 'PUBLIC_TEST_OBSERVATION')),
        'by_official_outcome': grouped}
    assert state_bytes == (LEARNING / 'learning-state.json').read_bytes(), 'Learning changed during snapshot'
    assert catalog_bytes == (LEARNING / 'catalog.json').read_bytes(), 'Catalog changed during snapshot'
    stamp = observed.strftime('%Y%m%dT%H%M%SZ')
    prefix = OUT / ('experience-status-' + stamp)
    data = {'schema': 'skhynix/experience-collection-status/1.0',
        'observed_at_utc': observed.isoformat(),
        'observed_at_kst': observed.astimezone(timezone(timedelta(hours=9))).isoformat(),
        'scope': 'EXPERIENCE_COLLECTION_NOT_MEMORY_EFFECT_EVALUATION',
        'classification_scope': 'OFFICIAL_OUTCOMES_JOINED_FOR_REPORTING_ONLY_NEVER_WRITTEN_TO_MEMORY',
        'summary': summary, 'tasks': sorted(tasks, key=lambda r: r['task_id']),
        'episodes': sorted(episodes, key=lambda r: (r['task_id'], r['cutoff_step'], r['checkpoint_kind'])),
        'evidence': evidence, 'learning_state_sha256': digest(state_bytes), 'catalog_sha256': digest(catalog_bytes)}
    with prefix.with_suffix('.json').open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    paths = {}
    for name, rows in [('tasks', data['tasks']), ('episodes', data['episodes'])]:
        path = Path(str(prefix) + '-' + name + '.csv')
        with path.open('x', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            for row in rows:
                writer.writerow({k: json.dumps(v, sort_keys=True) if isinstance(v, dict) else v for k, v in row.items()})
        paths[name] = str(path)
    print(json.dumps({'observed_at_kst': data['observed_at_kst'], 'summary': summary,
        'audit': reference(prefix.with_suffix('.json')), 'csv': paths}, sort_keys=True))


if __name__ == '__main__':
    main()
