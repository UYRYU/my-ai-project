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
    """指定銘柄のオプション契約一覧を取得（DTE 30日以内、CALLのみ）"""
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

    data = _api_get(url, params)
    return data.get("results", [])


def _get_contract_details(contract_ticker: str) -> dict | None:
    """個別契約のdaily barを取得（前日の出来高・終値）"""
    # 前営業日のデータを取得
    url = f"{config.POLYGON_BASE_URL}/v2/aggs/ticker/{contract_ticker}/prev"
    params = {
        "adjusted": "true",
        "apiKey": config.POLYGON_API_KEY,
    }

    data = _api_get(url, params)
    results = data.get("results", [])
    if results:
        return results[0]
    return None


def _calc_dte(expiration: str) -> int:
    """満期までの日数を計算"""
    exp_date = datetime.strptime(expiration, "%Y-%m-%d")
    return (exp_date - datetime.now()).days


def scan_ticker(ticker: str) -> list[OptionFlow]:
    """1銘柄をスキャンし、条件を満たすフローを返す"""
    try:
        contracts = _get_option_contracts(ticker)
    except requests.RequestException as e:
        print(f"[ERROR] {ticker} contracts取得失敗: {e}")
        return []

    if not contracts:
        return []

    print(f"  {ticker}: {len(contracts)} contracts found, checking details...")
    flows = []

    for contract in contracts:
        contract_ticker = contract.get("ticker", "")
        expiration = contract.get("expiration_date", "")
        strike = contract.get("strike_price", 0)

        if not contract_ticker or not expiration:
            continue

        dte = _calc_dte(expiration)
        if dte < 0 or dte > config.MAX_DTE:
            continue

        try:
            bar = _get_contract_details(contract_ticker)
        except requests.RequestException as e:
            print(f"  [WARN] {contract_ticker} スキップ: {e}")
            continue

        if not bar:
            continue

        volume = bar.get("v", 0)
        close_price = bar.get("c", 0)

        # OIはcontracts APIのopen_interestを使用
        open_interest = contract.get("open_interest", 0)

        # フィルタリング
        if open_interest <= 0:
            continue
        vol_oi = volume / open_interest
        if vol_oi < config.MIN_VOLUME_OI_RATIO:
            continue

        premium = volume * close_price * 100
        if premium < config.MIN_PREMIUM_USD:
            continue

        flows.append(OptionFlow(
            ticker=ticker,
            contract=contract_ticker,
            strike=strike,
            expiration=expiration,
            dte=dte,
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
