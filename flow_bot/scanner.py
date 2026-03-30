"""Unusual Options Flow Scanner - Alpaca APIからオプションデータを取得・フィルタリング"""

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


def _get_headers() -> dict:
    """Alpaca API認証ヘッダー"""
    return {
        "APCA-API-KEY-ID": config.ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
    }


def _calc_dte(expiration: str) -> int:
    """満期までの日数を計算"""
    exp_date = datetime.strptime(expiration, "%Y-%m-%d")
    return (exp_date - datetime.now()).days


def _get_option_snapshots(ticker: str) -> dict:
    """Alpaca Options Snapshots APIで銘柄のオプションチェーンを取得"""
    url = f"{config.ALPACA_DATA_URL}/v1beta1/options/snapshots/{ticker}"
    params = {
        "feed": "indicative",
        "limit": 250,
    }

    all_snapshots = {}
    page_token = None

    while True:
        if page_token:
            params["page_token"] = page_token

        resp = requests.get(url, headers=_get_headers(), params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        snapshots = data.get("snapshots", {})
        all_snapshots.update(snapshots)

        page_token = data.get("next_page_token")
        if not page_token:
            break

    return all_snapshots


def _parse_contract_symbol(symbol: str) -> dict | None:
    """オプションシンボルをパース (例: AAPL260410C00200000)"""
    # O:AAPL260410C00200000 形式の場合
    if symbol.startswith("O:"):
        symbol = symbol[2:]

    # 末尾からパース: 8桁価格 + 1桁C/P + 6桁日付 + ティッカー
    if len(symbol) < 16:
        return None

    try:
        price_str = symbol[-8:]
        side_char = symbol[-9]
        date_str = symbol[-15:-9]
        underlying = symbol[:-15]

        strike = int(price_str) / 1000
        exp_date = datetime.strptime(date_str, "%y%m%d").strftime("%Y-%m-%d")
        side = "call" if side_char == "C" else "put"

        return {
            "underlying": underlying,
            "expiration": exp_date,
            "strike": strike,
            "side": side,
        }
    except (ValueError, IndexError):
        return None


def scan_ticker(ticker: str) -> list[OptionFlow]:
    """1銘柄をスキャンし、条件を満たすフローを返す"""
    try:
        snapshots = _get_option_snapshots(ticker)
    except requests.RequestException as e:
        print(f"[ERROR] {ticker} snapshot取得失敗: {e}")
        return []

    if not snapshots:
        print(f"  {ticker}: no snapshots")
        return []

    print(f"  {ticker}: {len(snapshots)} options found")
    flows = []

    for symbol, snap in snapshots.items():
        parsed = _parse_contract_symbol(symbol)
        if not parsed:
            continue

        # CALLのみ
        if parsed["side"] != config.SIDE_FILTER:
            continue

        # DTE チェック
        dte = _calc_dte(parsed["expiration"])
        if dte < 0 or dte > config.MAX_DTE:
            continue

        # latest_trade から出来高取得はできないので day を使う
        # Alpaca snapshot には greeks, latestTrade, latestQuote がある
        latest_trade = snap.get("latestTrade", {})
        latest_quote = snap.get("latestQuote", {})

        volume = snap.get("dayVolume", 0) or 0
        open_interest = snap.get("openInterest", 0) or 0

        if volume <= 0:
            continue

        # 価格の取得（最新取引価格 or ミッドポイント）
        price = latest_trade.get("p", 0)
        if price <= 0:
            bid = latest_quote.get("bp", 0)
            ask = latest_quote.get("ap", 0)
            if bid > 0 and ask > 0:
                price = (bid + ask) / 2

        if price <= 0:
            continue

        # Vol/OI比
        if open_interest > 0:
            vol_oi = volume / open_interest
            if vol_oi < config.MIN_VOLUME_OI_RATIO:
                continue
        else:
            vol_oi = 0.0

        # プレミアム推定
        premium = volume * price * 100
        if premium < config.MIN_PREMIUM_USD:
            continue

        flows.append(OptionFlow(
            ticker=ticker,
            contract=symbol,
            strike=parsed["strike"],
            expiration=parsed["expiration"],
            dte=dte,
            volume=volume,
            open_interest=open_interest,
            volume_oi_ratio=round(vol_oi, 2),
            premium=round(premium, 2),
            side=parsed["side"],
        ))

    return flows


def scan_all() -> list[OptionFlow]:
    """全監視銘柄をスキャンし、異常フローを返す"""
    all_flows = []
    for ticker in config.WATCHLIST:
        flows = scan_ticker(ticker)
        all_flows.extend(flows)
    return all_flows
