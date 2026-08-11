"""§6.2/§11 sandbox: legit pass + every deliberate-failure fixture is rejected/detected."""
import os
import tempfile
import shutil
import pytest
from enterprise_memory.serving import sandbox as SB


@pytest.fixture()
def fixture_repo():
    d = tempfile.mkdtemp(prefix="est_fix_")
    with open(os.path.join(d, "mod.py"), "w", encoding="utf-8") as f:
        f.write("def solve():\n    return 0\n")
    with open(os.path.join(d, "test_hidden.py"), "w", encoding="utf-8") as f:
        f.write("from mod import solve\n\ndef test_h():\n    assert solve() == 42\n")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_correct_patch_passes(fixture_repo):
    r = SB.run_task(fixture_repo, {"mod.py": "def solve():\n    return 42\n"}, "test_hidden.py", timeout=30)
    assert r["passed"] and r["exec_ok"] and not r["violations"]


def test_wrong_patch_fails(fixture_repo):
    r = SB.run_task(fixture_repo, {"mod.py": "def solve():\n    return 1\n"}, "test_hidden.py", timeout=30)
    assert not r["passed"] and not r["violations"]


def test_parent_and_absolute_write_detected():
    assert "path_traversal_or_absolute_write" in SB.static_guard("open('../evil.txt','w')")
    assert "path_traversal_or_absolute_write" in SB.static_guard("open('C:/Windows/x','w')")


def test_dotenv_and_env_detected():
    assert "dotenv_or_env_access" in SB.static_guard("data = open('.env').read()")
    assert "dotenv_or_env_access" in SB.static_guard("import os; os.environ['SECRET']")


def test_network_attempt_detected():
    assert "network_attempt" in SB.static_guard("import socket; socket.socket()")
    assert "network_attempt" in SB.static_guard("import urllib.request as u; u.urlopen('http://x')")


def test_hidden_test_read_detected():
    assert "hidden_test_read" in SB.static_guard("open('test_hidden.py').read()", hidden_names=("test_hidden.py",))
    assert "hidden_test_read" in SB.static_guard("gold = open('expected_outputs.json')")


def test_guarded_patch_rejected_before_exec(fixture_repo):
    r = SB.run_task(fixture_repo, {"mod.py": "import socket\ndef solve():\n    return 42\n"}, "test_hidden.py")
    assert r.get("rejected_before_exec") and "network_attempt" in r["violations"]


def test_hang_times_out(fixture_repo):
    patch = "import time\ndef solve():\n    time.sleep(60)\n    return 42\n"
    # the hidden test imports solve and calls it -> sleeps -> timeout
    r = SB.run_task(fixture_repo, {"mod.py": patch}, "test_hidden.py", timeout=3)
    assert "timeout" in r["violations"] and not r["passed"]


def test_fresh_dir_no_cross_condition_state(fixture_repo):
    # writing a marker file in one run must not appear in the next (fresh temp dir each call)
    SB.run_task(fixture_repo, {"mod.py": "def solve():\n    return 42\n", "marker.txt": "leak"}, "test_hidden.py")
    r2 = SB.run_task(fixture_repo, {"mod.py": "import os\ndef solve():\n    return 42 if not os.path.exists('marker.txt') else 0\n"}, "test_hidden.py")
    assert r2["passed"]   # marker.txt from the prior run is absent -> returns 42
