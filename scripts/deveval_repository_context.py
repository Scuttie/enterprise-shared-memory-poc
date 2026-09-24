"""Sanitized DevEval repository views and evidence-bound static L2 retrieval.

Only this manager-side module reads the pinned archive/task metadata. Every
benchmark body in a project is removed before source is written or parsed.
The model-facing reader sees the same sanitized files in either arm. L2 is a
static navigation aid over those files, not a gold dependency/oracle annotation.
"""
from __future__ import annotations

import ast
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile
import textwrap
import tokenize
from io import BytesIO

SCHEMA = 'deveval/sanitized-repository/1'
POLICY = 'ALL_PROJECT_BENCHMARK_BODIES_AND_PRIVATE_TESTS_REMOVED_BEFORE_AST'
MAX_PROJECT_BYTES = 128 * 1024 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024


class RepositoryContextError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise RepositoryContextError(code)


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': file_sha(path), 'bytes': path.stat().st_size}


def checked(ref):
    path = Path(ref['path'])
    if not path.is_absolute():
        # Portable plan references are explicitly repository-root-relative.
        path = Path(__file__).resolve().parents[1].joinpath(*relative(ref['path']).parts)
    require(path.is_file() and not path.is_symlink(), 'REFERENCE_MISSING_OR_LINK')
    require(file_sha(path) == ref['sha256'] and ('bytes' not in ref or path.stat().st_size == ref['bytes']), 'REFERENCE_CHANGED')
    return path.resolve()


def relative(path):
    require(isinstance(path, str) and path and '\\' not in path and ':' not in path and '\x00' not in path, 'UNSAFE_RELATIVE_PATH')
    value = PurePosixPath(path)
    require(not value.is_absolute() and not any(p in ('.', '..') for p in path.split('/')), 'UNSAFE_RELATIVE_PATH')
    return value


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(payload)


def _metadata(path):
    # Read structurally; no contents are logged or emitted by this module.
    rows = [json.loads(line) for line in path.read_bytes().splitlines() if line.strip()]
    require(rows and len({r['namespace'] for r in rows}) == len(rows), 'METADATA_TASK_IDENTITY')
    return rows


def _private_path(path, explicit, *, target_file=False):
    parts = PurePosixPath(path).parts
    lower = [p.lower() for p in parts]
    name = lower[-1]
    excluded = {'tests', 'test', 'testing', 'fixtures', 'fixture', '__pycache__', 'build', 'dist'}
    if not target_file:
        excluded.update(('benchmarks', 'examples', 'docs', 'doc'))
    return (path in explicit or any(p.startswith('.') or p in excluded or p.endswith('.egg-info') for p in lower)
            or name in ('conftest.py', 'test.py', 'tests.py') or (name == 'setup.py' and not target_file)
            or name.startswith('test_') or name.endswith(('_test.py', '_tests.py')))


def _decode(raw):
    try:
        encoding, _ = tokenize.detect_encoding(BytesIO(raw).readline)
        return raw.decode(encoding)
    except (SyntaxError, UnicodeError, LookupError):
        raise RepositoryContextError('SOURCE_ENCODING_INVALID') from None


def _redact(raw, rows):
    lines = _decode(raw).splitlines(keepends=True)
    occupied = set()
    removed = 0
    for row in sorted(rows, key=lambda r: r['body_position'][0]):
        body, signature = row['body_position'], row['signature_position']
        require(isinstance(body, list) and len(body) == 2 and all(type(n) is int for n in body)
                and isinstance(signature, list) and len(signature) == 2 and all(type(n) is int for n in signature), 'POSITION_SHAPE')
        start, end = body
        require(1 <= signature[0] <= signature[1] < start <= end <= len(lines), 'BODY_SIGNATURE_BOUNDARY')
        # Upstream body_position excludes leading docstrings. Those original
        # source strings are not our public requirement authority, so remove
        # the entire suite following the signature before any AST parse.
        start = signature[1] + 1
        positions = set(range(start, end + 1))
        require(not occupied.intersection(positions), 'OVERLAPPING_TARGET_BODIES')
        occupied.update(positions)
        indent = row.get('indent')
        require(type(indent) is int and 0 <= indent <= 80, 'BODY_INDENT_INVALID')
        # Signature lines, not gold body text, establish the replacement indent.
        header = ''.join(lines[signature[0] - 1:signature[1]])
        require(re.search(r'\b(?:async\s+)?def\s+[A-Za-z_]\w*\s*\(', header) is not None, 'TARGET_SIGNATURE_NOT_FUNCTION')
        lines[start - 1:end] = [' ' * indent + 'pass  # BENCHMARK_TARGET_BODY_WITHHELD\n'] + ['\n'] * (end - start)
        removed += end - start + 1
    text = ''.join(lines)
    # Normalize encoding declaration because materialized bytes are always UTF-8.
    normalized = text.splitlines(keepends=True)
    for index in range(min(2, len(normalized))):
        normalized[index] = re.sub(r'coding[:=]\s*[-\w.]+', 'coding: utf-8', normalized[index])
    text = ''.join(normalized)
    try:
        parsed = ast.parse(text)
    except (SyntaxError, ValueError):
        raise RepositoryContextError('SANITIZED_SOURCE_NOT_PARSEABLE') from None
    # AST exists only after redaction. Verify every target became exactly pass.
    functions = [n for n in ast.walk(parsed) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for row in rows:
        sigstart, sigend = row['signature_position']
        matches = [n for n in functions if sigstart <= n.lineno <= sigend]
        require(len(matches) == 1 and len(matches[0].body) == 1 and isinstance(matches[0].body[0], ast.Pass), 'TARGET_BODY_NOT_FULLY_MASKED')
    return text.encode('utf-8'), removed, len(lines)


def _module(path):
    parts = list(PurePosixPath(path).with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts)


def _attribute(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _attribute(node.value)
        return prefix + '.' + node.attr if prefix else ''
    return ''


def build_relations(files):
    """Input mapping contains sanitized text only; no private metadata accepted."""
    nodes, edges, imported, pending = {}, [], {}, []
    module_paths = {_module(path): path for path in files}

    def resolve_module(name):
        choices = [path for module, path in module_paths.items() if module == name or module.endswith('.' + name)]
        return choices[0] if len(choices) == 1 else None

    for path, text in sorted(files.items()):
        tree = ast.parse(text)
        owner = 'file:' + path
        nodes[owner] = {'id': owner, 'kind': 'module', 'path': path, 'symbol': _module(path), 'line': 1}
        imported[path] = {}

        def visit(node, scope, parent):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    name = '.'.join(scope + [child.name])
                    identity = 'symbol:' + path + ':' + name
                    nodes[identity] = {'id': identity, 'kind': 'class' if isinstance(child, ast.ClassDef) else 'function',
                                       'path': path, 'symbol': name, 'line': child.lineno, 'end_line': child.end_lineno}
                    edges.append({'kind': 'OWNS', 'source': parent, 'target': identity, 'path': path, 'line': child.lineno})
                    visit(child, scope + [child.name], identity)
                elif isinstance(child, (ast.Import, ast.ImportFrom)):
                    for alias in child.names:
                        if isinstance(child, ast.Import):
                            full, local = alias.name, alias.asname or alias.name.split('.')[0]
                        else:
                            package = _module(path).split('.')[:-1] if PurePosixPath(path).name != '__init__.py' else _module(path).split('.')
                            prefix = '.'.join(package[:len(package) - child.level + 1]) if child.level else ''
                            full = '.'.join(p for p in (prefix, child.module or '', alias.name) if p)
                            local = alias.asname or alias.name
                        imported[path][local] = full
                        pending.append(('IMPORTS', parent, full, path, child.lineno, scope))
                else:
                    if isinstance(child, ast.Call):
                        name = _attribute(child.func)
                        if name:
                            pending.append(('CALLS', parent, name, path, child.lineno, scope))
                    visit(child, scope, parent)
        visit(tree, [], owner)

    for kind, owner, name, path, line, scope in pending:
        target = None
        candidates = []
        if kind == 'CALLS':
            if name.startswith(('self.', 'cls.')) and len(scope) >= 2:
                candidates.append('symbol:' + path + ':' + '.'.join(scope[:-1] + name.split('.')[1:]))
            candidates.extend('symbol:' + path + ':' + '.'.join(scope[:n] + [name]) for n in range(len(scope), -1, -1))
            target = next((candidate for candidate in candidates if candidate in nodes), None)
        parts = name.split('.')
        expanded = '.'.join([imported[path].get(parts[0], parts[0]), *parts[1:]]) if kind == 'CALLS' else name
        if target is None:
            for split in range(len(expanded.split('.')), 0, -1):
                prefix = '.'.join(expanded.split('.')[:split])
                mapped = resolve_module(prefix)
                suffix = '.'.join(expanded.split('.')[split:])
                candidate = ('symbol:' + mapped + ':' + suffix) if mapped and suffix else ('file:' + mapped if mapped else None)
                if candidate in nodes:
                    target = candidate
                    break
        edges.append({'kind': kind, 'source': owner, 'target': target, 'name': name,
                      'resolved': target is not None, 'path': path, 'line': line})
    return {'nodes': [nodes[k] for k in sorted(nodes)], 'edges': sorted(edges, key=lambda e: (e['path'], e['line'], e['kind'], e['source'], str(e['target']))),
            'claim': 'STATIC_VISIBLE_SYNTAX_NOT_RUNTIME_CALLGRAPH'}


def materialize_repository(source_archive_reference, metadata_reference, output_root, *, project, plan_reference):
    archive_path, metadata_path, plan_path = map(checked, (source_archive_reference, metadata_reference, plan_reference))
    relative(project)
    plan = json.loads(plan_path.read_bytes())
    require(plan.get('schema') == 'deveval/repository-plan/1' and
            plan.get('source_archive_reference') == source_archive_reference and
            plan.get('metadata_reference') == metadata_reference, 'PLAN_SOURCE_BINDING')
    planned_projects = [p for p in plan.get('projects', []) if p.get('project') == project]
    require(len(planned_projects) == 1, 'PROJECT_NOT_IN_PLAN')
    all_rows = _metadata(metadata_path)
    rows = [r for r in all_rows if r['project_path'] == project]
    require(rows, 'PROJECT_WITHOUT_BENCHMARK_TASKS')
    require(planned_projects[0].get('all_benchmark_target_count') == len(rows), 'PLAN_TARGET_COUNT_CHANGED')
    selected = [r for r in plan.get('tasks', []) if r.get('project') == project]
    selected_ids = [r['task_id'] for r in selected]
    require(selected and len(selected_ids) == len(set(selected_ids)) and
            set(selected_ids) <= {r['namespace'] for r in rows} and
            all(r.get('phase') in ('DISCOVERY', 'VERIFICATION', 'VALID', 'TEST') for r in selected), 'PLAN_TASK_MEMBERSHIP')
    by_file, private = defaultdict(list), set()
    for row in rows:
        completion = row['completion_path']
        require(completion.startswith(project + '/'), 'TARGET_OUTSIDE_PROJECT')
        path = str(relative(completion[len(project) + 1:]))
        by_file[path].append(row)
        for selector in row['tests']:
            require(isinstance(selector, str), 'TEST_SELECTOR_TYPE')
            test_path = selector.split('::', 1)[0]
            if test_path.startswith(project + '/'):
                test_path = test_path[len(project) + 1:]
            private.add(str(relative(test_path)))
    output = Path(output_root).absolute()
    require(not output.exists(), 'OUTPUT_MUST_BE_FRESH')
    require(not any(p.is_symlink() for p in (output, *output.parents)), 'OUTPUT_LINK_FORBIDDEN')
    prefix = 'Source_Code/' + project + '/'
    files, source_files, seen, removed_files = {}, [], set(), 0
    removed_lines = total_lines = total_bytes = 0
    with tarfile.open(archive_path, 'r:*') as archive:
        for member in archive:
            if not member.name.startswith(prefix):
                continue
            if member.isdir():
                continue
            name = member.name[len(prefix):]
            if not name.endswith('.py') or _private_path(name, private, target_file=name in by_file):
                removed_files += 1
                continue
            require(member.isfile(), 'SOURCE_LINK_OR_SPECIAL_ENTRY')
            path = str(relative(name))
            require(path not in seen, 'DUPLICATE_ARCHIVE_MEMBER')
            seen.add(path)
            require(0 <= member.size <= MAX_FILE_BYTES, 'SOURCE_FILE_BUDGET')
            total_bytes += member.size
            require(total_bytes <= MAX_PROJECT_BYTES, 'SOURCE_PROJECT_BUDGET')
            raw = archive.extractfile(member).read()
            payload, removed, lines = _redact(raw, by_file.get(path, []))
            files[path] = payload.decode('utf-8')
            source_files.append({'path': path, 'source_sha256': hashlib.sha256(raw).hexdigest(),
                                 'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)})
            removed_lines += removed
            total_lines += lines
    require(set(by_file) <= set(files), 'TARGET_FILE_NOT_VISIBLE')
    relations = build_relations(files)
    identity = {'project': project, 'policy': POLICY, 'files': sorted(source_files, key=lambda r: r['path']),
                'target_spans': [{'task_id': r['namespace'], 'path': r['completion_path'][len(project) + 1:],
                                  'body_position': r['body_position'],
                                  'masked_body_position': [r['signature_position'][1] + 1, r['body_position'][1]],
                                  'signature_position': r['signature_position']} for r in sorted(rows, key=lambda r: r['namespace'])]}
    snapshot_id = 'deveval-snapshot:' + digest(identity)
    manifest = {'schema': SCHEMA, 'snapshot_id': snapshot_id, **identity,
        'source_archive_reference': source_archive_reference, 'metadata_reference': metadata_reference,
        'plan_reference': plan_reference, 'selected_task_ids': sorted(selected_ids),
        'context_module_reference': reference(__file__),
        'index_sha256': digest(relations), 'counts': {'visible_python_files': len(files), 'excluded_files': removed_files,
            'masked_target_bodies': len(rows), 'removed_body_lines': removed_lines, 'source_visible_file_lines': total_lines,
            'retained_context_lines': total_lines - removed_lines, 'l2_nodes': len(relations['nodes']), 'l2_edges': len(relations['edges']),
            'resolved_cross_file_edges': sum(e.get('target') is not None and
                next(n['path'] for n in relations['nodes'] if n['id'] == e['target']) != e['path'] for e in relations['edges']),
            'selected_tasks': len(selected_ids)},
        'visibility': 'SAME_SANITIZED_REPOSITORY_READ_AUTHORITY_OFF_ON', 'private_tests_visible': False,
        'gold_bodies_parsed_by_ast': False, 'grader_uses_separate_pristine_repository': True}
    # Recheck original authority before publication; no pristine source was written.
    for value in (source_archive_reference, metadata_reference, plan_reference):
        checked(value)
    output.mkdir(parents=True)
    for path, text in files.items():
        _write(output / 'repository' / path, text.encode('utf-8'))
    _write(output / 'relations.json', canonical(relations))
    _write(output / 'snapshot.json', canonical(manifest))
    return reference(output / 'snapshot.json')


class Snapshot:
    def __init__(self, snapshot_reference):
        self.reference = dict(snapshot_reference)
        self.path = checked(snapshot_reference)
        self.root = self.path.parent
        self.manifest = json.loads(self.path.read_bytes())
        require(self.manifest.get('schema') == SCHEMA and self.manifest.get('policy') == POLICY, 'SNAPSHOT_POLICY')
        self.files = {r['path']: r for r in self.manifest['files']}
        require(len(self.files) == len(self.manifest['files']), 'DUPLICATE_VISIBLE_FILE')
        self.relations = json.loads((self.root / 'relations.json').read_bytes())
        require(digest(self.relations) == self.manifest['index_sha256'], 'INDEX_CHANGED')
        checked(self.manifest['plan_reference'])
        checked(self.manifest['context_module_reference'])
        for path in self.files:
            self._bytes(path)
        identity = {key: self.manifest[key] for key in ('project', 'policy', 'files', 'target_spans')}
        require(self.manifest['snapshot_id'] == 'deveval-snapshot:' + digest(identity), 'SNAPSHOT_ID_CHANGED')

    def _bytes(self, path):
        checked(self.reference)
        path = str(relative(path))
        require(path in self.files, 'FILE_NOT_IN_VISIBLE_AUTHORITY')
        target = self.root / 'repository' / path
        require(not any(p.is_symlink() for p in (target, *target.parents)), 'VISIBLE_LINK_FORBIDDEN')
        raw = target.read_bytes()
        require(len(raw) == self.files[path]['bytes'] and hashlib.sha256(raw).hexdigest() == self.files[path]['sha256'], 'VISIBLE_SOURCE_CHANGED')
        return raw

    def read_file(self, relative_path, *, start_line=1, end_line=None, max_bytes=32768):
        raw = self._bytes(relative_path)
        lines = raw.decode('utf-8').splitlines(keepends=True)
        end_line = len(lines) if end_line is None else end_line
        require(type(start_line) is int and type(end_line) is int and 1 <= start_line <= end_line <= len(lines), 'READ_LINE_RANGE')
        require(type(max_bytes) is int and 1 <= max_bytes <= MAX_FILE_BYTES, 'READ_BYTE_LIMIT')
        text = ''.join(lines[start_line - 1:end_line])
        require(len(text.encode()) <= max_bytes, 'READ_BYTE_BUDGET')
        return {'snapshot_id': self.manifest['snapshot_id'], 'path': relative_path, 'file_sha256': self.files[relative_path]['sha256'],
                'start_line': start_line, 'end_line': end_line, 'text': text}

    def public_task(self, task_id):
        require(task_id in self.manifest['selected_task_ids'], 'TASK_NOT_SELECTED_BY_PLAN')
        metadata = checked(self.manifest['metadata_reference'])
        selected = [r for r in _metadata(metadata) if r['namespace'] == task_id and r['project_path'] == self.manifest['project']]
        require(len(selected) == 1, 'TASK_NOT_IN_SNAPSHOT')
        row = selected[0]
        requirement = row['requirement']
        require(isinstance(requirement, dict) and set(requirement) == {'Arguments', 'Functionality'}
                and all(isinstance(v, str) for v in requirement.values()), 'PUBLIC_REQUIREMENT_ALLOWLIST')
        path = row['completion_path'][len(row['project_path']) + 1:]
        signature = self.read_file(path, start_line=row['signature_position'][0], end_line=row['signature_position'][1])
        return {'schema': 'deveval/public-repository-task/1', 'task_id': task_id, 'namespace': row['namespace'], 'project': row['project_path'],
                'snapshot_id': self.manifest['snapshot_id'], 'completion_path': path, 'type': row['type'],
                'masked_body_start': row['signature_position'][1] + 1, 'masked_body_end': row['body_position'][1], 'body_indent': row['indent'],
                'signature': signature['text'], 'requirement': dict(requirement), 'signature_reference': {k: v for k, v in signature.items() if k != 'text'}}

    def search(self, query, *, limit=20, max_bytes=16384):
        require(isinstance(query, str) and 0 < len(query.encode()) <= 512 and
                type(limit) is int and 1 <= limit <= 100 and type(max_bytes) is int and 1 <= max_bytes <= 32768, 'SEARCH_BUDGET')
        matches, size = [], 0
        for path in sorted(self.files):
            for line, text in enumerate(self._bytes(path).decode('utf-8').splitlines(), 1):
                if query not in text:
                    continue
                row = {'path': path, 'line': line, 'text': text, 'file_sha256': self.files[path]['sha256']}
                encoded = len(canonical(row))
                if len(matches) == limit or size + encoded > max_bytes:
                    return {'snapshot_id': self.manifest['snapshot_id'], 'matches': matches, 'truncated': True}
                matches.append(row)
                size += encoded
        return {'snapshot_id': self.manifest['snapshot_id'], 'matches': matches, 'truncated': False}

    def retrieve(self, query, *, task_id=None, limit=8):
        require(isinstance(query, str) and len(query.encode()) <= 8192 and type(limit) is int and 1 <= limit <= 32, 'RETRIEVAL_BUDGET')
        checked(self.reference)
        require(digest(json.loads((self.root / 'relations.json').read_bytes())) == self.manifest['index_sha256'], 'INDEX_CHANGED')
        nodes = {n['id']: n for n in self.relations['nodes']}
        tokens = set(re.findall(r'[a-z][a-z0-9_]*', query.lower()))
        seeds = {key: float(len(tokens.intersection(re.findall(r'[a-z][a-z0-9_]*', (n['symbol'] + ' ' + n['path']).lower())))) for key, n in nodes.items()}
        if task_id is not None:
            spans = [s for s in self.manifest['target_spans'] if s['task_id'] == task_id]
            require(len(spans) == 1, 'TASK_NOT_IN_SNAPSHOT')
            span = spans[0]
            for key, node in nodes.items():
                if node['path'] == span['path'] and span['signature_position'][0] <= node['line'] <= span['signature_position'][1]:
                    seeds[key] += 3
        total = sum(seeds.values())
        if not total:
            return {'snapshot_id': self.manifest['snapshot_id'], 'matches': [], 'algorithm': 'VISIBLE_STATIC_RELATION_PPR'}
        seeds = {key: value / total for key, value in seeds.items()}
        neighbors = defaultdict(set)
        for edge in self.relations['edges']:
            if edge['target'] in nodes:
                neighbors[edge['source']].add(edge['target'])
                neighbors[edge['target']].add(edge['source'])
        scores = seeds.copy()
        for _ in range(12):
            updated = {key: 0.25 * value for key, value in seeds.items()}
            for key, value in scores.items():
                for target in neighbors[key] or {key}:
                    updated[target] += 0.75 * value / max(1, len(neighbors[key]))
            scores = updated
        matches = []
        for key in sorted(nodes, key=lambda k: (-scores[k], k)):
            if scores[key] <= 0:
                continue
            node = nodes[key]
            self._bytes(node['path'])
            related = [e for e in self.relations['edges'] if e['source'] == key or e['target'] == key]
            visible_relations = []
            for edge in related[:8]:
                self._bytes(edge['path'])
                visible_relations.append({**edge, 'file_sha256': self.files[edge['path']]['sha256']})
            matches.append({**node, 'score': scores[key], 'snapshot_id': self.manifest['snapshot_id'],
                'file_sha256': self.files[node['path']]['sha256'],
                'relations': visible_relations, 'relation_count': len(related),
                'relations_truncated': len(related) > len(visible_relations),
                'full_matching_relations_sha256': digest(related)})
            if len(matches) == limit:
                break
        return {'snapshot_id': self.manifest['snapshot_id'], 'matches': matches, 'algorithm': 'VISIBLE_STATIC_RELATION_PPR',
                'claim': 'STATIC_VISIBLE_SYNTAX_NOT_RUNTIME_CALLGRAPH'}


def load_snapshot(snapshot_reference):
    return Snapshot(snapshot_reference)


def apply_candidate(snapshot_or_reference, task_id, candidate_body, output_copy):
    """Fresh generated-test workspace; hidden official grading stays separate."""
    snapshot = snapshot_or_reference if isinstance(snapshot_or_reference, Snapshot) else load_snapshot(snapshot_or_reference)
    require(isinstance(candidate_body, str) and candidate_body.strip() and len(candidate_body.encode()) <= 65536, 'CANDIDATE_BODY_BUDGET')
    task = snapshot.public_task(task_id)
    output = Path(output_copy).absolute()
    require(not output.exists() and not any(p.is_symlink() for p in (output, *output.parents)), 'CANDIDATE_OUTPUT_MUST_BE_FRESH')
    sources = {path: snapshot._bytes(path) for path in snapshot.files}
    path = task['completion_path']
    original_tree = ast.parse(sources[path])
    lines = sources[path].decode('utf-8').splitlines(keepends=True)
    body = textwrap.indent(textwrap.dedent(candidate_body).strip('\n') + '\n', ' ' * task['body_indent'])
    lines[task['masked_body_start'] - 1:task['masked_body_end']] = [body]
    modified = ''.join(lines).encode('utf-8')
    try:
        modified_tree = ast.parse(modified)
    except (SyntaxError, ValueError):
        raise RepositoryContextError('CANDIDATE_BODY_SYNTAX') from None
    def without_target_body(tree):
        candidates = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and
                      task['signature_reference']['start_line'] <= n.lineno <= task['signature_reference']['end_line']]
        require(len(candidates) == 1, 'CANDIDATE_TARGET_SCOPE')
        candidates[0].body = [ast.Pass()]
        return ast.dump(tree, include_attributes=False)
    require(without_target_body(original_tree) == without_target_body(modified_tree), 'CANDIDATE_ESCAPES_TARGET_BODY')
    sources[path] = modified
    output.mkdir(parents=True)
    for name, raw in sources.items():
        _write(output / name, raw)
    receipt = {'schema': 'deveval/sanitized-candidate-copy/1', 'task_id': task_id,
               'snapshot_reference': snapshot.reference, 'snapshot_id': snapshot.manifest['snapshot_id'],
               'output_path': str(output), 'completion_path': path,
               'candidate_body_sha256': hashlib.sha256(candidate_body.encode()).hexdigest(),
               'candidate_body_start': task['masked_body_start'],
               'candidate_body_end': task['masked_body_start'] + len(body.splitlines()) - 1,
               'source_file_sha256': snapshot.files[path]['sha256'], 'candidate_file_sha256': hashlib.sha256(modified).hexdigest(),
               'private_tests_present': False, 'other_benchmark_bodies_remain_masked': True}
    _write(output / 'candidate-receipt.json', canonical(receipt))
    return receipt
