from enterprise_memory.promotion import security_scan as S


def test_true_positives():
    assert S.scan("-----BEGIN RSA PRIVATE KEY-----\nMIIB")["result"] == S.BLOCK_SECRET
    assert S.scan("token ghp_" + "a"*36)["result"] == S.BLOCK_SECRET
    assert S.scan("AKIA" + "1234567890ABCDEF")["result"] == S.BLOCK_SECRET
    assert S.scan("key sk-" + "A"*24)["result"] == S.BLOCK_SECRET
    assert S.scan("Authorization: Bearer " + "x"*24)["result"] == S.BLOCK_SECRET
    assert S.scan("password = 'hunter2xyz'")["result"] == S.BLOCK_SECRET
    assert S.scan("contact me at alice@example.com about it")["result"] == S.BLOCK_PII
    assert S.scan("call 010-1234-5678 now")["result"] == S.BLOCK_PII


def test_false_positive_guard_ordinary_code():
    # ordinary short code snippet must PASS (not flagged as secret/PII)
    code = "def add(a, b):\n    return a + b\n"
    assert S.scan(code, allow_source_lines=8)["result"] == S.PASS


def test_fake_benchmark_tokens_not_blocked():
    # fictional benchmark markers stay distinguishable from real secrets
    assert S.scan("use tenant class ORCHID with retry multiplier 2")["result"] == S.PASS
    assert not S.scan("FAKE-EXAMPLE token sk-fake-not-a-secret")["blocking"]


def test_blocking_forbids_promotion():
    ok, r = S.is_promotable("-----BEGIN PRIVATE KEY-----")
    assert not ok and r["result"] == S.BLOCK_SECRET
