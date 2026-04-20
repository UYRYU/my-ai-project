"""Pre-flight check: verify the bot can run before you launch it.

Validates env vars, derives addresses without leaking secrets, probes
Polymarket Gamma + CLOB endpoints, and checks USDC balance on Polygon
via a public RPC. No private keys leave the process.

Usage:
    python -m src.healthcheck
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv

POLYGON_RPC = "https://polygon-rpc.com"
USDC_E_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e on Polygon (Polymarket's collateral)
GAMMA_HEALTH = "https://gamma-api.polymarket.com/markets?limit=1"
CLOB_HEALTH = "https://clob.polymarket.com/time"

PRIVKEY_RE = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str

    def line(self) -> str:
        mark = "✓" if self.ok else "✗"
        return f"  {mark} {self.name}: {self.detail}"


def _redact(addr: str) -> str:
    if len(addr) < 12:
        return "<short>"
    return f"{addr[:6]}...{addr[-4:]}"


def _check_env() -> list[CheckResult]:
    results = []

    anth = os.environ.get("ANTHROPIC_API_KEY", "")
    if not anth:
        results.append(CheckResult("ANTHROPIC_API_KEY", False, "未設定 (Claude スカウトはスキップされる)"))
    elif not anth.startswith("sk-ant-"):
        results.append(CheckResult("ANTHROPIC_API_KEY", False, "形式が不正 (sk-ant-... で始まるはず)"))
    else:
        results.append(CheckResult("ANTHROPIC_API_KEY", True, f"set ({len(anth)} chars)"))

    pk = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
    if not pk:
        results.append(CheckResult("POLYMARKET_PRIVATE_KEY", False, "未設定 — 発注には必須"))
    elif not PRIVKEY_RE.match(pk):
        results.append(CheckResult("POLYMARKET_PRIVATE_KEY", False, "形式が不正 (0x + 64 hex)"))
    else:
        results.append(CheckResult("POLYMARKET_PRIVATE_KEY", True, "形式 OK (中身は表示しません)"))

    funder = os.environ.get("POLYMARKET_FUNDER_ADDRESS", "")
    if not funder:
        results.append(CheckResult("POLYMARKET_FUNDER_ADDRESS", False, "未設定 — 発注には必須"))
    elif not ADDRESS_RE.match(funder):
        results.append(CheckResult("POLYMARKET_FUNDER_ADDRESS", False, "形式が不正"))
    else:
        results.append(CheckResult("POLYMARKET_FUNDER_ADDRESS", True, _redact(funder)))

    return results


def _check_signer_matches_funder() -> CheckResult:
    pk = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
    funder = os.environ.get("POLYMARKET_FUNDER_ADDRESS", "")
    if not (PRIVKEY_RE.match(pk or "") and ADDRESS_RE.match(funder or "")):
        return CheckResult("signer/funder ペア", False, "前提条件未達 (上のチェック先に解決)")
    try:
        from eth_account import Account  # type: ignore
    except ImportError:
        return CheckResult("signer/funder ペア", False, "eth_account 未インストール — pip install eth-account")
    signer = Account.from_key(pk).address
    if signer.lower() == funder.lower():
        return CheckResult(
            "signer/funder ペア",
            True,
            f"signer == funder ({_redact(signer)}) — Magic ログイン形式",
        )
    return CheckResult(
        "signer/funder ペア",
        True,
        f"signer={_redact(signer)} != funder={_redact(funder)} — proxy ウォレット形式 (Email login)",
    )


def _http_ok(url: str) -> tuple[bool, str]:
    try:
        with httpx.Client(timeout=8.0) as c:
            r = c.get(url)
            return (r.status_code < 400, f"HTTP {r.status_code}")
    except Exception as e:
        return (False, f"{type(e).__name__}: {e}")


def _check_polymarket() -> list[CheckResult]:
    gamma_ok, gamma_msg = _http_ok(GAMMA_HEALTH)
    clob_ok, clob_msg = _http_ok(CLOB_HEALTH)
    return [
        CheckResult("Gamma API 到達性", gamma_ok, gamma_msg),
        CheckResult("CLOB API 到達性", clob_ok, clob_msg),
    ]


def _eth_call_balance_of(address: str) -> int | None:
    """USDC.e balanceOf via JSON-RPC eth_call. No auth, no SDK needed."""
    selector = "0x70a08231"  # balanceOf(address)
    padded = address.lower().replace("0x", "").zfill(64)
    data = selector + padded
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_call",
        "params": [{"to": USDC_E_ADDRESS, "data": data}, "latest"],
        "id": 1,
    }
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.post(POLYGON_RPC, json=payload)
            r.raise_for_status()
            result = r.json().get("result")
            if not result or result == "0x":
                return 0
            return int(result, 16)
    except Exception:
        return None


def _check_usdc_balance() -> CheckResult:
    funder = os.environ.get("POLYMARKET_FUNDER_ADDRESS", "")
    if not ADDRESS_RE.match(funder or ""):
        return CheckResult("USDC.e 残高", False, "POLYMARKET_FUNDER_ADDRESS が必要")
    raw = _eth_call_balance_of(funder)
    if raw is None:
        return CheckResult("USDC.e 残高", False, "Polygon RPC 失敗")
    usdc = raw / 1_000_000  # 6 decimals
    if usdc <= 0:
        return CheckResult(
            "USDC.e 残高",
            False,
            f"{usdc:.6f} USDC — Polymarket に deposit してください",
        )
    return CheckResult("USDC.e 残高", True, f"{usdc:.2f} USDC.e")


def main() -> int:
    load_dotenv()
    print("== polymarket-arb-bot health check ==\n")

    sections: list[tuple[str, list[CheckResult]]] = [
        ("Env", _check_env()),
        ("ウォレット派生", [_check_signer_matches_funder()]),
        ("Polymarket 接続", _check_polymarket()),
        ("オンチェーン残高", [_check_usdc_balance()]),
    ]

    all_ok = True
    for title, checks in sections:
        print(f"[{title}]")
        for c in checks:
            print(c.line())
            if not c.ok:
                all_ok = False
        print()

    if all_ok:
        print("すべて OK — `python main.py` でドライラン開始できます。")
        return 0
    print("いくつか問題あり。上の ✗ を解決してから再実行してください。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
