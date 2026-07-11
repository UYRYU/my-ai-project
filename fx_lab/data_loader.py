"""CSVデータの読み込み・前処理

MT4/MT5エクスポートCSVの自動変換にも対応。
"""

import os
import glob
import logging
import pandas as pd

logger = logging.getLogger(__name__)

# ================================================================
# MT4/MT5 CSV 自動変換
# ================================================================

# MT4 History Center エクスポート形式:
#   2024.01.02,00:00,149.967,150.080,149.948,149.988,394
#   (date, time, open, high, low, close, volume)  ヘッダなし or <DATE><TIME>
#
# MT5 エクスポート形式:
#   2024.01.02	00:00:00	149.967	150.080	149.948	149.988	10	394	0
#   (date, time, open, high, low, close, tick_volume, real_volume, spread)  タブ区切り
#   先頭行にヘッダがある場合もある

MT5_HEADER_KEYWORDS = {"<DATE>", "<TIME>", "<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>",
                        "date", "time", "open", "high", "low", "close"}


def _detect_format(filepath: str) -> str:
    """CSVのフォーマットを自動判定する。

    Returns: "standard" | "mt4" | "mt5"
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        first_line = f.readline().strip()
        second_line = f.readline().strip()

    # 標準フォーマット: timestamp,open,high,low,close,volume
    if "timestamp" in first_line.lower() and "open" in first_line.lower():
        return "standard"

    # MT5ヘッダー付き (タブ区切りでヘッダにDATE等含む)
    lower_first = first_line.lower().replace("<", "").replace(">", "")
    if "\t" in first_line and any(kw in lower_first for kw in ("date", "time", "open")):
        return "mt5"

    # MT5データ行 (タブ区切り、7列以上)
    if "\t" in second_line and len(second_line.split("\t")) >= 7:
        return "mt5"

    # MT4: カンマ区切り、日付が YYYY.MM.DD 形式
    test_line = second_line if second_line else first_line
    if "." in test_line.split(",")[0] if "," in test_line else "":
        parts = test_line.split(",")
        if len(parts) >= 7 and "." in parts[0]:
            return "mt4"

    # フォールバック: カンマ区切りで6-7列ならMT4とみなす
    parts = test_line.split(",")
    if len(parts) in (6, 7) and "." in parts[0]:
        return "mt4"

    return "standard"


def _load_mt4_csv(filepath: str) -> pd.DataFrame:
    """MT4 History Center CSV を読み込み、標準フォーマットに変換"""
    # ヘッダの有無を判定
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        first = f.readline().strip()

    has_header = any(kw in first.lower() for kw in ("date", "open", "high", "close"))

    if has_header:
        df = pd.read_csv(filepath, header=0)
        # MT4ヘッダ形式: <DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>
        df.columns = [c.strip().lower().replace("<", "").replace(">", "") for c in df.columns]
        if "vol" in df.columns:
            df = df.rename(columns={"vol": "volume"})
        if "tickvol" in df.columns:
            df = df.rename(columns={"tickvol": "volume"})
    else:
        cols = ["date", "time", "open", "high", "low", "close", "volume"]
        df = pd.read_csv(filepath, header=None, names=cols[:min(7, len(first.split(",")))])

    # timestamp列を作成
    if "date" in df.columns and "time" in df.columns:
        df["timestamp"] = pd.to_datetime(
            df["date"].astype(str) + " " + df["time"].astype(str),
            format="mixed", dayfirst=False
        )
        df = df.drop(columns=["date", "time"], errors="ignore")
    elif "date" in df.columns:
        df["timestamp"] = pd.to_datetime(df["date"], format="mixed")
        df = df.drop(columns=["date"], errors="ignore")

    if "volume" not in df.columns:
        df["volume"] = 0

    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def _load_mt5_csv(filepath: str) -> pd.DataFrame:
    """MT5 エクスポート CSV (タブ区切り) を読み込み、標準フォーマットに変換"""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        first = f.readline().strip()

    has_header = any(kw in first.lower().replace("<", "").replace(">", "") for kw in ("date", "open"))

    if has_header:
        df = pd.read_csv(filepath, sep="\t", header=0)
        df.columns = [c.strip().lower().replace("<", "").replace(">", "") for c in df.columns]
    else:
        # MT5: date time open high low close tick_volume real_volume spread
        n_cols = len(first.split("\t"))
        if n_cols >= 9:
            cols = ["date", "time", "open", "high", "low", "close", "tick_volume", "real_volume", "spread"]
        elif n_cols >= 7:
            cols = ["date", "time", "open", "high", "low", "close", "volume"]
        else:
            cols = ["date", "time", "open", "high", "low", "close"]
        df = pd.read_csv(filepath, sep="\t", header=None, names=cols[:n_cols])

    # volume列の処理
    if "tick_volume" in df.columns:
        df = df.rename(columns={"tick_volume": "volume"})
    elif "tickvol" in df.columns:
        df = df.rename(columns={"tickvol": "volume"})
    if "volume" not in df.columns:
        df["volume"] = 0

    # timestamp列を作成
    if "date" in df.columns and "time" in df.columns:
        df["timestamp"] = pd.to_datetime(
            df["date"].astype(str) + " " + df["time"].astype(str),
            format="mixed", dayfirst=False
        )
        df = df.drop(columns=["date", "time"], errors="ignore")

    keep = ["timestamp", "open", "high", "low", "close", "volume"]
    return df[[c for c in keep if c in df.columns]]


# ================================================================
# 標準ローダー
# ================================================================

def load_ohlc(filepath: str) -> pd.DataFrame:
    """CSV形式のOHLCデータを読み込む。MT4/MT5形式も自動検出して変換。"""
    fmt = _detect_format(filepath)
    logger.debug(f"データ形式検出: {fmt} ({os.path.basename(filepath)})")

    if fmt == "mt4":
        df = _load_mt4_csv(filepath)
    elif fmt == "mt5":
        df = _load_mt5_csv(filepath)
    else:
        df = pd.read_csv(filepath)
        required = {"timestamp", "open", "high", "low", "close"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"必須カラムが不足: {missing}")

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(int)
    else:
        df["volume"] = 0

    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)

    return df


def convert_mt_csv(input_path: str, output_path: str) -> str:
    """MT4/MT5 CSV を標準フォーマットに変換して保存"""
    df = load_ohlc(input_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_csv(output_path, index=False)
    logger.info(f"変換完了: {input_path} -> {output_path} ({len(df)} 行)")
    return output_path


def batch_convert_mt_csv(input_dir: str, output_dir: str) -> list[str]:
    """ディレクトリ内のMT4/MT5 CSVを一括変換"""
    converted = []
    for filepath in sorted(glob.glob(os.path.join(input_dir, "*.csv"))):
        filename = os.path.basename(filepath)
        out_path = os.path.join(output_dir, filename)
        try:
            convert_mt_csv(filepath, out_path)
            converted.append(out_path)
        except Exception as e:
            logger.error(f"変換失敗: {filename}: {e}")
    return converted


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
