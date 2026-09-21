"""Deterministic public-only 24 -> 120 -> 240 sources, DEV60 and locked FINAL500.

Selection reads only the existing public Parquet column allowlist. Public issue
families are heuristic sampling strata, not verified procedures or gate evidence.
The near-duplicate filter is lexical and cannot certify semantic independence.
This module never invokes a model, grader, container, or private-row decoder.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from pathlib import Path
import re
import unicodedata

import trimem_skhynix_architecture_dataset as dataset
import trimem_skhynix_architecture_plan as plan

SCHEMA = "skhynix/pdf-architecture-scale-dataset/1.0"
PROTOCOL_SCHEMA = "skhynix/pdf-architecture-scale-selection/1.0"
DEFAULT_SEED = "skhynix-scale-001-public-v1"
# Repository: cumulative TRAIN120, cumulative TRAIN240, separately reserved DEV.
ALLOCATIONS = {
    "astropy/astropy": (8, 14, 5), "django/django": (20, 56, 8),
    "matplotlib/matplotlib": (10, 20, 5), "mwaskom/seaborn": (7, 10, 4),
    "pallets/flask": (6, 6, 4), "psf/requests": (8, 12, 4),
    "pydata/xarray": (9, 16, 5), "pylint-dev/pylint": (8, 13, 4),
    "pytest-dev/pytest": (9, 16, 5), "scikit-learn/scikit-learn": (11, 24, 5),
    "sphinx-doc/sphinx": (10, 20, 5), "sympy/sympy": (14, 33, 6),
}
FAMILY_TERMS = {
    "query_and_database": ("queryset", "sql", "database", "migration", "lookup", "join", "orm"),
    "rendering_and_layout": ("plot", "legend", "ticks", "figure", "colorbar", "axes", "render", "layout"),
    "indexing_and_shapes": ("indexing", "shape", "broadcast", "dimension", "slice", "array", "align"),
    "serialization_and_io": ("serialize", "deserialize", "json", "pickle", "csv", "encoding", "io", "read", "write"),
    "http_and_routing": ("http", "https", "cookie", "redirect", "request", "response", "route", "header"),
    "symbolic_and_numeric": ("integral", "derivative", "polynomial", "eigenvalue", "precision", "nan", "infinity", "simplify"),
    "test_collection_and_plugins": ("fixture", "pytest", "plugin", "collection", "marker", "parametrize"),
    "documentation_and_references": ("sphinx", "docstring", "autodoc", "rst", "documentation", "reference"),
    "static_analysis_and_types": ("pylint", "lint", "inference", "ast", "annotation", "typehint"),
    "parsing_and_text": ("parser", "parse", "regex", "unicode", "token", "string", "escape"),
    "validation_and_errors": ("validation", "invalid", "valueerror", "typeerror", "exception", "raises"),
    "api_and_compatibility": ("deprecated", "compatibility", "kwargs", "signature", "argument", "attribute"),
}
POLICY = {
    "public_fields": [*dataset.PUBLIC_COLUMNS, *dataset.PUBLIC_ENVIRONMENT_COLUMNS],
    "selection": "RESERVE_DEV_FIRST_THEN_NESTED_REPOSITORY_FAMILY_ROUNDS",
    "dev_family_chunk": 1, "training_family_chunk": 3,
    "ranking": "SHA256_SEED_PURPOSE_REPOSITORY_FAMILY_INSTANCE_ID",
    "family_terms": {name: list(terms) for name, terms in FAMILY_TERMS.items()},
    "family_tie_break": "ALPHABETICAL", "family_default": "other_public_issue",
    "duplicate_normalization": "NFKC_CASEFOLD_WHITESPACE",
    "near_duplicate_repository_scope": True, "near_duplicate_word_shingle_size": 5,
    "near_duplicate_min_shingles": 40, "near_duplicate_jaccard_percent": 85,
    "near_duplicate_min_length_ratio_percent": 80, "duplicate_closure": "TRANSITIVE_CONNECTED_COMPONENTS",
    "one_new_source_per_duplicate_group": True,
    "final_overlap_groups_excluded": True, "mandatory_source_groups_excluded_from_dev": True,
    "official_outcomes_used": False, "runtime_availability_used_for_selection": False,
    "limitations": ["Lexical groups can miss paraphrases and can overgroup shared issue templates.",
        "Inferred public families do not assert a shared fix, successful verification, or Gate B eligibility.",
        "Existing mandatory sources are preserved even if they share a duplicate group with one another.",
        "A mandatory source grouped with FINAL500 blocks selection; it is never silently dropped.",
        "Runtime images and execution readiness are not established by this public-data freeze."],
}


class ScaleDatasetError(ValueError):
    pass


def _fail(message):
    raise ScaleDatasetError(message)


def _reference(path):
    path = plan._path(path)
    return {"path": str(path), "sha256": plan.file_sha(path)}


def _read(reference):
    return plan._read_reference(reference)[1]


def _retain(path, value):
    path = plan._path(path, exists=False)
    raw = plan.canonical(value) + b"\n"
    if path.exists():
        if path.read_bytes() != raw:
            _fail("Refusing to overwrite an existing scale artifact")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
    return _reference(path)


def _rank(seed, *values):
    return plan.sha(plan.canonical([seed, *values]))


def infer_public_family(statement):
    words = Counter(re.findall(r"[a-z][a-z0-9]*", unicodedata.normalize("NFKC", statement).casefold()))
    scores = {name: sum(min(words[term], 3) for term in terms) for name, terms in FAMILY_TERMS.items()}
    best = min(scores, key=lambda name: (-scores[name], name))
    return {"family": best if scores[best] else "other_public_issue",
        "matched_terms": sorted(term for term in FAMILY_TERMS[best] if words[term]) if scores[best] else []}


def duplicate_groups(rows):
    """Deterministic lexical components, using public instructions and repository only."""
    ids = sorted(rows)
    parent = {identity: identity for identity in ids}

    def root(identity):
        while parent[identity] != identity:
            parent[identity] = parent[parent[identity]]
            identity = parent[identity]
        return identity

    def join(a, b):
        a, b = sorted((root(a), root(b)))
        parent[b] = a

    normalized, shingles, by_repo, edges = {}, {}, defaultdict(list), []
    for identity in ids:
        row = rows[identity]
        text = " ".join(unicodedata.normalize("NFKC", row["problem_statement"]).casefold().split())
        fingerprint = plan.sha(text.encode())
        if fingerprint in normalized:
            prior = normalized[fingerprint]
            join(prior, identity)
            edges.append({"a": prior, "b": identity, "reason": "NORMALIZED_EXACT"})
        else:
            normalized[fingerprint] = identity
        words = re.findall(r"\w+|[^\w\s]", text)
        values = frozenset(" ".join(words[index:index + 5]) for index in range(max(0, len(words) - 4)))
        if len(values) >= POLICY["near_duplicate_min_shingles"]:
            shingles[identity] = values
            by_repo[row["repo"]].append(identity)
    for repository in sorted(by_repo):
        candidates = by_repo[repository]
        for index, a in enumerate(candidates):
            left = shingles[a]
            for b in candidates[index + 1:]:
                right = shingles[b]
                if min(len(left), len(right)) * 100 < max(len(left), len(right)) * 80:
                    continue
                overlap = len(left.intersection(right))
                union = len(left) + len(right) - overlap
                if overlap * 100 >= union * 85:
                    join(a, b)
                    edges.append({"a": a, "b": b, "reason": "PUBLIC_SHINGLE_JACCARD_GE_85_PERCENT"})
    members = defaultdict(list)
    for identity in ids:
        members[root(identity)].append(identity)
    group_by_id = {}
    groups = []
    for identities in sorted(members.values()):
        group_id = plan.sha(plan.canonical(identities))
        group_by_id.update({identity: group_id for identity in identities})
        if len(identities) > 1:
            groups.append({"group_id": group_id, "instance_ids": identities})
    return group_by_id, groups, edges


def _draw(repository, count, candidates, signals, blocked, selected, seed, purpose, chunk):
    """Repeated examples within a family, with rounds across available families."""
    pools = defaultdict(list)
    for identity in candidates:
        signal = signals[identity]
        if signal["duplicate_group"] not in blocked:
            pools[signal["family"]].append(identity)
    queues = {family: deque(sorted(values, key=lambda identity: (_rank(seed, purpose, repository, family, identity), identity)))
              for family, values in pools.items()}
    counts = Counter(signals[identity]["family"] for identity in selected)
    added = []
    while len(added) < count:
        for queue in queues.values():
            while queue and signals[queue[0]]["duplicate_group"] in blocked:
                queue.popleft()
        available = [family for family, queue in queues.items() if queue]
        if not available:
            _fail(f"Insufficient independent public candidates for {repository}: {purpose} requires {count}, found {len(added)}")
        family = min(available, key=lambda name: (counts[name], _rank(seed, purpose, repository, name), name))
        for _ in range(min(chunk, count - len(added))):
            queue = queues[family]
            while queue and signals[queue[0]]["duplicate_group"] in blocked:
                queue.popleft()
            if not queue:
                break
            identity = queue.popleft()
            added.append(identity)
            blocked.add(signals[identity]["duplicate_group"])
            counts[family] += 1
    return added


def select_public_tasks(original_targets, candidate_rows, final_rows, *, seed=DEFAULT_SEED):
    if not isinstance(seed, str) or not seed or len(seed.encode()) > 256:
        _fail("Selection seed must be an explicit bounded string")
    allowed = set(POLICY["public_fields"])
    for identity, row in [*candidate_rows.items(), *final_rows.items()]:
        if set(row) - allowed or identity != row.get("instance_id"):
            _fail("Selection received missing or non-public row fields")
        dataset._descriptor(row)
    original = [row["instance_id"] for row in original_targets if row["role"] == "TRAINING"]
    final = [row["instance_id"] for row in original_targets if row["role"] == "EVALUATION"]
    if (len(original) != 24 or len(set(original)) != 24 or len(final) != 500 or set(final) != set(final_rows)
            or not set(original) <= set(candidate_rows) or set(candidate_rows).intersection(final_rows)):
        _fail("Original 24-source / 500-final identity binding differs")
    if Counter(candidate_rows[identity]["repo"] for identity in original) != Counter({repo: 2 for repo in ALLOCATIONS}):
        _fail("Mandatory prefix must retain the original two sources for all twelve repositories")
    if set(row["repo"] for row in candidate_rows.values()) != set(ALLOCATIONS):
        _fail("Candidate repository population differs")
    train_hashes = {dataset._descriptor(row)["instruction_sha256"] for row in candidate_rows.values()}
    final_hashes = {dataset._descriptor(row)["instruction_sha256"] for row in final_rows.values()}
    if train_hashes.intersection(final_hashes):
        _fail("Candidate instructions overlap the final test instructions")
    group_by_id, groups, edges = duplicate_groups({**candidate_rows, **final_rows})
    final_groups = {group_by_id[identity] for identity in final}
    mandatory_groups = {group_by_id[identity] for identity in original}
    if mandatory_groups.intersection(final_groups):
        _fail("A mandatory original source is lexically grouped with FINAL500; review required without dropping either")
    signals = {identity: {**infer_public_family(row["problem_statement"]), "duplicate_group": group_by_id[identity]}
               for identity, row in sorted(candidate_rows.items())}
    by_repo = {repo: [identity for identity, row in candidate_rows.items() if row["repo"] == repo]
               for repo in ALLOCATIONS}
    dev, dev_blocked = [], final_groups | mandatory_groups
    for repo in sorted(ALLOCATIONS):
        dev.extend(_draw(repo, ALLOCATIONS[repo][2], by_repo[repo], signals, dev_blocked, [], seed, "DEVELOPMENT", 1))
    training, stages = list(original), {"24": list(original)}
    blocked = final_groups | {signals[identity]["duplicate_group"] for identity in dev} | mandatory_groups
    for size, index in ((120, 0), (240, 1)):
        for repo in sorted(ALLOCATIONS):
            prior = [identity for identity in training if candidate_rows[identity]["repo"] == repo]
            additional = ALLOCATIONS[repo][index] - len(prior)
            training.extend(_draw(repo, additional, by_repo[repo], signals, blocked, prior, seed, "TRAINING", 3))
        if len(training) != size:
            _fail("Frozen repository quotas did not produce the requested training size")
        stages[str(size)] = list(training)
    owner_counts, owners = Counter(), {}
    for identity in training:
        repo = candidate_rows[identity]["repo"]
        owners[identity] = 1 + owner_counts[repo] % 2
        owner_counts[repo] += 1
    return {"seed": seed, "original_training_instance_ids": original, "training_instance_ids_by_size": stages,
        "development_instance_ids": dev, "final_evaluation_instance_ids": final,
        "training_owner_by_instance": owners, "candidate_signals": signals,
        "duplicate_groups": groups, "duplicate_edges": edges,
        "excluded_candidate_final_overlap_ids": sorted(identity for identity in candidate_rows if group_by_id[identity] in final_groups),
        "candidate_counts_by_repository": dict(sorted(Counter(row["repo"] for row in candidate_rows.values()).items()))}


def _target(row, source, role, order, scope=None):
    descriptor = dataset._descriptor(row)
    prefix = "swebench_verified--" if scope == "FINAL" else "swebench--"
    value = {"target_id": prefix + descriptor["instance_id"], "instance_id": descriptor["instance_id"],
        "benchmark_id": "swebench_verified", "role": role, "language": "python",
        "repository": descriptor["repository"], "base_commit": descriptor["base_commit"],
        "public_issue_created_at": descriptor["created_at"], "instruction_sha256": descriptor["instruction_sha256"],
        "public_source_row_sha256": plan.sha(plan.canonical(row)), "source_dataset_id": source["dataset_id"],
        "dataset_revision": source["revision"], "source_split": source["split"], "order_index": order}
    if scope:
        value["evaluation_scope"] = scope
    return value


def _selection_inputs(original_reference):
    original = _read(original_reference)
    targets, old_rows, loaded = dataset.load_architecture_rows(original_reference["path"], expected_sha256=original_reference["sha256"])
    if loaded != original or original["training_count"] != 24 or original["evaluation_count"] != 500:
        _fail("Scale selection requires the exact original pilot manifest")
    _, evaluation, _, training = dataset._inventories(original["evaluation_inventory"], original["training_inventory"])
    candidates = {row["instance_id"]: row for row in training["tasks"]}
    candidate_rows = dataset._public_rows(training, candidates, evaluation=False)
    final_rows = {row["instance_id"]: old_rows[row["instance_id"]] for row in targets if row["role"] == "EVALUATION"}
    return original, targets, training, evaluation, candidate_rows, final_rows


def _assemble_protocol(original_manifest_reference, seed):
    original, targets, training, evaluation, candidates, final = _selection_inputs(original_manifest_reference)
    selection = select_public_tasks(targets, candidates, final, seed=seed)
    chosen = [*selection["training_instance_ids_by_size"]["240"], *selection["development_instance_ids"], *selection["final_evaluation_instance_ids"]]
    rows = {identity: (candidates if identity in candidates else final)[identity] for identity in chosen}
    public_targets = []
    for identities, role, scope, source in (
        (selection["training_instance_ids_by_size"]["240"], "TRAINING", None, training["dataset"]),
        (selection["development_instance_ids"], "EVALUATION", "DEVELOPMENT", training["dataset"]),
        (selection["final_evaluation_instance_ids"], "EVALUATION", "FINAL", evaluation["dataset"])):
        for identity in identities:
            public_targets.append(_target(rows[identity], source, role, len(public_targets), scope))
    value = {"schema": PROTOCOL_SCHEMA, "status": "FROZEN_PUBLIC_SCALE_SELECTION_NOT_EXECUTION_READY",
        "original_manifest_reference": plan._reference(original_manifest_reference),
        "selection_implementation_sha256": plan.file_sha(__file__), "policy": POLICY,
        "repository_allocations": {repo: {"training120": sizes[0], "training240": sizes[1], "development": sizes[2]}
                                   for repo, sizes in sorted(ALLOCATIONS.items())},
        "evaluation_inventory": original["evaluation_inventory"], "training_inventory": original["training_inventory"],
        "datasets": {"TRAINING": training["dataset"], "DEVELOPMENT": training["dataset"], "FINAL": evaluation["dataset"]},
        **selection, "targets": public_targets,
        "public_task_descriptors": [{"task_id": target["target_id"], "repository": target["repository"],
            "commit": target["base_commit"], "instruction": rows[target["instance_id"]]["problem_statement"].strip()}
            for target in public_targets],
        "model_calls": 0, "official_grader_runs": 0, "training_runs": 0,
        "runtime_compatibility_verified": False, "final_outcomes_used_for_selection": False}
    _validate_protocol(value)
    return value


def build_scale_protocol(original_manifest_reference, *, output, seed=DEFAULT_SEED):
    return _retain(output, _assemble_protocol(original_manifest_reference, seed))


def verify_scale_protocol(protocol_reference):
    """Full public-source reproduction of the frozen selection, without writing or execution."""
    value = _read(protocol_reference)
    expected = _assemble_protocol(value["original_manifest_reference"], value["seed"])
    if value != expected:
        _fail("Scale selection does not reproduce from its public source bytes and frozen policy")
    return value


def _validate_protocol(value):
    plan._fields(value, "schema status original_manifest_reference selection_implementation_sha256 policy "
        "repository_allocations evaluation_inventory training_inventory datasets seed original_training_instance_ids "
        "training_instance_ids_by_size development_instance_ids final_evaluation_instance_ids training_owner_by_instance "
        "candidate_signals duplicate_groups duplicate_edges excluded_candidate_final_overlap_ids candidate_counts_by_repository "
        "targets public_task_descriptors model_calls official_grader_runs training_runs runtime_compatibility_verified "
        "final_outcomes_used_for_selection", "Scale public protocol")
    if (value.get("schema") != PROTOCOL_SCHEMA or value.get("policy") != POLICY
            or value.get("selection_implementation_sha256") != plan.file_sha(__file__)
            or value.get("repository_allocations") != {repo: {"training120": a, "training240": b, "development": c}
                                                       for repo, (a, b, c) in sorted(ALLOCATIONS.items())}):
        _fail("Scale protocol policy or implementation differs")
    if (value["status"] != "FROZEN_PUBLIC_SCALE_SELECTION_NOT_EXECUTION_READY"
            or any(type(value[key]) is not int or value[key] != 0 for key in ("model_calls", "official_grader_runs", "training_runs"))
            or value["runtime_compatibility_verified"] is not False or value["final_outcomes_used_for_selection"] is not False
            or not isinstance(value["seed"], str) or not 0 < len(value["seed"].encode()) <= 256):
        _fail("Scale selection cannot claim execution readiness or use outcomes")
    original = _read(value["original_manifest_reference"])
    if (value["evaluation_inventory"] != original["evaluation_inventory"] or value["training_inventory"] != original["training_inventory"]
            or value["datasets"] != {"TRAINING": original["datasets"]["TRAINING"], "DEVELOPMENT": original["datasets"]["TRAINING"],
                                     "FINAL": original["datasets"]["EVALUATION"]}):
        _fail("Scale source identities differ from the original byte-pinned sources")
    training_inventory, final_inventory = _read(value["training_inventory"]), _read(value["evaluation_inventory"])
    descriptors = {row["instance_id"]: row for row in [*training_inventory["tasks"], *final_inventory["tasks"]]}
    stages, dev, final = value["training_instance_ids_by_size"], value["development_instance_ids"], value["final_evaluation_instance_ids"]
    mandatory = [row["instance_id"] for row in original["targets"] if row["role"] == "TRAINING"]
    original_final = [row for row in original["targets"] if row["role"] == "EVALUATION"]
    if (set(stages) != {"24", "120", "240"} or stages["24"] != mandatory or value["original_training_instance_ids"] != mandatory
            or stages["120"][:24] != mandatory or stages["240"][:120] != stages["120"]
            or any(len(stages[size]) != int(size) or len(set(stages[size])) != int(size) for size in stages)
            or len(dev) != 60 or len(set(dev)) != 60 or final != [row["instance_id"] for row in original_final]):
        _fail("Scale nested prefixes or DEV60 / locked FINAL500 population differs")
    sets = [set(stages["240"]), set(dev), set(final)]
    candidate_ids = {row["instance_id"] for row in training_inventory["tasks"]}
    if not sets[0] | sets[1] <= candidate_ids:
        _fail("A selected source is outside the disjoint candidate inventory")
    hashes = [{descriptors[identity]["instruction_sha256"] for identity in identities} for identities in sets]
    if any(sets[a] & sets[b] or hashes[a] & hashes[b] for a in range(3) for b in range(a + 1, 3)):
        _fail("Scale training, development and final populations overlap")
    expected_order = [*stages["240"], *dev, *final]
    if [target["instance_id"] for target in value["targets"]] != expected_order or len(value["public_task_descriptors"]) != 800:
        _fail("Scale public target ordering differs")
    for index, (target, public) in enumerate(zip(value["targets"], value["public_task_descriptors"])):
        identity = target["instance_id"]
        descriptor = descriptors[identity]
        scope = None if identity in sets[0] else "DEVELOPMENT" if identity in sets[1] else "FINAL"
        source = value["datasets"][scope or "TRAINING"]
        fields = ("target_id instance_id benchmark_id role language repository base_commit public_issue_created_at "
                  "instruction_sha256 public_source_row_sha256 source_dataset_id dataset_revision source_split order_index")
        plan._fields(target, fields + (" evaluation_scope" if scope else ""), "Scale public target")
        plan._digest(target["public_source_row_sha256"], "public source row")
        expected_prefix = "swebench_verified--" if scope == "FINAL" else "swebench--"
        if (target["order_index"] != index or target["role"] != ("TRAINING" if scope is None else "EVALUATION")
                or target["target_id"] != expected_prefix + identity or target["benchmark_id"] != "swebench_verified" or target["language"] != "python"
                or target.get("evaluation_scope") != scope
                or any(target[field] != descriptor[original_field] for field, original_field in (
                    ("repository", "repository"), ("base_commit", "base_commit"),
                    ("public_issue_created_at", "created_at"), ("instruction_sha256", "instruction_sha256")))
                or (target["source_dataset_id"], target["dataset_revision"], target["source_split"])
                != (source["dataset_id"], source["revision"], source["split"])
                or public != {"task_id": target["target_id"], "repository": target["repository"], "commit": target["base_commit"], "instruction": public.get("instruction")}
                or plan.sha(public["instruction"].encode()) != descriptor["instruction_sha256"]):
            _fail("Scale target or public task descriptor differs from its source inventory")
    for size, column in ((120, 0), (240, 1)):
        if Counter(descriptors[identity]["repository"] for identity in stages[str(size)]) != Counter({repo: values[column] for repo, values in ALLOCATIONS.items()}):
            _fail("Scale training repository quotas differ")
    if Counter(descriptors[identity]["repository"] for identity in dev) != Counter({repo: values[2] for repo, values in ALLOCATIONS.items()}):
        _fail("Scale development repository quotas differ")
    counts, owners = Counter(), {}
    for identity in stages["240"]:
        repo = descriptors[identity]["repository"]
        owners[identity] = 1 + counts[repo] % 2
        counts[repo] += 1
    if value["training_owner_by_instance"] != owners:
        _fail("Scale stable contributor assignment differs")
    if (set(value["candidate_signals"]) != candidate_ids
            or value["candidate_counts_by_repository"] != dict(sorted(Counter(row["repository"] for row in training_inventory["tasks"]).items()))):
        _fail("Scale candidate signal inventory differs")
    group_by_id, grouped = {}, set()
    for group in value["duplicate_groups"]:
        plan._fields(group, "group_id instance_ids", "Public duplicate group")
        members = group["instance_ids"]
        if (len(members) < 2 or members != sorted(set(members)) or not set(members) <= set(descriptors)
                or set(members) & grouped or group["group_id"] != plan.sha(plan.canonical(members))):
            _fail("Public duplicate component is inconsistent")
        grouped.update(members)
        group_by_id.update({identity: group["group_id"] for identity in members})
    for identity in descriptors:
        group_by_id.setdefault(identity, plan.sha(plan.canonical([identity])))
    for identity, signal in value["candidate_signals"].items():
        plan._fields(signal, "family matched_terms duplicate_group", "Public sampling signal")
        if (signal["family"] not in {*FAMILY_TERMS, "other_public_issue"} or signal["duplicate_group"] != group_by_id[identity]
                or signal["matched_terms"] != sorted(set(signal["matched_terms"]))
                or not set(signal["matched_terms"]) <= set(FAMILY_TERMS.get(signal["family"], ()))):
            _fail("Public sampling signal differs from its declared lexical policy")
    for target, public in zip(value["targets"], value["public_task_descriptors"]):
        identity = target["instance_id"]
        if identity in candidate_ids and {key: value["candidate_signals"][identity][key] for key in ("family", "matched_terms")} != infer_public_family(public["instruction"]):
            _fail("Selected public family signal differs from its actual public instruction")
    group_sets = [{group_by_id[identity] for identity in identities} for identities in sets]
    if any(group_sets[a] & group_sets[b] for a in range(3) for b in range(a + 1, 3)):
        _fail("A lexical duplicate component crosses source/development/final boundaries")
    repeated_training = defaultdict(list)
    for identity in stages["240"]:
        repeated_training[group_by_id[identity]].append(identity)
    if any(len(ids) > 1 and not set(ids) <= set(mandatory) for ids in repeated_training.values()):
        _fail("A new training source duplicates another selected source")
    expected_excluded = sorted(identity for identity in candidate_ids if group_by_id[identity] in group_sets[2])
    if value["excluded_candidate_final_overlap_ids"] != expected_excluded:
        _fail("Candidate final-overlap exclusions differ")
    for edge in value["duplicate_edges"]:
        plan._fields(edge, "a b reason", "Public duplicate edge")
        if (edge["a"] not in descriptors or edge["b"] not in descriptors or edge["a"] == edge["b"]
                or group_by_id[edge["a"]] != group_by_id[edge["b"]]
                or edge["reason"] not in {"NORMALIZED_EXACT", "PUBLIC_SHINGLE_JACCARD_GE_85_PERCENT"}):
            _fail("Public duplicate edge is inconsistent")
    target_by_id = {target["instance_id"]: target for target in value["targets"]}
    for original_target in [*original["targets"][:24], *original_final]:
        target = target_by_id[original_target["instance_id"]]
        if any(target[key] != child for key, child in original_target.items() if key != "order_index"):
            _fail("An original pilot or final target descriptor changed")
    return value


def _view(protocol, protocol_reference, size):
    if type(size) is not int or size not in (24, 120, 240):
        _fail("Scale training size must be 24, 120 or 240")
    ids = protocol["training_instance_ids_by_size"][str(size)]
    evaluation = [*protocol["development_instance_ids"], *protocol["final_evaluation_instance_ids"]]
    by_id = {target["instance_id"]: target for target in protocol["targets"]}
    targets = [{**by_id[identity], "order_index": index} for index, identity in enumerate([*ids, *evaluation])]
    return {"schema": SCHEMA, "status": "FROZEN_PUBLIC_SCALE_DATASET", "protocol_reference": protocol_reference,
        "training_count": size, "evaluation_count": 560, "development_count": 60, "final_evaluation_count": 500,
        "training_instance_ids": ids, "development_instance_ids": protocol["development_instance_ids"],
        "final_evaluation_instance_ids": protocol["final_evaluation_instance_ids"],
        "datasets": protocol["datasets"], "targets": targets,
        "training_owner_by_instance": {identity: protocol["training_owner_by_instance"][identity] for identity in ids},
        "public_columns": list(dataset.PUBLIC_COLUMNS), "optional_public_environment_columns": list(dataset.PUBLIC_ENVIRONMENT_COLUMNS),
        "model_calls": 0, "official_grader_runs": 0, "training_runs": 0}


def build_scale_manifest(protocol_reference, *, training_size, output):
    protocol = _validate_protocol(_read(protocol_reference))
    return _retain(output, _view(protocol, plan._reference(protocol_reference), training_size))


def validate_scale_manifest(manifest):
    """Cheap public JSON authority checks, with no Parquet decoding or private access."""
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        _fail("Unsupported scale dataset manifest")
    protocol = _validate_protocol(_read(manifest["protocol_reference"]))
    if manifest != _view(protocol, manifest["protocol_reference"], manifest["training_count"]):
        _fail("Scale manifest differs from its exact protocol-derived public view")
    return manifest


def load_scale_rows(manifest_path, *, expected_sha256, role=None):
    if role is not None and role not in dataset.ROLES:
        _fail("Unknown scale runtime role")
    reference = {"path": str(manifest_path), "sha256": expected_sha256}
    manifest = validate_scale_manifest(_read(reference))
    protocol = _read(manifest["protocol_reference"])
    training_inventory, final_inventory = _read(protocol["training_inventory"]), _read(protocol["evaluation_inventory"])
    selected = set(manifest["training_instance_ids"]) | set(manifest["development_instance_ids"])
    descriptors = {row["instance_id"]: row for row in training_inventory["tasks"] if row["instance_id"] in selected}
    rows = dataset._public_rows(training_inventory, descriptors, evaluation=False)
    rows.update(dataset._public_rows(final_inventory, {row["instance_id"]: row for row in final_inventory["tasks"]}, evaluation=True))
    for target in manifest["targets"]:
        if plan.sha(plan.canonical(rows[target["instance_id"]])) != target["public_source_row_sha256"]:
            _fail("Scale public row differs from its frozen target")
    plan._reference(reference)
    targets = [dict(target) for target in manifest["targets"] if role is None or target["role"] == role]
    return targets, {target["instance_id"]: rows[target["instance_id"]] for target in targets}, manifest


def public_grader_manifest(target, manifest):
    """Public membership/source adapter for the existing manager-only grader boundary."""
    manifest = validate_scale_manifest(manifest)
    public = {key: value for key, value in target.items() if key != "source_row_sha256"}
    if public not in manifest["targets"]:
        _fail("Grader target is outside the loaded scale dataset")
    source = manifest["datasets"][public.get("evaluation_scope") or "TRAINING"]
    return {"schema": dataset.SCHEMA, "status": "VALIDATED_SCALE_PUBLIC_GRADER_ADAPTER",
        "protocol_reference": manifest["protocol_reference"], "targets": [public],
        "datasets": {"TRAINING": manifest["datasets"]["TRAINING"], "EVALUATION": source}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "validate"))
    parser.add_argument("--original-manifest", type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    args = parser.parse_args()
    root = args.output_directory.resolve()
    if args.command == "build":
        if args.original_manifest is None:
            parser.error("build requires the frozen original manifest")
        protocol = build_scale_protocol(_reference(args.original_manifest.resolve()), output=root / "protocol.json", seed=args.seed)
        manifests = {str(size): build_scale_manifest(protocol, training_size=size, output=root / f"dataset-{size}.json") for size in (24, 120, 240)}
        result = {"protocol_reference": protocol, "dataset_references": manifests,
            "training_sizes": [24, 120, 240], "development": 60, "final_evaluation": 500,
            "model_calls": 0, "official_grader_runs": 0, "runtime_compatibility_verified": False}
        receipt = _retain(root / "selection-receipt.json", result)
        print(plan.canonical({**result, "selection_receipt": receipt}).decode())
    else:
        receipt = _read(_reference(root / "selection-receipt.json"))
        verify_scale_protocol(receipt["protocol_reference"])
        for reference in receipt["dataset_references"].values():
            load_scale_rows(reference["path"], expected_sha256=reference["sha256"])
        print(plan.canonical({"status": "PASS_PUBLIC_ROWS", "dataset_sizes": [24, 120, 240], "model_calls": 0, "official_grader_runs": 0}).decode())


if __name__ == "__main__":
    main()
