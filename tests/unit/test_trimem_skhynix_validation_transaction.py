"""Request-local validation DAG reuse retains byte-level mutation detection."""
from collections import Counter
from pathlib import Path
import os

import pytest

import trimem_skhynix_architecture_run as run
from test_trimem_skhynix_architecture_scale_runtime import scaled, authorize
from test_trimem_skhynix_training_grade_hold import terminal_factory


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(run.canonical(value)+b'\n')
    return {'path':str(path),'sha256':run.digest(path.read_bytes())}


@pytest.fixture
def graph(tmp_path,monkeypatch):
    dataset=write(tmp_path/'dataset.json',{})
    image=write(tmp_path/'images.json',{})
    loader=write(tmp_path/'loader.json',{})
    source=tmp_path/'source/module.py'
    source.parent.mkdir()
    source.write_bytes(b'original frozen module\n')
    paths={name:tmp_path/(name+'.json') for name in ('root','left','right','leaf')}
    edges={'root':['left','right','leaf'],'left':['leaf'],'right':['leaf'],'leaf':[]}
    configs={}
    for name,path in paths.items():
        config={'schema':run.SCHEMA,'dataset_manifest':dataset,'image_index':image,
            'loader_preflight_path':loader['path'],'loader_preflight_sha256':loader['sha256'],
            'source_root':str(source.parent),'source_sha256':{'module.py':run.digest(source.read_bytes())},
            'scale_authority_reference':{'synthetic_graph':name},'name':name}
        write(path,config)
        path.with_suffix('.sha256').write_text(run.digest(run.canonical(config)))
        configs[name]=config
    visited=[]
    def enrollment(config,dataset=None):
        visited.append(config['name'])
        for child in edges[config['name']]:
            run.load_experiment(paths[child])
        return None
    monkeypatch.setattr(run,'execution_enrollment',enrollment)
    return paths,configs,edges,source,visited


def test_diamond_dependencies_are_fully_validated_once_then_byte_rechecked(graph,monkeypatch):
    paths,configs,edges,source,visited=graph
    reads=Counter()
    original=Path.read_bytes
    def counted(path):
        reads[path]+=1
        return original(path)
    monkeypatch.setattr(Path,'read_bytes',counted)
    assert run.load_experiment(paths['root'])==configs['root']
    assert Counter(visited)==Counter({'root':1,'left':1,'right':1,'leaf':1})
    assert reads[source]==2  # first immutable snapshot plus final byte recheck
    assert reads[paths['leaf']]==2
    assert run._VALIDATION_TRANSACTION.get() is None
    run.load_experiment(paths['root'])
    assert Counter(visited)==Counter({'root':2,'left':2,'right':2,'leaf':2})
    assert reads[source]==4


@pytest.mark.parametrize('which',['source','config','checksum'])
def test_completed_child_dependency_changed_after_cache_hit_is_rejected_at_outer_return(graph,monkeypatch,which):
    paths,configs,edges,source,visited=graph
    original=run.execution_enrollment
    def changed(config,dataset=None):
        result=original(config,dataset)
        if config['name']=='right':
            path=source if which=='source' else paths['leaf'] if which=='config' else paths['leaf'].with_suffix('.sha256')
            raw=path.read_bytes(); stat=path.stat()
            path.write_bytes(b'X'+raw[1:])
            os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        return result
    monkeypatch.setattr(run,'execution_enrollment',changed)
    with pytest.raises(ValueError,match='changed'):
        run.load_experiment(paths['root'])
    assert run._VALIDATION_TRANSACTION.get() is None


def test_next_call_revalidates_source_bytes_and_recovers_after_prior_failure(graph):
    paths,configs,edges,source,visited=graph
    run.load_experiment(paths['root'])
    original=source.read_bytes()
    source.write_bytes(b'changed frozen module\n')
    with pytest.raises(ValueError):
        run.load_experiment(paths['root'])
    assert run._VALIDATION_TRANSACTION.get() is None
    source.write_bytes(original)
    assert run.load_experiment(paths['root'])==configs['root']


def test_final_recheck_uses_bytes_even_when_metadata_is_unchanged(graph,monkeypatch):
    paths,configs,edges,source,visited=graph
    identity=run._file_identity
    frozen={}
    monkeypatch.setattr(run,'_file_identity',lambda path:frozen.setdefault(path,identity(path)))
    original=run.execution_enrollment
    def changed(config,dataset=None):
        result=original(config,dataset)
        if config['name']=='root':
            raw=source.read_bytes()
            source.write_bytes(b'X'+raw[1:])
        return result
    monkeypatch.setattr(run,'execution_enrollment',changed)
    with pytest.raises(ValueError,match='changed'):
        run.load_experiment(paths['root'])
    assert run._VALIDATION_TRANSACTION.get() is None


def test_cycles_fail_before_recursion_limit_and_context_is_not_reused(graph):
    paths,configs,edges,source,visited=graph
    edges['leaf']=['root']
    with pytest.raises(ValueError,match='Cyclic'):
        run.load_experiment(paths['root'])
    assert len(visited)==3 and run._VALIDATION_TRANSACTION.get() is None
    edges['leaf']=[]
    assert run.load_experiment(paths['root'])==configs['root']


def test_returned_config_cannot_mutate_another_cached_view(graph):
    paths,configs,edges,source,visited=graph
    @run._validation_scope(lambda:'two-views')
    def views():
        first=run.load_experiment(paths['leaf'])
        first['source_sha256']['module.py']='0'*64
        return run.load_experiment(paths['leaf'])
    assert views()==configs['leaf']
    assert visited==['leaf']


def test_same_path_conflicting_reference_is_rejected_in_one_request(tmp_path):
    ref=write(tmp_path/'value.json',{'valid':True})
    @run._validation_scope(lambda:'conflicting')
    def conflicting():
        run.checked_reference(ref)
        return run.checked_reference({**ref,'sha256':'0'*64})
    with pytest.raises(ValueError,match='conflicting'):
        conflicting()
    assert run._VALIDATION_TRANSACTION.get() is None


def test_actual_scope_dedup_checks_dataset_argument_and_keeps_returned_views_separate(scaled,monkeypatch):
    case=scaled(120); authorize(case,'TRAINING_INCREMENT')
    calls=[]; original=run._scale_targets
    monkeypatch.setattr(run,'_scale_targets',lambda dataset:(calls.append(dataset),original(dataset))[1])
    @run._validation_scope(lambda:'scope-batch')
    def batch():
        one=run.execution_enrollment(case.ops.config)
        one['task_ids'].clear()
        return run.execution_enrollment(case.ops.config,case.dataset)
    assert len(batch()['task_ids'])==96 and len(calls)==1
    with pytest.raises(ValueError,match='scope differs'):
        run.execution_enrollment(case.ops.config,{**case.dataset,'training_count':24})


@pytest.mark.parametrize('change',['completion','native_events','sidecar','new_pending','new_failure','new_manager_error'])
def test_cached_native_source_dependencies_and_absence_guards_are_rechecked(terminal_factory,change):
    ctx=terminal_factory(budget=True)
    @run._validation_scope(lambda:'native-source')
    def source():
        run._validate_training_submission(ctx.cell_path,ctx.config)
        if change in {'completion','native_events','sidecar'}:
            path={'completion':ctx.output/'completion.json','native_events':ctx.output/'events.jsonl',
                'sidecar':ctx.cell_path.with_suffix('.sha256')}[change]
            raw=path.read_bytes(); stat=path.stat()
            path.write_bytes(raw[:-1]+(b' ' if raw[-1:]!=b' ' else b'\n'))
            os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        else:
            path={'new_pending':ctx.folder/'broker/pending.json','new_failure':ctx.folder/'native-execution-failure.json',
                'new_manager_error':ctx.output/'manager-error-new.json'}[change]
            write(path,{'unexpected':True})
    with pytest.raises(ValueError,match='changed'):
        source()
    assert run._VALIDATION_TRANSACTION.get() is None


def test_new_authority_is_not_written_when_final_dependency_recheck_fails(scaled,monkeypatch):
    case=scaled(120)
    output=case.root/'must-not-exist.json'
    original=run._scale_targets
    def changed(dataset):
        result=original(dataset)
        Path(case.dataset_ref['path']).write_bytes(b'changed during validation')
        return result
    monkeypatch.setattr(run,'_scale_targets',changed)
    with pytest.raises(ValueError,match='changed'):
        run.create_execution_enrollment(output,dataset_reference=case.dataset_ref,purpose='TRAINING_INCREMENT')
    assert not output.exists()


@pytest.mark.parametrize('changed',['protocol','original_manifest_reference','training_inventory','evaluation_inventory','implementation'])
def test_transitive_public_protocol_dependencies_survive_scope_cache_hits(scaled,monkeypatch,changed):
    import sys
    case=scaled(120)
    implementation=write(case.root/'selection.py',{'public_selection':True})
    monkeypatch.setattr(sys.modules['trimem_skhynix_architecture_scale_dataset'],'__file__',implementation['path'],raising=False)
    protocol={name:write(case.root/(name+'.json'),{'public_inventory':name}) for name in
        ('original_manifest_reference','training_inventory','evaluation_inventory')}
    protocol['selection_implementation_sha256']=implementation['sha256']
    protocol_ref=write(case.root/'protocol.json',protocol)
    case.dataset['protocol_reference']=protocol_ref
    case.dataset_ref=write(case.root/'dataset.json',case.dataset)
    case.ops.config['dataset_manifest']=case.dataset_ref
    authorize(case,'TRAINING_INCREMENT')
    @run._validation_scope(lambda:'public-protocol-batch')
    def batch():
        run.execution_enrollment(case.ops.config)
        reference=protocol_ref if changed=='protocol' else implementation if changed=='implementation' else protocol[changed]
        path=Path(reference['path'])
        path.write_bytes(path.read_bytes()+b' ')
        return run.execution_enrollment(case.ops.config)
    with pytest.raises(ValueError,match='changed'):
        batch()
