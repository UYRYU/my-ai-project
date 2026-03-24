"""CSVデータの読み込み・前処理"""

import os
import pandas as pd


def load_ohlc(filepath: str) -> pd.DataFrame:
    """CSV形式のOHLCデータを読み込む。

    期待フォーマット: timestamp,open,high,low,close,volume
    """
    df = pd.read_csv(filepath)

    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"必須カラムが不足: {missing}")

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)

    return df


def discover_data_files(data_dir: str) -> list[dict]:
    """data_dir内のCSVファイルを検出し、通貨ペアと時間足の情報を返す。

    ファイル命名規則: {SYMBOL}_{TIMEFRAME}.csv
    例: USDJPY_M1.csv, EURJPY_M5.csv
    """
    results = []
    if not os.path.isdir(data_dir):
        return results

    for filename in sorted(os.listdir(data_dir)):
        if not filename.endswith(".csv"):
            continue
        name = filename.replace(".csv", "")
        parts = name.split("_")
        if len(parts) >= 2:
            symbol = parts[0]
            timeframe = parts[1]
        else:
            symbol = name
            timeframe = "unknown"

        results.append({
            "symbol": symbol,
            "timeframe": timeframe,
            "filepath": os.path.join(data_dir, filename),
        })

    return results
