"""Static fail-closed checks for the standalone TriMem 0015 migration."""
import hashlib
import importlib.util
import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[2]
SQLDIR = ROOT / "migrations" / "sql"
SQL = (SQLDIR / "0015_up.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
VERSION = ROOT / "migrations" / "versions" / "0015_trimem_graph_memory.py"

TABLES = [
    "trimem_graphs",
    "trimem_graph_nodes",
    "trimem_graph_edges",
    "trimem_semantic_supports",
    "trimem_memory_access_events",
    "trimem_graph_checkpoints",
    "trimem_policy_transitions",
    "trimem_semantic_strengths",
    "trimem_namespace_claims",
    "trimem_vector_index_outbox",
    "trimem_session_checkpoints",
    "trimem_lifecycle_operation_receipts",
    "trimem_promotion_evidence",
]
CHILD_TABLES = TABLES[1:8]
OWNER_TABLES = [table for table in TABLES if table != "trimem_promotion_evidence"]
APPEND_ONLY = [
    "trimem_semantic_supports",
    "trimem_memory_access_events",
    "trimem_graph_checkpoints",
    "trimem_policy_transitions",
    "trimem_session_checkpoints",
    "trimem_lifecycle_operation_receipts",
    "trimem_promotion_evidence",
]
TEMPORAL = [
    "event_time",
    "ingested_at",
    "source_available_at",
    "last_accessed_at",
    "last_used_at",
    "last_verified_at",
    "valid_from",
    "valid_until",
]


def _block(table):
    return SQL.split("CREATE TABLE %s" % table, 1)[1].split("CREATE TABLE", 1)[0]


def test_exact_graph_table_family_is_created():
    for table in TABLES:
        assert re.search(r"CREATE TABLE %s\b" % table, SQL), table
    assert SQL.count("CREATE TABLE ") == len(TABLES)


def test_every_table_has_forced_rls_and_org_namespace_policy():
    for table in TABLES:
        assert "ALTER TABLE %s ENABLE ROW LEVEL SECURITY" % table in SQL, table
        assert "ALTER TABLE %s FORCE ROW LEVEL SECURITY" % table in SQL, table
        assert "CREATE POLICY org_isolation ON %s" % table in SQL, table
        assert "CREATE POLICY namespace_isolation ON %s AS RESTRICTIVE" % table in SQL, table
        namespace_policy = SQL.split(
            "CREATE POLICY namespace_isolation ON %s" % table, 1
        )[1].split(";", 1)[0]
        assert "app.trimem_namespace" in namespace_policy, table
        assert "WITH CHECK" in namespace_policy, table
    for table in OWNER_TABLES:
        assert "CREATE POLICY private_owner ON %s AS RESTRICTIVE" % table in SQL, table
        owner_policy = SQL.split(
            "CREATE POLICY private_owner ON %s" % table, 1
        )[1].split(";", 1)[0]
        assert "app.user_id" in owner_policy, table
        assert "WITH CHECK" in owner_policy, table
    assert "CREATE POLICY private_owner ON trimem_promotion_evidence" not in SQL


def test_child_owner_is_denormalized_and_trigger_checked_against_header():
    for table in CHILD_TABLES:
        block = _block(table)
        assert "org_id UUID NOT NULL" in block, table
        assert "namespace TEXT NOT NULL" in block, table
        assert "graph_id UUID NOT NULL" in block, table
        assert "graph_kind TEXT NOT NULL" in block, table
        assert "owner_user_id UUID" in block, table
    for stem in ("node", "edge", "support", "access", "checkpoint", "transition", "strength"):
        assert "CREATE TRIGGER trimem_%s_partition_guard" % stem in SQL, stem
    assert "NEW.owner_user_id IS DISTINCT FROM header_owner" in SQL
    assert "NEW.graph_kind IS DISTINCT FROM header_kind" in SQL
    assert "NEW.namespace IS DISTINCT FROM header_namespace" in SQL
    assert "INTO header_namespace, header_kind, header_owner, header_state" in SQL
    assert "namespace = NEW.namespace" in SQL
    assert "header_state <> 'ACTIVE'" in SQL
    assert "TG_TABLE_NAME <> 'trimem_memory_access_events'" in SQL
    assert "only access audit may append to a sealed or archived trimem graph" in SQL


def test_private_owner_and_shared_review_constraints_are_fail_closed():
    for table in ("trimem_graphs", "trimem_graph_nodes", "trimem_graph_edges"):
        block = _block(table)
        assert "graph_kind = 'ORGANISATION_SEMANTIC' AND owner_user_id IS NULL" in block
        assert "HUMAN_REVIEW" in block and "TRUSTED_DOCUMENT" in block
        assert "review_evidence_hash IS NOT NULL" in block
    support = _block("trimem_semantic_supports")
    assert "source_episode_id IS NULL" in support
    assert "trimem_validate_support_source" in SQL
    assert "source_owner IS DISTINCT FROM NEW.owner_user_id" in SQL
    assert "source_payload_hash IS DISTINCT FROM NEW.source_evidence_hash" in SQL
    assert "trimem_support_episode_fk" in support
    assert "trimem_validate_semantic_target" in SQL
    assert "target_type <> 'SemanticRule'" in SQL


def test_semantic_strength_updates_are_identity_bound_and_monotonic():
    assert "CREATE FUNCTION trimem_validate_strength_monotonic()" in SQL
    assert "CREATE TRIGGER trimem_strength_monotonic_guard" in SQL
    assert "semantic_node_id)" in SQL
    for field in (
        "updated_at",
        "support",
        "successful_reuse",
        "independent_user_evidence",
        "recent_verification",
        "negative_transfer",
        "contradiction",
        "version_staleness",
    ):
        assert "NEW.%s < OLD.%s" % (field, field) in SQL
    assert "REVOKE ALL ON FUNCTION trimem_validate_strength_monotonic()" in SQL


def test_graph_node_edge_temporal_metadata_is_complete():
    for table in ("trimem_graphs", "trimem_graph_nodes", "trimem_graph_edges"):
        block = _block(table)
        for column in TEMPORAL:
            assert re.search(r"\b%s\b" % column, block), (table, column)


def test_qdrant_fields_are_protocol_metadata_only():
    block = _block("trimem_graph_nodes")
    for field in (
        "vector_index_schema_version",
        "vector_collection_scope",
        "embedding_model_id",
        "embedding_revision",
        "embedding_dimension",
        "payload_hash",
        "content_hash",
    ):
        assert field in block
    assert "vector_index_schema_version = 2" in block
    assert "vector_collection_scope = 'shared'" in block
    assert "vector_collection_scope = 'private'" in block


def test_policy_cannot_publish_shared_and_review_authority_excludes_dqn():
    transition = _block("trimem_policy_transitions")
    assert "target_graph_kind IN ('USER_EPISODIC','USER_SEMANTIC')" in transition
    assert "MOVE_TO_SEMANTIC_CANDIDATE" in transition
    assert "target_graph_kind = 'USER_SEMANTIC'" in transition
    assert "ORGANISATION_SEMANTIC" in transition  # explicit named deny constraint
    assert "review_authority IN ('HUMAN_REVIEW','TRUSTED_DOCUMENT')" in SQL
    assert "review_authority IN ('DOUBLE_DQN'" not in SQL


def test_fifo_provenance_strength_and_append_only_foundations_exist():
    node = _block("trimem_graph_nodes")
    assert "payload_hash TEXT NOT NULL" in node
    assert "archived_at TIMESTAMPTZ" in node
    assert "archive_reason TEXT" in node
    assert "archived_from_content_hash TEXT" in node
    strength = _block("trimem_semantic_strengths")
    expected_terms = (
        "support + successful_reuse + independent_user_evidence + recent_verification"
        "\n      - negative_transfer - contradiction - version_staleness"
    )
    assert expected_terms in strength
    assert "GENERATED ALWAYS" in strength and "STORED" in strength
    for table in APPEND_ONLY:
        stem = {
            "trimem_semantic_supports": "support",
            "trimem_memory_access_events": "access",
            "trimem_graph_checkpoints": "checkpoint",
            "trimem_policy_transitions": "transition",
            "trimem_session_checkpoints": "session_checkpoint",
            "trimem_lifecycle_operation_receipts": "lifecycle_receipt",
            "trimem_promotion_evidence": "promotion_evidence",
        }[table]
        assert "CREATE TRIGGER trimem_%s_immutable" % stem in SQL
        assert "BEFORE UPDATE OR DELETE ON %s" % table in SQL


def test_namespace_claim_closes_freshness_race_and_binds_frozen_arm_inputs():
    claim = _block("trimem_namespace_claims")
    for field in (
        "namespace TEXT NOT NULL", "experiment_id TEXT NOT NULL", "split TEXT NOT NULL",
        "arm_id TEXT NOT NULL", "task_order_hash TEXT NOT NULL", "config_hash TEXT NOT NULL",
        "run_nonce UUID NOT NULL", "next_sequence_index BIGINT NOT NULL",
    ):
        assert field in claim
    assert "PRIMARY KEY (org_id, namespace)" in claim
    assert "UNIQUE (run_nonce)" in claim


def test_vector_index_outbox_is_durable_hash_bound_and_tenant_scoped():
    outbox = _block("trimem_vector_index_outbox")
    for field in (
        "namespace TEXT NOT NULL",
        "owner_user_id UUID",
        "node_id UUID NOT NULL",
        "canonical_content_hash TEXT NOT NULL",
        "status TEXT NOT NULL DEFAULT 'PENDING'",
        "attempts INTEGER NOT NULL DEFAULT 0",
        "last_error TEXT",
        "created_at TIMESTAMPTZ NOT NULL",
        "updated_at TIMESTAMPTZ NOT NULL",
        "indexed_at TIMESTAMPTZ",
    ):
        assert field in outbox
    assert "status IN ('PENDING','INDEXED','CANCELLED')" in outbox
    assert "operation IN ('UPSERT','DELETE')" in outbox
    assert "prior_content_hash TEXT" in outbox
    assert "trimem_outbox_node_fk" in outbox
    assert "UNIQUE (org_id, namespace, node_id, canonical_content_hash)" in outbox
    assert "CREATE TRIGGER trimem_vector_outbox_guard" in SQL
    assert "node_hash IS DISTINCT FROM NEW.canonical_content_hash" in SQL
    assert "node_state <> 'ACTIVE'" in SQL
    assert "completed trimem vector outbox intent is terminal" in SQL
    assert "ix_trimem_vector_outbox_pending" in SQL


def test_session_checkpoint_journal_is_immutable_and_claim_bound():
    block = _block("trimem_session_checkpoints")
    for field in (
        "run_nonce UUID NOT NULL",
        "next_sequence_index BIGINT NOT NULL",
        "checkpoint_schema TEXT NOT NULL",
        "checkpoint_payload JSONB NOT NULL",
        "checkpoint_digest TEXT NOT NULL",
    ):
        assert field in block
    assert "trimem_session_checkpoint_claim_fk" in block
    assert "trimem_session_checkpoint_envelope" in block
    assert "checkpoint_payload->>'schema' = checkpoint_schema" in block
    assert "checkpoint_payload->>'namespace' = namespace" in block
    assert "checkpoint_payload->>'run_nonce' = run_nonce::text" in block
    assert "checkpoint_payload->>'next_sequence_index'" in block
    assert "UNIQUE (org_id, namespace, run_nonce, next_sequence_index)" in block


def test_lifecycle_operation_receipt_is_private_immutable_and_digest_bound():
    block = _block("trimem_lifecycle_operation_receipts")
    for field in (
        "owner_user_id UUID NOT NULL",
        "bundle_digest TEXT NOT NULL",
        "receipt_payload JSONB NOT NULL",
    ):
        assert field in block
    assert "trimem_lifecycle_receipt_identity" in block
    assert "receipt_payload->>'operation_id' = id::text" in block
    assert "receipt_payload->>'bundle_digest' = bundle_digest" in block
    assert "CREATE TRIGGER trimem_lifecycle_receipt_immutable" in SQL
    grants = SQL.split("GRANT SELECT, INSERT ON trimem_semantic_supports", 1)[1].split(
        "TO api_service, worker_service;", 1
    )[0]
    assert "trimem_lifecycle_operation_receipts" in grants


def test_api_health_can_read_only_the_alembic_head_metadata_it_queries():
    assert "GRANT SELECT ON alembic_version TO api_service;" in SQL


def test_promotion_evidence_is_sanitized_org_visible_and_content_free():
    block = SQL.split("CREATE TABLE trimem_promotion_evidence", 1)[1].split(");", 1)[0]
    for forbidden in (
        "owner_user_id", "node_id", "episode_id", "task_id", "canonical_payload"
    ):
        assert forbidden not in block
    for required in (
        "evidence_hash", "contributor_hash", "public_evidence_hash",
        "verifier_hash", "extraction_hash", "attestation_hash", "verified_at",
    ):
        assert required in block
    assert "source_kind = 'VERIFIED_EPISODE'" in block
    assert "source_outcome = 'passed'" in block
    assert "CREATE TRIGGER trimem_promotion_evidence_guard" in SQL
    assert "promotion evidence has no matching verified private episode" in SQL


def test_security_definer_validation_functions_have_fixed_path_and_public_revoked():
    functions = [
        "trimem_validate_graph_header",
        "trimem_validate_vector_outbox",
        "trimem_validate_promotion_evidence",
        "trimem_enforce_graph_partition",
        "trimem_validate_support_source",
        "trimem_validate_semantic_target",
        "trimem_validate_access_actor",
        "trimem_reject_structural_cycle",
    ]
    for name in functions:
        declaration = SQL.split("CREATE FUNCTION %s()" % name, 1)[1].split("AS $$", 1)[0]
        assert "SECURITY DEFINER" in declaration, name
        assert "SET search_path = pg_catalog, public" in declaration, name
        assert "REVOKE ALL ON FUNCTION %s() FROM PUBLIC" % name in SQL, name


def test_hash_guard_and_single_0015_revision_match():
    expected = (SQLDIR / "0015_up.sha256").read_text(encoding="utf-8").strip()
    assert hashlib.sha256(SQL.encode()).hexdigest() == expected
    source = VERSION.read_text(encoding="utf-8")
    assert 'revision = "0015"' in source
    assert 'down_revision = "0014"' in source
    assert "0015_up.sql hash mismatch" in source

    spec = importlib.util.spec_from_file_location("trimem_migration", VERSION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0015"
    assert module.down_revision == "0014"
