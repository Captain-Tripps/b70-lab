"""Disposable fixture for the STEP-000 tool-loop proof.

The test states the contract. The implementation has a real defect (wrong separator and a
missing space). The repair must change the implementation; weakening the assertion would be
the exact failure mode the plan forbids.
"""


def greeting(name: str) -> str:
    # Repaired 2026-10-27: the defect was the separator and spacing, not the contract.
    # The assertions were left exactly as written.
    return f"Hello, {name}!"


def test_greeting_contract():
    assert greeting("Zeus") == "Hello, Zeus!"
    assert greeting("") == "Hello, !"


def test_greeting_returns_str():
    assert isinstance(greeting("a"), str)
