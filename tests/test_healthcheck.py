import os
from unittest.mock import patch

from src import healthcheck


def test_redact_short_address():
    assert healthcheck._redact("0x123") == "<short>"


def test_redact_normal_address():
    out = healthcheck._redact("0x7485203DBde7e5bcA3280dc83776cC8dE660258d")
    assert out == "0x7485...258d"


def test_privkey_regex_accepts_with_and_without_prefix():
    assert healthcheck.PRIVKEY_RE.match("0x" + "a" * 64)
    assert healthcheck.PRIVKEY_RE.match("a" * 64)


def test_privkey_regex_rejects_short():
    assert not healthcheck.PRIVKEY_RE.match("0x" + "a" * 63)


def test_address_regex():
    assert healthcheck.ADDRESS_RE.match("0x" + "f" * 40)
    assert not healthcheck.ADDRESS_RE.match("0x" + "f" * 39)
    assert not healthcheck.ADDRESS_RE.match("f" * 40)  # missing 0x


def test_env_check_reports_missing(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "POLYMARKET_PRIVATE_KEY", "POLYMARKET_FUNDER_ADDRESS"):
        monkeypatch.delenv(k, raising=False)
    results = healthcheck._check_env()
    assert all(not r.ok for r in results)


def test_env_check_passes_with_good_values(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-" + "x" * 30)
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "0x" + "1" * 64)
    monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", "0x" + "a" * 40)
    results = healthcheck._check_env()
    assert all(r.ok for r in results)


def test_signer_funder_check_detects_match(monkeypatch):
    # Known test vector: privkey 0x...01 → 0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf
    monkeypatch.setenv("POLYMARKET_PRIVATE_KEY", "0x" + "0" * 63 + "1")
    monkeypatch.setenv("POLYMARKET_FUNDER_ADDRESS", "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf")
    r = healthcheck._check_signer_matches_funder()
    assert r.ok
    assert "Magic" in r.detail
