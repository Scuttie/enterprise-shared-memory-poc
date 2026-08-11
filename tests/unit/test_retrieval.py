from enterprise_memory.contracts import schema as S
from enterprise_memory.retrieval import pipeline as PL


def _user():
    return S.UserContext("orgA", "t1", "user_00", "a", ["repoX"], ["src/**"], "dev", "req")


def _task(repo="repoX"):
    return S.TaskContext("t1", "orgA", "user_00", repo, "c", "main", "python", "fw", {}, ["src/api.py"],
                         "fix", ["E"], "env", "2026").stamp()


def _c(cid, state="promoted", repos=("repoX",)):
    return S.MemoryContract(cid, S.SCHEMA_VERSION, "t", "retry rule text " + cid,
        S.ContractScope("orgA", ["t1"], list(repos), ["src/**"], "python", "fw", {}, [], ["E"], ["a"], ["na"]),
        S.ContractAction(["s"], "c", [], ["i"], ["o"]), S.ContractValidity("2020", "", {}, {}, [], [], ""),
        S.ContractVerification(["pytest"], ["ok"], ["nr"], ["f"]), S.ContractProvenance(["ep"], ["u"], ["sha"], ["p"], "x/1"),
        S.ContractEvidence(), S.ContractGovernance(state=state)).stamp()


def test_top_two_cap_and_order():
    shared = [(_c("c%d" % i), "retry rule text c%d unique words here %d" % (i, i)) for i in range(5)]
    out = PL.retrieve_and_inject(_user(), _task(), [], shared, now="2026-01-01")
    assert len(out["injected"]) <= 2


def test_out_of_scope_rejected():
    c = _c("cY")                       # repoX (permission ok) but path-scoped elsewhere
    c.scope.path_globs = ["migrations/**"]
    out = PL.retrieve_and_inject(_user(), _task(repo="repoX"), [], [(c, "text")], now="2026")
    assert out["audit"]["rejections"].get("cY") == "out_of_scope"


def test_abstain_when_none_valid():
    shared = [(_c("cD", state="deprecated"), "text")]
    out = PL.retrieve_and_inject(_user(), _task(), [], shared, now="2026")
    assert out["audit"]["abstained"]


def test_private_isolation_in_pipeline():
    other = S.PrivateEpisode("epB", "user_99", "orgA", "repoX", "t", "s", {}, [], [], "p", [], [], {}, "success", [], "l", "2026")
    out = PL.retrieve_and_inject(_user(), _task(), [(other, "bob private")], [], now="2026")
    assert out["audit"]["rejections"].get("epB") == "not_owner"
