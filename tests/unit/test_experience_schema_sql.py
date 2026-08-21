"""P6/R19 §5 — static invariants of migrations/sql/0014_up.sql (no live DB; complements ci-postgres)."""
import hashlib
import pathlib
import re

SQLDIR = pathlib.Path(__file__).resolve().parents[2] / "migrations" / "sql"
SQL = (SQLDIR / "0014_up.sql").read_text(encoding="utf-8").replace("\r\n", "\n")

TABLES = [
    "experience_cards", "experience_card_versions", "experience_sources", "experience_source_outcomes",
    "memory_search_sessions", "memory_search_queries", "memory_candidates", "memory_browse_events",
    "memory_decisions", "memory_policy_versions", "memory_outcome_credits", "memory_counterfactual_links",
    "memory_usage_aggregates",
]
# append-only (immutable) tables must NOT be granted UPDATE or DELETE
IMMUTABLE = [
    "experience_card_versions", "experience_sources", "experience_source_outcomes",
    "memory_search_sessions", "memory_search_queries", "memory_candidates", "memory_browse_events",
    "memory_decisions", "memory_policy_versions", "memory_outcome_credits", "memory_counterfactual_links",
]


def _grant_line(table):
    m = re.search(r"GRANT ([^;]+) ON %s TO [^;]+;" % re.escape(table), SQL)
    return m.group(1) if m else ""


def test_all_13_tables_present():
    for t in TABLES:
        assert re.search(r"CREATE TABLE %s\b" % re.escape(t), SQL), t
    assert SQL.count("CREATE TABLE ") == 13


def test_every_table_has_forced_rls_and_policy():
    for t in TABLES:
        assert re.search(r"ALTER TABLE %s ENABLE ROW LEVEL SECURITY" % t, SQL), t
        assert re.search(r"ALTER TABLE %s FORCE ROW LEVEL SECURITY" % t, SQL), t
        assert re.search(r"CREATE POLICY org_isolation ON %s" % t, SQL), t


def test_immutable_tables_have_no_update_or_delete_grant():
    for t in IMMUTABLE:
        g = _grant_line(t)
        assert g, t
        assert "UPDATE" not in g, "%s must be append-only" % t
        assert "DELETE" not in g, "%s must be append-only" % t


def test_mutable_tables_may_update():
    assert "UPDATE" in _grant_line("experience_cards")
    assert "UPDATE" in _grant_line("memory_usage_aggregates")


def test_integrity_constraints_present():
    # current-version pointer references a version OF THIS CARD
    assert "ec_current_same_card_fk" in SQL
    assert "FOREIGN KEY (org_id, id, current_version_id) REFERENCES experience_card_versions(org_id, card_id, id)" in SQL
    # supersession only within the same card
    assert "ecv_supersede_same_card_fk" in SQL
    assert "FOREIGN KEY (org_id, card_id, supersedes_version_id)" in SQL
    # no self-supersede
    assert "ecv_no_self_supersede" in SQL


def test_governance_enum_on_cards_and_versions():
    for t in ("experience_cards", "experience_card_versions"):
        blk = SQL.split("CREATE TABLE %s" % t, 1)[1].split("CREATE TABLE", 1)[0]
        for state in ("candidate", "probation", "promoted", "deprecated", "quarantined", "deleted"):
            assert "'%s'" % state in blk, (t, state)


def test_sha256_matches_guard_file():
    expected = (SQLDIR / "0014_up.sha256").read_text(encoding="utf-8").strip()
    assert hashlib.sha256(SQL.encode()).hexdigest() == expected
