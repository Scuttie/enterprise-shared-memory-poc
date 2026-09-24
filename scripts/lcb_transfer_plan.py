"""Preregister transfer cohorts using existing split metadata only.

This module has no model, task-payload, network, or grader access. The plan is
immutable on disk: an identical invocation can verify it, never replace it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'lcb-transfer-plan/1'
SEED = 'skhynix-lcb-004/transfer/v1'
LIMITS = {'tool_actions': 24, 'public_tests': 4, 'task_seconds': 600,
          'sessions': 4, 'code_bytes': 65536, 'prompt_bytes': 196608,
          'context_bytes': 48000, 'memory_bytes': 12000, 'subtasks': 3}
DIFFICULTIES = ('easy', 'medium', 'hard')
SPLIT_IDENTITY = ('dataset_id', 'source_revision', 'release', 'source_hashes',
    'split_policy', 'pilot_policy', 'train_ids', 'valid_ids', 'test_ids',
    'pilot_ids', 'train_pilot_ids', 'counts', 'task_descriptors', 'task_families',
    'family_reassignments', 'public_tasks_reference', 'pilot_difficulty_counts',
    'train_pilot_difficulty_counts')


class PlanError(ValueError):
    """Metadata-only error codes, never payload-bearing exceptions."""


def require(condition, code):
    if not condition:
        raise PlanError(code)


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False,
                       separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def reference(path, root=ROOT):
    path, root = Path(path).resolve(), Path(root).resolve()
    require(path.is_relative_to(root), 'SOURCE_OUTSIDE_REPOSITORY')
    raw = path.read_bytes()
    return {'path': path.relative_to(root).as_posix(), 'sha256': digest(raw), 'bytes': len(raw)}


def verify_references(refs, root=ROOT):
    root = Path(root).resolve()
    for ref in refs.values():
        path = root / ref['path']
        require(reference(path, root) == ref, 'SOURCE_REFERENCE_CHANGED')


def rank(seed, phase, identity):
    return digest((seed + '\0' + phase + '\0' + identity).encode('utf-8')), identity


def metadata(split):
    require(split.get('schema') == 'trimem/lcb-split/1.0', 'SPLIT_SCHEMA_DIFFERS')
    partitions, seen = {}, set()
    for partition in ('train', 'valid', 'test'):
        ids = split[partition + '_ids']
        require(isinstance(ids, list) and all(isinstance(i, str) and i for i in ids)
                and len(ids) == len(set(ids)), 'INVALID_PARTITION_IDS')
        require(not seen.intersection(ids), 'PARTITIONS_OVERLAP')
        seen.update(ids)
        partitions.update((identity, partition) for identity in ids)
    rows = split['task_descriptors']
    require(isinstance(rows, list) and len(rows) == len(seen), 'DESCRIPTOR_COVERAGE_DIFFERS')
    descriptors = {row['task_id']: row for row in rows}
    require(set(descriptors) == seen and set(split['task_families']) == seen,
            'DESCRIPTOR_COVERAGE_DIFFERS')
    family_partitions = {}
    for identity, row in descriptors.items():
        family = row['family_id']
        require(isinstance(family, str) and family and
                family == split['task_families'][identity], 'FAMILY_IDENTITY_DIFFERS')
        require(row['split'] == partitions[identity] and row['difficulty'] in DIFFICULTIES,
                'DESCRIPTOR_PARTITION_OR_DIFFICULTY_DIFFERS')
        family_partitions.setdefault(family, set()).add(row['split'])
    require(all(len(parts) == 1 for parts in family_partitions.values()),
            'FAMILY_CROSSES_EXISTING_PARTITIONS')
    for key, partition in (('train_pilot_ids', 'train'), ('pilot_ids', 'valid')):
        ids = split[key]
        require(isinstance(ids, list) and len(ids) == len(set(ids)) and
                set(ids).issubset(set(split[partition + '_ids'])), 'OLD_PILOT_IDENTITY_DIFFERS')
    return descriptors


def whole_families(groups, count, *, seed, phase):
    """Exact subset sum, first solution in deterministic family hash order."""
    require(type(count) is int and count > 0, 'INVALID_COHORT_SIZE')
    choices = {0: ()}
    for family in sorted(groups, key=lambda item: rank(seed, phase, item)):
        size = len(groups[family])
        for subtotal in sorted(tuple(choices), reverse=True):
            target = subtotal + size
            if target <= count and target not in choices:
                choices[target] = choices[subtotal] + (family,)
        if count in choices:
            return set(choices[count])
    raise PlanError('EXACT_WHOLE_FAMILY_COHORT_UNAVAILABLE')


def build_plan(split, config, *, seed=SEED, discovery_size=80,
               verification_size=40, validation_size=60, source_references=None):
    rows = metadata(split)
    require(isinstance(seed, str) and seed and '\0' not in seed, 'INVALID_SELECTION_SEED')
    require(config.get('requested_model') == 'gpt-5.6-luna' and
            config.get('reasoning_effort') == 'low' and type(config.get('workers')) is int and
            config.get('workers') == 2 and config.get('limits') == LIMITS and
            all(type(value) is int for value in config.get('limits', {}).values()) and
            type(config.get('repeats', 1)) is int and config.get('repeats', 1) == 1,
            'MODEL_OR_BUDGET_CONTRACT_DIFFERS')
    require(type(validation_size) is int and validation_size > 0 and
            validation_size % 3 == 0, 'VALIDATION_SIZE_MUST_ALLOW_EQUAL_DIFFICULTIES')
    controls = config['infrastructure_control_excluded_train_ids']
    require(isinstance(controls, list) and len(controls) == len(set(controls)) and
            set(controls).issubset(set(split['train_ids'])), 'CONTROL_EXCLUSION_OUTSIDE_TRAIN')
    excluded_train = set(split['train_pilot_ids']) | set(controls)
    excluded_families = {rows[i]['family_id'] for i in excluded_train}
    groups = {}
    for identity in split['train_ids']:
        family = rows[identity]['family_id']
        if family not in excluded_families:
            groups.setdefault(family, []).append(identity)
    discovery_families = whole_families(groups, discovery_size, seed=seed, phase='discovery-family')
    remaining = {family: ids for family, ids in groups.items() if family not in discovery_families}
    verification_families = whole_families(remaining, verification_size,
                                          seed=seed, phase='verification-family')
    discovery = sorted((i for f in discovery_families for i in groups[f]),
                       key=lambda i: rank(seed, 'discovery-task', i))
    verification = sorted((i for f in verification_families for i in groups[f]),
                          key=lambda i: rank(seed, 'verification-task', i))
    eligible_valid = set(split['valid_ids']) - set(split['pilot_ids'])
    quota, validation = validation_size // 3, []
    for difficulty in DIFFICULTIES:
        candidates = sorted((i for i in eligible_valid if rows[i]['difficulty'] == difficulty),
                            key=lambda i: rank(seed, 'validation-task', i))
        require(len(candidates) >= quota, 'VALIDATION_DIFFICULTY_QUOTA_UNAVAILABLE')
        validation.extend(candidates[:quota])
    validation.sort(key=lambda i: rank(seed, 'validation-task', i))
    old_valid_families = {rows[i]['family_id'] for i in split['pilot_ids']}
    family_fresh_valid = [i for i in eligible_valid if rows[i]['family_id'] not in old_valid_families]
    old_family_overlap = [i for i in validation if rows[i]['family_id'] in old_valid_families]

    def cohort(ids, partition):
        return {'partition': partition, 'task_count': len(ids), 'task_ids': ids,
                'family_count': len({rows[i]['family_id'] for i in ids}),
                'family_ids': sorted({rows[i]['family_id'] for i in ids}),
                'difficulty_counts': {d: sum(rows[i]['difficulty'] == d for i in ids) for d in DIFFICULTIES}}

    total = discovery_size + verification_size + 3 * validation_size + 2 * len(split['test_ids'])
    plan = {
        'schema': SCHEMA, 'experiment_id': 'skhynix-lcb-004',
        'status': 'PREREGISTERED_METADATA_ONLY', 'model_calls': 0, 'private_grader_calls': 0,
        'selection_seed': seed, 'source_references': source_references or {},
        'dataset': {k: split[k] for k in ('dataset_id', 'source_revision', 'release')},
        'source_partition_counts': {p: len(split[p + '_ids']) for p in ('train', 'valid', 'test')},
        'requested_model': 'gpt-5.6-luna', 'reasoning_effort': 'low', 'workers': 2,
        'repeats': 1, 'limits': dict(LIMITS),
        'cohorts': {'discovery': cohort(discovery, 'train'),
                    'verification': cohort(verification, 'train'),
                    'validation': cohort(validation, 'valid'),
                    'test': cohort(list(split['test_ids']), 'test')},
        'exclusions': {
            'old_train_pilot_ids': sorted(split['train_pilot_ids']),
            'infrastructure_control_ids': sorted(controls),
            'train_excluded_family_ids': sorted(excluded_families),
            'train_family_closure_excluded_ids': sorted(i for i in split['train_ids']
                                                       if rows[i]['family_id'] in excluded_families),
            'old_valid_pilot_ids': sorted(split['pilot_ids'])},
        'selection_policy': {
            'inputs': 'Only existing task IDs, difficulty, family and partition metadata; no outcomes or task text.',
            'rank': 'SHA256(UTF8(seed + NUL + phase + NUL + identity)), identity tie-break.',
            'train': 'Exclude prior TRAIN pilot and infrastructure-control families. Select whole families by exact subset sum: family hash order, descending reachable totals, keep first solution. Discovery first, verification from remaining families.',
            'validation': 'Exclude old VALID pilot IDs; equal easy/medium/hard quotas by task hash, then task-hash launch order.',
            'test': 'Every original TEST task, in unchanged original order.',
            'evaluation_order': 'VALID cycles (OFF,ON,L1ONLY), (ON,L1ONLY,OFF), (L1ONLY,OFF,ON) by task index. TEST alternates OFF-first and ON-first. Scheduling order is not completion order.',
            'original_family_partitions_unchanged': True,
            'discovery_verification_task_disjoint': True,
            'discovery_verification_family_disjoint': True,
            'selection_uses_hidden_results': False},
        'validation_freshness': {
            'task_disjoint_from_old_pilot': True,
            'eligible_unseen_tasks': len(eligible_valid),
            'eligible_tasks_in_unseen_families': len(family_fresh_valid),
            'selected_tasks_sharing_old_pilot_family': len(old_family_overlap),
            'selected_overlap_task_ids': old_family_overlap,
            'limitation': 'Fresh task IDs do not imply fresh families. The original VALID partition has fewer than 60 wholly unseen-family tasks.' if len(family_fresh_valid) < validation_size else 'Task and prior-family overlap counts are disclosed; selection uses task-level freshness.'},
        'memory_policy': {
            'discovery': 'Native TRAIN arm, no bank. Collect public-only L1 evidence and candidate private L3 procedures.',
            'verification': 'Native ON arm with a frozen provisional bank. Independent TRAIN tasks may support or reject transfer and private L3 promotion; never use VALID or TEST as promotion support.',
            'verification_candidate_assignment': {
                'policy': 'round_robin', 'candidate_order': 'ascending candidate_id',
                'task_order': 'cohorts.verification.task_ids',
                'index': 'verification_task_index modulo provisional_candidate_count',
                'zero_candidates': 'SKIPPED_NOT_READY; no verification model calls'},
            'evaluation_arms': ['OFF', 'ON'], 'on_layers': ['L1', 'promoted_private_L3'],
            'validation_secondary_condition': {'condition': 'L1ONLY', 'native_arm': 'ON',
                'enabled_layers': ['L1'], 'task_count': validation_size,
                'purpose': 'Separate the private L3 contribution from a larger L1 bank; secondary VALID comparison only.'},
            'primary_comparison': 'OFF versus ON on VALID and TEST; L1ONLY does not replace the primary arms.',
            'l2': 'No forced L2 injection or additional L2 treatment.',
            'bank_frozen_before_validation': True, 'bank_updates_during_validation_or_test': False,
            'private_grades_used_for_selection_or_promotion': False,
            'promotion_protocol': 'A separately frozen implementation and public-evidence promotion contract are required before model execution.',
            'extra_promotion_verification': 'Any additional model solve requires an additive preregistered budget; none is authorized by this schedule.'},
        'solve_accounting': {'discovery': discovery_size, 'verification': verification_size,
            'validation_off_on': 2 * validation_size, 'validation_l1only': validation_size,
            'test_off_on': 2 * len(split['test_ids']),
            'initial_model_solves': total, 'maximum_task_seconds_per_solve': LIMITS['task_seconds'],
            'additional_model_solves_preregistered': 0,
            'verification_and_evaluation_conditional_on_readiness': True},
        'execution_policy': {
            'phase_order': ['DISCOVERY', 'VERIFICATION', 'VALID', 'TEST'],
            'cell_identity': ['phase', 'task_id', 'condition'],
            'distinct_conditions_require_independent_native_cells': True,
            'submission_contract': 'Identical explicit source_lesson schema for both evaluation arms; original validator and limits retained.',
            'shared_test_execution_budget': {'limit': 4,
                'tools': ['run_public_tests', 'run_command'], 'scope': 'per task/arm solve',
                'identical_for_off_on': True, 'additional_test_budget': 0},
            'readiness_gates': {
                'zero_provisional_candidates': 'Mark verification SKIPPED_NOT_READY; do not launch those model calls.',
                'zero_promoted_private_l3_skills': 'Report NOT_READY; do not launch VALID or TEST, do not add training, advance the separate DevEval workstream.',
                'minimum_final_private_l3_skills': 1,
                'skipped_planned_cells': 'Remain explicitly unexecuted with null outcomes; never recorded as solved or wrong.'},
            'no_automatic_retries_of_partial_solves': True,
            'hidden_feedback_to_model': False,
            'primary_denominator': 'All preregistered task/arm cells; model protocol failures count as failures, infrastructure unresolved remains null.',
            'glm': 'Company reproduction package only; no GLM calls in this plan.'},
    }
    plan['schedule_sha256'] = digest(canonical(schedule(plan)))
    return plan


def schedule(plan):
    rows = []
    phases = {'discovery': 'DISCOVERY', 'verification': 'VERIFICATION',
              'validation': 'VALID', 'test': 'TEST'}
    for phase in ('discovery', 'verification', 'validation', 'test'):
        for index, identity in enumerate(plan['cohorts'][phase]['task_ids']):
            if phase == 'discovery':
                conditions = ('TRAIN',)
            elif phase == 'verification':
                conditions = ('PROVISIONAL',)
            elif phase == 'validation':
                order = ('OFF', 'ON', 'L1ONLY')
                offset = index % 3
                conditions = order[offset:] + order[:offset]
            else:
                conditions = ('OFF', 'ON') if index % 2 == 0 else ('ON', 'OFF')
            for condition in conditions:
                native_arm = condition if condition in ('TRAIN', 'OFF') else 'ON'
                rows.append({'ordinal': len(rows) + 1, 'phase': phases[phase], 'task_id': identity,
                             'condition': condition, 'native_arm': native_arm})
    return rows


def from_files(split_path, public_split_path, config_path, *, root=ROOT, seed=SEED):
    paths = {'split': Path(split_path), 'public_split': Path(public_split_path),
             'exclusion_config': Path(config_path), 'planner': Path(__file__)}
    refs = {key: reference(path, root) for key, path in paths.items()}
    split, public_split, config = (json.loads(paths[key].read_bytes())
                                   for key in ('split', 'public_split', 'exclusion_config'))
    require(all(split.get(key) == public_split.get(key) for key in SPLIT_IDENTITY),
            'FINAL_PUBLIC_SPLIT_IDENTITY_DIFFERS')
    require(config['split_sha256'] == refs['public_split']['sha256'] and
            (Path(root) / config['split_path']).resolve() == paths['public_split'].resolve(),
            'EXCLUSION_CONFIG_SPLIT_BINDING_DIFFERS')
    require([len(split[p + '_ids']) for p in ('train', 'valid', 'test')] == [767, 106, 182]
            and len(split['pilot_ids']) == len(split['train_pilot_ids']) == 24,
            'ORIGINAL_LCB_COHORT_COUNTS_DIFFER')
    plan = build_plan(split, config, seed=seed, source_references=refs)
    verify_references(refs, root)
    return plan


def write_once(path, plan):
    path = Path(path)
    raw = canonical(plan)
    if path.exists():
        require(path.read_bytes() == raw, 'PREREGISTRATION_ALREADY_EXISTS_WITH_DIFFERENT_BYTES')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['create', 'verify'])
    parser.add_argument('--split', type=Path, default=ROOT / 'configs/skhynix_v1/lcb_001_split.json')
    parser.add_argument('--public-split', type=Path, default=ROOT / 'configs/skhynix_v1/lcb_001_public_split.json')
    parser.add_argument('--source-config', type=Path, default=ROOT / 'configs/skhynix_v1/lcb_002_luna_pilot.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'configs/skhynix_v1/lcb_004_transfer_plan.json')
    args = parser.parse_args(argv)
    try:
        plan = from_files(args.split, args.public_split, args.source_config)
        if args.mode == 'verify':
            require(args.output.is_file() and args.output.read_bytes() == canonical(plan), 'PLAN_VERIFICATION_FAILED')
        else:
            write_once(args.output, plan)
        print(json.dumps({'status': 'VERIFIED' if args.mode == 'verify' else 'PREREGISTERED',
            'schema': SCHEMA, 'plan_sha256': digest(canonical(plan)),
            'counts': {name: cohort['task_count'] for name, cohort in plan['cohorts'].items()},
            'model_solves': plan['solve_accounting']['initial_model_solves'], 'model_calls': 0,
            'prior_valid_family_overlap': plan['validation_freshness']['selected_tasks_sharing_old_pilot_family']}, sort_keys=True))
        return 0
    except (KeyError, TypeError, ValueError, OSError) as exc:
        print(json.dumps({'status': 'ERROR', 'error_code': str(exc) if isinstance(exc, PlanError)
                          else 'INVALID_OR_UNAVAILABLE_PLAN_INPUT'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
