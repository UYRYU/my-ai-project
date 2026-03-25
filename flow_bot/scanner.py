"""Unusual Options Flow Scanner - Polygon.io APIからオプションデータを取得・フィルタリング"""

from datetime import datetime, timedelta
from dataclasses import dataclass

import requests

import config


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

    contracts = []
    while url:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        contracts.extend(data.get("results", []))
        # ページネーション
        next_url = data.get("next_url")
        if next_url:
            url = next_url
            params = {"apiKey": config.POLYGON_API_KEY}
        else:
            break

    return contracts


def _get_snapshot(ticker: str) -> list[dict]:
    """オプションチェーンのスナップショット（volume, OI, last price）を取得"""
    url = (
        f"{config.POLYGON_BASE_URL}/v3/snapshot/options/{ticker}"
    )
    params = {
        "limit": 250,
        "apiKey": config.POLYGON_API_KEY,
    }

    results = []
    while url:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("results", []))
        next_url = data.get("next_url")
        if next_url:
            url = next_url
            params = {"apiKey": config.POLYGON_API_KEY}
        else:
            break

    return results


def _calc_dte(expiration: str) -> int:
    """満期までの日数を計算"""
    exp_date = datetime.strptime(expiration, "%Y-%m-%d")
    return (exp_date - datetime.now()).days


def _passes_filters(snap: dict) -> bool:
    """検出条件を満たすか判定"""
    details = snap.get("details", {})
    day = snap.get("day", {})

    # CALLのみ
    if details.get("contract_type", "").lower() != config.SIDE_FILTER:
        return False

    # DTE チェック
    expiration = details.get("expiration_date", "")
    if not expiration:
        return False
    dte = _calc_dte(expiration)
    if dte < 0 or dte > config.MAX_DTE:
        return False

    volume = day.get("volume", 0)
    open_interest = snap.get("open_interest", 0)

    # Volume/OI比
    if open_interest <= 0:
        return False
    vol_oi = volume / open_interest
    if vol_oi < config.MIN_VOLUME_OI_RATIO:
        return False

    # プレミアム推定 (volume × last_price × 100)
    last_price = snap.get("last_quote", {}).get("midpoint", 0)
    if last_price <= 0:
        last_price = day.get("close", 0)
    premium = volume * last_price * 100
    if premium < config.MIN_PREMIUM_USD:
        return False

    return True


def _to_option_flow(snap: dict, ticker: str) -> OptionFlow:
    """スナップショットデータをOptionFlowに変換"""
    details = snap.get("details", {})
    day = snap.get("day", {})

    expiration = details.get("expiration_date", "")
    volume = day.get("volume", 0)
    open_interest = snap.get("open_interest", 0)

    last_price = snap.get("last_quote", {}).get("midpoint", 0)
    if last_price <= 0:
        last_price = day.get("close", 0)

    return OptionFlow(
        ticker=ticker,
        contract=details.get("ticker", ""),
        strike=details.get("strike_price", 0),
        expiration=expiration,
        dte=_calc_dte(expiration),
        volume=volume,
        open_interest=open_interest,
        volume_oi_ratio=round(volume / max(open_interest, 1), 2),
        premium=round(volume * last_price * 100, 2),
        side=details.get("contract_type", "").lower(),
    )


def scan_ticker(ticker: str) -> list[OptionFlow]:
    """1銘柄をスキャンし、条件を満たすフローを返す"""
    try:
        snapshots = _get_snapshot(ticker)
    except requests.RequestException as e:
        print(f"[ERROR] {ticker} snapshot取得失敗: {e}")
        return []

    flows = []
    for snap in snapshots:
        if _passes_filters(snap):
            flows.append(_to_option_flow(snap, ticker))

    return flows


def scan_all() -> list[OptionFlow]:
    """全監視銘柄をスキャンし、異常フローを返す"""
    all_flows = []
    for ticker in config.WATCHLIST:
        flows = scan_ticker(ticker)
        all_flows.extend(flows)
    return all_flows
