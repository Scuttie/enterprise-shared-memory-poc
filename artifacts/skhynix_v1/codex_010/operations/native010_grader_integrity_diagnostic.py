"""Read-only fixed completed-cell diagnostic; stdout/artifact are allowlisted counts only."""
from pathlib import Path
from collections import Counter
from enum import Enum
import ast
import hashlib
import json
import re
import sys

CENTRAL = Path('/home/trimem-runner/skhynix-codex-010')
TEMP = Path('/mnt/c/Users/jewon/AppData/Local/Temp')
CASES = [(CENTRAL / name / 'execution', arm) for name in
    ('recovery-20428-r1', 'recovery-20428-r2', 'recovery-20438-r1', 'recovery-20438-r2') for arm in ('A', 'C')]
sha = lambda raw: hashlib.sha256(raw).hexdigest()
canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
protected = {}
OUTPUT_NAME = 'native010_grader_integrity_diagnostic.json'
CONTRACT_SHA = 'db5d5e6ea064e3573ce5e7578c54c2df70f25bfd5b7068aeb9be757490030a2f'
EXPECTED_HARNESS_FUNCTIONS = {
 '_resolve_case': {'function_sha256':'873999cbdcf17e47b0817517eec5c41882f8bf443d2e8b76eeb56e1d9489e48c', 'source_sha256':'a095273010175001a6779e365b3b77abb8657c7ac2e4f80b4bc360faa6f09483'},
 'parse_log_sympy': {'function_sha256':'55853f23276e63137711ea2322962841a038bc1228e2d4116852c36195e834d9', 'source_sha256':'cd56156414f8327221e525665ace9b184f7d73e83b272d9eb3f545fb17c2d9bc'}}


def read(path):
    path=Path(path)
    assert path.is_absolute() and path.is_file() and path.stat().st_size<64*1024*1024, 'EVIDENCE_NOT_BOUNDED_FILE'
    assert not any(p.is_symlink() for p in (path,*path.parents)), 'LINKED_EVIDENCE'
    raw = path.read_bytes()
    digest = sha(raw)
    if str(path) in protected:
        assert protected[str(path)] == digest, 'READ_INPUT_CHANGED'
    protected[str(path)] = digest
    return raw


def reference(execution, ref):
    assert ref['access'] == 'RESTRICTED_RAW_NOT_FOR_PUBLIC_LOGS'
    relative = Path(ref['path'])
    assert not relative.is_absolute() and '..' not in relative.parts
    matches = []
    for root in execution.glob('environment/**/official-grader'):
        path = root / relative
        if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve()):
            raw = path.read_bytes()
            if sha(raw) == ref['sha256'] and len(raw) == ref['bytes']:
                matches.append((path, raw))
    assert matches and len({raw for _, raw in matches}) == 1, 'CAPTURED_REFERENCE_NOT_FOUND'
    return read(matches[0][0])


class TestStatus(Enum):
    PASSED = 'PASSED'
    FAILED = 'FAILED'
    ERROR = 'ERROR'
    XFAIL = 'XFAIL'
    SKIPPED = 'SKIPPED'


def main():
    assert sys.platform=='linux' and CENTRAL.is_dir(), 'LINUX_EXPERIMENT_REQUIRED'
    assert all(not (root/OUTPUT_NAME).exists() and not (root/OUTPUT_NAME).is_symlink() for root in (TEMP,CENTRAL)), 'REFUSE_EXISTING_DIAGNOSTIC'
    assert len(CASES)==8 and all((execution/'cells'/arm/'public-result.json').is_file() for execution,arm in CASES), 'ALL_EIGHT_GRADES_REQUIRED_BEFORE_PRIVATE_READ'
    assert sha(read(CENTRAL/'launch-contract.json'))==CONTRACT_SHA, 'FROZEN_CONTRACT_DIFFERS'
    helper_sha=sha(read(TEMP/'native010_grader_integrity_diagnostic.py'))
    plan = json.loads(read(CASES[0][0] / 'plan.json'))
    harness = Path(plan['paths']['harness_root'])
    parser_path, = harness.glob('**/swebench/harness/log_parsers/python.py')
    grading_path, = harness.glob('**/swebench/harness/grading.py')
    namespace = {'re': re, 'TestStatus': TestStatus}
    sources = {}
    for path, names in ((parser_path, ('parse_log_sympy',)), (grading_path, ('_resolve_case',))):
        raw = read(path); source = raw.decode()
        nodes = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name in names]
        assert len(nodes) == len(names)
        for node in nodes:
            segment = ast.get_source_segment(source, node)
            sources[node.name] = {'source_sha256': sha(raw), 'function_sha256': sha(segment.encode())}
            assert sources[node.name]==EXPECTED_HARNESS_FUNCTIONS[node.name], 'PINNED_PUBLIC_HARNESS_FUNCTION_DIFFERS'
            exec(compile('from __future__ import annotations\n' + segment, '<approved-public-harness-function>', 'exec'), namespace)

    constants = {}
    constant_source_sha256 = []
    constant_names = {'START_TEST_OUTPUT', 'END_TEST_OUTPUT', 'TESTS_ERROR', 'TESTS_TIMEOUT',
        'APPLY_PATCH_FAIL', 'RESET_FAILED', 'TEST_EXIT_CODE'}
    for path in harness.glob('**/swebench/harness/constants/**/*.py'):
        constant_raw=read(path);source=constant_raw.decode()
        constant_source_sha256.append(sha(constant_raw))
        for node in ast.parse(source).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in constant_names:
                        constants[target.id] = ast.literal_eval(node.value)
    assert set(constants) == constant_names

    rows = []
    for execution, arm in CASES:
        case_plan=json.loads(read(execution/'plan.json'))
        assert case_plan['paths']['harness_root']==str(harness), 'CASE_HARNESS_ROOT_DIFFERS'
        cell = execution / 'cells' / arm
        public_raw = read(cell / 'public-result.json')
        private_raw = read(cell / 'grader-private.json')
        public = json.loads(public_raw); private = json.loads(private_raw)
        assert public['official'] is True and public['grader_status'] == 'success'
        assert public['agent_completed'] is True and public['grader_private_sha256'] == sha(private_raw)
        assert type(public['resolved']) is bool, 'PUBLIC_RESOLUTION_MUST_BE_BOOLEAN'
        envelope = private['report']['_trimem']
        execution_contract = envelope['execution_contract']
        patch_raw=read(cell/'submission.diff');patch_digest=sha(patch_raw)
        assert patch_digest==public['patch_sha256'], 'PUBLIC_PATCH_DIGEST_DIFFERS'
        assert public['grader_patch_sha256']==execution_contract['submitted_patch_sha256'], 'GRADER_PATCH_CONTRACT_DIFFERS'
        if patch_raw:
            assert patch_digest==public['grader_patch_sha256'] and public['grader_patch_source']=='NATIVE_CODEX_PATCH', 'NONEMPTY_GRADED_PATCH_DIFFERS'
        else:
            assert public['grader_patch_source']=='CANONICAL_FAILED_CELL_NOOP', 'EMPTY_PATCH_FALLBACK_DIFFERS'
        status_raw = reference(execution, envelope['official_test_status'])
        log_raw = reference(execution, envelope['test_output'])
        status = json.loads(status_raw)
        assert len(status) == 1
        instance = next(iter(status.values()))
        assert all(type(instance[key]) is bool for key in ('patch_successfully_applied','patch_exists','infra_failure')), 'STATUS_BOOLEAN_FIELDS_REQUIRED'
        semantics=envelope['semantic_normalization']
        assert all(type(semantics[key]) is int and semantics[key]>=0 for key in ('fail_to_pass_classified','fail_to_pass_expected','fail_to_pass_failures','pass_to_pass_classified','pass_to_pass_expected','pass_to_pass_regressions')), 'SEMANTIC_NUMERIC_COUNTS_REQUIRED'
        assert type(semantics['resolved']) is bool and semantics['resolved']==public['resolved'], 'SEMANTIC_RESOLUTION_DIFFERS'
        text = log_raw.decode('utf-8', errors='replace')
        start, end = constants['START_TEST_OUTPUT'], constants['END_TEST_OUTPUT']
        markers_present = start in text and end in text
        sliced = text.split(start)[1].split(end)[0] if markers_present else text
        parsed = namespace['parse_log_sympy'](sliced, None)
        whole_fallback = not bool(parsed)
        if whole_fallback:
            parsed = namespace['parse_log_sympy'](text, None)
        bad_markers = {key: text.count(constants[key]) for key in
            ('APPLY_PATCH_FAIL', 'RESET_FAILED', 'TESTS_ERROR', 'TESTS_TIMEOUT')}
        exit_match = re.search(re.escape(constants['TEST_EXIT_CODE']) + r':\s*(-?\d+)', text)
        domains = {}
        for domain in ('FAIL_TO_PASS', 'PASS_TO_PASS'):
            result = instance['tests_status'][domain]
            expected = [*result['success'], *result['failure']]
            assert len(set(expected)) == len(expected)
            hist = Counter()
            missing_hashes = []
            missing_recovery = Counter()
            status_identifier_sha256 = {}
            for key in expected:
                resolved_key = namespace['_resolve_case'](key, parsed)
                state = parsed[resolved_key] if resolved_key is not None else 'MISSING'
                assert state in {'PASSED', 'FAILED', 'ERROR', 'XFAIL', 'SKIPPED', 'MISSING'}
                hist[state] += 1
                status_identifier_sha256.setdefault(state,[]).append(sha(key.encode()))
                if resolved_key is None:
                    missing_hashes.append(sha(key.encode()))
                    # Identify only generic name-shape mismatch counts, never names/paths.
                    short = re.split(r'::|:', key)[-1]
                    matched = [v for k, v in parsed.items() if re.split(r'::|:', k)[-1] == short]
                    if matched and len(set(matched)) == 1:
                        missing_recovery['same_terminal_identifier_' + matched[0]] += 1
                    if key in sliced:
                        missing_recovery['identifier_present_in_log'] += 1
            domains[domain] = {'expected': len(expected), 'official_success': len(result['success']),
                'official_failure': len(result['failure']), 'parsed_status_histogram': dict(sorted(hist.items())),
                'expected_id_set_sha256': sha(canonical(sorted(expected))),
                'missing_identifier_sha256': sorted(missing_hashes),
                'missing_identifier_shape_diagnostics': dict(sorted(missing_recovery.items())),
                'status_identifier_sha256': {key:sorted(value) for key,value in sorted(status_identifier_sha256.items())}}
        failure_summary_counts = {}
        for name in ('passed', 'failed', 'errors', 'exceptions', 'skipped', 'xfailed', 'xpassed'):
            values = re.findall(r'\b(\d+)\s+' + name + r'\b', '\n'.join(line for line in sliced.splitlines() if 'tests finished:' in line))
            failure_summary_counts[name] = [int(value) for value in values]
        error_classes = ('AssertionError', 'SyntaxError', 'IndentationError', 'ImportError', 'ModuleNotFoundError',
            'NameError', 'TypeError', 'ValueError', 'RuntimeError', 'AttributeError', 'ZeroDivisionError')
        error_counts = {kind: len(re.findall(r'^\s*' + kind + r'(?::|\s*$)', sliced, re.MULTILINE)) for kind in error_classes}
        rows.append({'run': execution.parent.name, 'cell': arm, 'official_resolved': public['resolved'],
            'agent_completed': public['agent_completed'], 'source_hashes': {'public_result': sha(public_raw),
                'private_grade_envelope': sha(private_raw), 'official_test_status': sha(status_raw), 'test_output': sha(log_raw)},
            'adapter_status_success': envelope['adapter_status']=='SUCCESS', 'harness_invocation_status_success': envelope['harness_invocation_status']=='SUCCESS',
            'submitted_patch_matches_grader_execution_contract': True, 'submitted_patch_sha256': patch_digest,
            'grader_patch_sha256':public['grader_patch_sha256'],'grader_patch_source':public['grader_patch_source'],
            'patch_applied': instance['patch_successfully_applied'], 'patch_exists': instance['patch_exists'],
            'infra_failure': instance['infra_failure'], 'semantic_counts': {key:envelope['semantic_normalization'][key]
                for key in ('fail_to_pass_classified','fail_to_pass_expected','fail_to_pass_failures','pass_to_pass_classified','pass_to_pass_expected','pass_to_pass_regressions','resolved')},
            'test_markers_present': markers_present, 'marker_counts': {'start': text.count(start), 'end': text.count(end)},
            'bad_execution_marker_counts': bad_markers, 'recorded_test_exit_code': int(exit_match[1]) if exit_match else None,
            'parser_whole_log_fallback': whole_fallback, 'parsed_total': len(parsed),
            'parsed_status_histogram': dict(sorted(Counter(parsed.values()).items())),
            'domains': domains, 'runner_summary_numeric_counts': failure_summary_counts,
            'terminal_exception_class_counts': error_counts})

    for path, digest in protected.items():
        assert sha(Path(path).read_bytes()) == digest, 'READ_INPUT_CHANGED_AFTER_DIAGNOSIS'
    native_rows = [row for row in rows if row['run'].startswith('recovery-')]
    assert len(native_rows)==len(rows)==8 and len({(row['run'],row['cell']) for row in rows})==8, 'EXACT_EIGHT_DIAGNOSTIC_ROWS_REQUIRED'
    integrity_pass = all(row['patch_applied'] and not row['infra_failure'] and row['test_markers_present'] and
        not any(row['bad_execution_marker_counts'].values()) and
        not any(domain['parsed_status_histogram'].get('MISSING', 0) for domain in row['domains'].values())
        for row in native_rows)
    aggregate = {}
    for arm in ('A', 'C'):
        matched = [row for row in native_rows if row['cell'] == arm]
        aggregate[arm] = {'completed_attempts': len(matched), 'official_resolved': sum(row['official_resolved'] for row in matched),
            'fail_to_pass_passed': sum(row['domains']['FAIL_TO_PASS']['official_success'] for row in matched),
            'fail_to_pass_expected': sum(row['domains']['FAIL_TO_PASS']['expected'] for row in matched),
            'pass_to_pass_passed': sum(row['domains']['PASS_TO_PASS']['official_success'] for row in matched),
            'pass_to_pass_expected': sum(row['domains']['PASS_TO_PASS']['expected'] for row in matched),
            'expected_identifiers_missing': sum(domain['parsed_status_histogram'].get('MISSING', 0) for row in matched for domain in row['domains'].values())}
    value = {'schema': 'skhynix/native010-grader-integrity-count-diagnostic/1.0', 'status': 'COMPLETE_READ_ONLY',
        'scope': 'EXACT_EIGHT_COMPLETED_NATIVE010_RECOVERY_CELLS',
        'integrity_findings_all_clear':integrity_pass,'frozen_launch_contract_sha256':CONTRACT_SHA,
        'diagnostic_helper_sha256':helper_sha,
        'scientific_role': 'SECONDARY_POSTHOC_GRADING_INTEGRITY_DIAGNOSTIC',
        'primary_issue_solve_rate_unchanged': True, 'distinct_reused_tasks': 2,
        'replicates_are_not_independent_task_samples': True, 'aggregate': aggregate,
        'interpretation': 'Secondary counts of official test execution. All eight fixed issue-attempt outcomes remain in the primary endpoint. Inspect missing identifiers, patch application and infrastructure fields before interpreting partial progress. Parsed totals may include multiple parser keys for one failure; expected-domain counts are authoritative.',
        'harness_function_provenance': sources, 'public_harness_constant_source_sha256':sorted(constant_source_sha256), 'rows': rows, 'protected_files_verified': len(protected),
        'official_grader_calls': 0, 'test_commands_executed': 0, 'model_calls': 0,
        'hidden_fixture_or_gold_patch_files_opened': False, 'test_names_or_paths_exported': False,
        'raw_test_logs_exported': False, 'expected_identifiers_used_only_for_opaque_status_counts': True,
        'evidence_mutations': 0}
    path=TEMP/OUTPUT_NAME;destination=CENTRAL/OUTPUT_NAME
    payload=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
    assert not path.exists() and not destination.exists(), 'REFUSE_EXISTING_DIAGNOSTIC'
    with path.open('xb') as stream:stream.write(payload)
    with destination.open('xb') as stream:stream.write(payload)
    assert path.read_bytes()==destination.read_bytes()==payload, 'DIAGNOSTIC_PUBLIC_COPY_DIFFERS'
    print(json.dumps({'artifact':OUTPUT_NAME,'sha256':sha(payload),'protected_files_verified':len(protected),
        'aggregate':aggregate,'integrity_findings_all_clear':integrity_pass,
        'rows':[{k:row[k] for k in ('run','cell','official_resolved','patch_applied','infra_failure',
            'parsed_status_histogram','domains','runner_summary_numeric_counts','terminal_exception_class_counts')} for row in rows]},sort_keys=True))

if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status':'SECONDARY_DIAGNOSTIC_FAILED','error_type':type(exc).__name__,
            'error_message_sha256':sha(str(exc).encode()),'private_error_detail_omitted':True}))
        raise SystemExit(1)
