"""Unusual Options Flow Scanner - Polygon.io APIからオプションデータを取得・フィルタリング"""

import time
from datetime import datetime, timedelta
from dataclasses import dataclass

import requests

import config

# 無料プランのレート制限対応（5 calls/min）
API_CALL_DELAY = 13  # 秒


@dataclass
class OptionFlow:
    """検出されたオプションフロー"""
    ticker: str
    contract: str
    strike: float
    expiration: str
    dte: int
    volume: int
    open_interest: int
    volume_oi_ratio: float
    premium: float
    side: str  # "call" or "put"


def _api_get(url: str, params: dict) -> dict:
    """API呼び出し（レート制限対応付き）"""
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    time.sleep(API_CALL_DELAY)
    return resp.json()


def _get_option_contracts(ticker: str) -> list[dict]:
    """指定銘柄のオプション契約一覧を取得（DTE 30日以内、CALLのみ）
    ページネーションで全件取得する。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    max_exp = (datetime.now() + timedelta(days=config.MAX_DTE)).strftime("%Y-%m-%d")

    url = f"{config.POLYGON_BASE_URL}/v3/reference/options/contracts"
    params = {
        "underlying_ticker": ticker,
        "contract_type": config.SIDE_FILTER,
        "expiration_date.gte": today,
        "expiration_date.lte": max_exp,
        "expired": "false",
        "limit": 250,
        "apiKey": config.POLYGON_API_KEY,
    }

    all_contracts = []
    while url:
        data = _api_get(url, params)
        all_contracts.extend(data.get("results", []))
        next_url = data.get("next_url")
        if next_url:
            url = next_url
            params = {"apiKey": config.POLYGON_API_KEY}
        else:
            break

    return all_contracts


def _get_contract_bar(contract_ticker: str) -> dict | None:
    """個別契約の前日barを取得（出来高・終値）"""
    url = f"{config.POLYGON_BASE_URL}/v2/aggs/ticker/{contract_ticker}/prev"
    params = {
        "adjusted": "true",
        "apiKey": config.POLYGON_API_KEY,
    }

    data = _api_get(url, params)
    results = data.get("results", [])
    return results[0] if results else None


def _calc_dte(expiration: str) -> int:
    """満期までの日数を計算"""
    exp_date = datetime.strptime(expiration, "%Y-%m-%d")
    return (exp_date - datetime.now()).days


def _prefilter_contracts(contracts: list[dict]) -> list[dict]:
    """DTE条件でフィルタし、直近満期順にソート。
    無料プランではOIが取得できないため、OIフィルタはbar取得後に行う。
    """
    candidates = []
    for c in contracts:
        exp = c.get("expiration_date", "")
        if not exp:
            continue
        dte = _calc_dte(exp)
        if dte < 0 or dte > config.MAX_DTE:
            continue
        candidates.append(c)

    # 直近満期順（活発な取引が多い）
    candidates.sort(key=lambda c: c.get("expiration_date", ""))

    # APIコール数を制限
    return candidates[:config.MAX_CONTRACTS_PER_TICKER]


def scan_ticker(ticker: str) -> list[OptionFlow]:
    """1銘柄をスキャンし、条件を満たすフローを返す"""
    try:
        contracts = _get_option_contracts(ticker)
    except requests.RequestException as e:
        print(f"[ERROR] {ticker} contracts取得失敗: {e}")
        return []

    if not contracts:
        return []

    candidates = _prefilter_contracts(contracts)
    print(f"  {ticker}: {len(contracts)} contracts → {len(candidates)} candidates")

    flows = []
    for contract in candidates:
        contract_ticker = contract.get("ticker", "")
        expiration = contract.get("expiration_date", "")
        strike = contract.get("strike_price", 0)
        open_interest = contract.get("open_interest", 0)

        try:
            bar = _get_contract_bar(contract_ticker)
        except requests.RequestException as e:
            print(f"  [WARN] {contract_ticker} スキップ: {e}")
            continue

        if not bar:
            continue

        volume = bar.get("v", 0)
        close_price = bar.get("c", 0)

        if volume <= 0 or close_price <= 0:
            continue

        # OIが取得できない場合（無料プラン）はVol/OI比チェックをスキップ
        if open_interest > 0:
            vol_oi = volume / open_interest
            if vol_oi < config.MIN_VOLUME_OI_RATIO:
                continue
        else:
            vol_oi = 0.0

        premium = volume * close_price * 100
        if premium < config.MIN_PREMIUM_USD:
            continue

        print(f"    ✅ {contract_ticker} | Vol:{int(volume):,} | Premium:${premium/1000:.1f}K")

        flows.append(OptionFlow(
            ticker=ticker,
            contract=contract_ticker,
            strike=strike,
            expiration=expiration,
            dte=_calc_dte(expiration),
            volume=int(volume),
            open_interest=int(open_interest),
            volume_oi_ratio=round(vol_oi, 2),
            premium=round(premium, 2),
            side=contract.get("contract_type", "call").lower(),
        ))

    return flows


def scan_all() -> list[OptionFlow]:
    """全監視銘柄をスキャンし、異常フローを返す"""
    all_flows = []
    for ticker in config.WATCHLIST:
        flows = scan_ticker(ticker)
        all_flows.extend(flows)
    return all_flows
