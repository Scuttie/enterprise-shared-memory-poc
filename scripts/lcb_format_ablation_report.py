"""Metadata-only paired analysis of the preregistered submission ablation."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import random

METRICS = ('fixed_candidate_success', 'submission_valid', 'anchor_valid', 'candidate_same')


def require(ok):
    if not ok:
        raise ValueError('ANALYSIS_AUDIT_FAILED')


def reference(path):
    raw = path.read_bytes()
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def aggregate(protocol, records):
    require(len(records) == len(protocol['trials']))
    byid = {r['trial_id']: r for r in records}
    require(len(byid) == len(records))
    lookup = {}
    for t in protocol['trials']:
        r = byid[t['trial_id']]
        require(all(r[k] == t[k] for k in ('task_id', 'arm', 'repeat')))
        require(all(r['metrics'][m] is None or type(r['metrics'][m]) is bool for m in METRICS))
        lookup[t['task_id'], t['repeat'], t['arm']] = r
    totals = {}
    for arm in ('KEEP', 'DROP'):
        rows = [r for r in records if r['arm'] == arm]
        totals[arm] = {}
        for m in METRICS:
            values = [r['metrics'][m] for r in rows]
            successes, known = sum(v is True for v in values), sum(v is not None for v in values)
            totals[arm][m] = {'successes': successes, 'observed': known, 'null': len(values) - known,
                              'scheduled': len(values), 'rate': successes / known if known else None}
    tasks = []
    control_ids = {r['task_id'] for r in protocol['checkpoints'] if r['no_memory_control']}
    for task_id in protocol['task_ids']:
        row = {'task_id': task_id, 'no_memory_control': task_id in control_ids, 'metrics': {}}
        for m in METRICS:
            values = {arm: [lookup[task_id, i, arm]['metrics'][m] for i in range(1, protocol['repeats'] + 1)] for arm in ('KEEP', 'DROP')}
            ds = [int(k) - int(d) for k, d in zip(values['KEEP'], values['DROP']) if k is not None and d is not None]
            row['metrics'][m] = {**values, 'paired_observations': len(ds),
                                 'paired_mean_difference': sum(ds) / len(ds) if ds else None}
        tasks.append(row)
    contrasts = {}
    for cohort in ('all24', 'memory_exposed23', 'no_memory_control'):
        selected = [t for t in tasks if cohort == 'all24' or t['no_memory_control'] == (cohort == 'no_memory_control')]
        contrasts[cohort] = {}
        for m in METRICS:
            diffs = [t['metrics'][m]['paired_mean_difference'] for t in selected if t['metrics'][m]['paired_mean_difference'] is not None]
            rng = random.Random(240924)
            boot = sorted(sum(rng.choices(diffs, k=len(diffs))) / len(diffs) for _ in range(20000)) if len(diffs) > 1 else []
            contrasts[cohort][m] = {'tasks_scheduled': len(selected), 'tasks_with_paired_observations': len(diffs),
                                     'paired_observations': sum(t['metrics'][m]['paired_observations'] for t in selected),
                                     'mean_task_difference': sum(diffs) / len(diffs) if diffs else None,
                                     'task_cluster_bootstrap_95_percentile': [boot[499], boot[19499]] if boot else None}
    return {'arm_totals': totals, 'task_results': tasks, 'contrasts': contrasts}


def report(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    protocol_path = root / 'protocol.json'
    protocol = json.loads(protocol_path.read_bytes())
    result_path = root / 'results.json'
    result = json.loads(result_path.read_bytes())
    require(result['status'] == 'COMPLETE' and result['protocol_reference'] == reference(protocol_path))
    rows = result['trials']
    receipts, classifications, shapes, refs = [], Counter(), {a: Counter() for a in ('KEEP', 'DROP')}, []
    for row in rows:
        ref = row['receipt_reference']
        path = Path(ref['path'])
        require(reference(path) == ref)
        receipt = json.loads(path.read_bytes())
        require(receipt['metrics'] == row['metrics'])
        for evidence in receipt['output_references']:
            require(reference(Path(evidence['path'])) == evidence)
        receipts.append(row)
        refs.append(ref)
        classifications[row['metrics']['classification']] += 1
        action_path = path.parent / 'action.json'
        if action_path.exists():
            require(receipt['action_reference'] == reference(action_path))
            action = json.loads(action_path.read_bytes())
            shapes[row['arm']][action['outcome']['trace_steps_container_type']] += 1
    for ref in protocol['source_references']:
        require(reference(Path(ref['path'])) == ref)
    for trial in protocol['trials']:
        for kind in ('packet', 'prompt', 'history'):
            require(reference(root / trial[kind + '_path'])['sha256'] == trial[kind + '_sha256'])
    summary = {'schema': 'lcb-format-ablation-analysis/1', 'protocol_reference': reference(protocol_path),
               'results_reference': reference(result_path), 'receipt_references': refs,
               'requested_model': protocol['requested_model'], 'reasoning_effort': protocol['reasoning_effort'],
               'classifications': dict(classifications), 'trace_container_types': {a: dict(v) for a, v in shapes.items()},
               'source_and_input_hashes_unchanged': True, 'new_grader_calls': 0,
               'interpretation': protocol['interpretation'], **aggregate(protocol, receipts)}
    output.mkdir(parents=True, exist_ok=True)
    with (output / 'results-001.json').open('xb') as f:
        f.write(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2).encode() + b'\n')
    with (output / 'paired-001.csv').open('x', newline='', encoding='utf8') as f:
        writer = csv.writer(f)
        writer.writerow(['task_id', 'no_memory_control', 'KEEP_primary_3_repeats', 'DROP_primary_3_repeats', 'primary_difference', 'KEEP_format_3_repeats', 'DROP_format_3_repeats'])
        for t in summary['task_results']:
            m, s = t['metrics']['fixed_candidate_success'], t['metrics']['submission_valid']
            writer.writerow([t['task_id'], t['no_memory_control'], json.dumps(m['KEEP']), json.dumps(m['DROP']), m['paired_mean_difference'], json.dumps(s['KEEP']), json.dumps(s['DROP'])])
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    r = report(args.root, args.output)
    print(json.dumps({'arm_totals': r['arm_totals'], 'contrasts': r['contrasts'], 'classifications': r['classifications']}))
