# my-ai-project — Crypto Scalper (EMA + RSI + ATR)

XAU_Scalper_EMA_RSI（ゴールド向け好調EA）を**BTC等の仮想通貨**へ移植・最適化するプロジェクト。
MT5 で最適化を回しつつ、実運用は **Bitget** を想定（手数料を厳密にバックテストへ反映）。

## 構成

```
mt5/CryptoScalper_EMA_RSI_ATR.mq5   # MT5 EA本体 (ATR比例化, 24/7前提)
backtest/strategy.py                # 同ロジックの Python 版 (オフライン最適化用)
backtest/fetch_data.py              # Bitget public API から K線取得 (BTCUSDT 等)
backtest/synth_data.py              # 外部API使えない環境向けの合成データ生成
backtest/optimize.py                # グリッド + ウォークフォワード最適化
backtest/compare_fees.py            # 手数料感度分析 (Bitget taker/maker/手数料ゼロ)
results/best.set                    # 最良パラメータ (MT5 .set フォーマット)
results/top10.json                  # 全期間最適化トップ10
results/walkforward.json            # WFA 各fold OOS結果
results/fee_sensitivity.json        # 手数料シナリオ別の成績
```

## ロジック (元EAからの変更点)

| 項目 | 元 (XAU) | クリプト版 |
|---|---|---|
| EMA | 短20 / 長25 | 短20 / 長50 (BTCはノイズ大、長め推奨) |
| TP/SL | 2000pt / 500pt 直値 | **ATR×倍率** (例 TP=ATR×4, SL=ATR×1) |
| トレール | 50pt発動/30pt刻み | TrailStart_ATR / TrailStep_ATR |
| ボラフィルタ | ATR≥100pt 直値 | 直近20本ATR平均との比 (`ATR ≥ avg×倍率`) |
| クールダウン | 連続負け3回 | 同じ + クールダウン分数で時間ベース停止 |
| ロット | 固定0.01 | 固定 or RiskPercent (口座%) で自動算出 |

> **なぜ「ポイント直値」をやめたか**: BTCUSD はブローカーによって 1pt の意味が違う (Exness=$0.01, FXTM=$1, 等)。直値依存だと別ブローカー/別シンボルに移すと実質パラメータがズレる。ATR比例なら「ボラの倍数」という同じ意味を維持できる。

## ワークフロー

### 1. データ取得 (Bitget)
```bash
python3 backtest/fetch_data.py --symbol BTCUSDT --tf 5m --days 365 \
    --out data/btcusdt_5m.csv
```
※ Bitget API がブロックされる環境では合成データで代替:
```bash
python3 backtest/synth_data.py --days 180 --tf 5 --out data/btcusdt_5m_synth.csv
```

### 2. 最適化 (グリッド + ウォークフォワード)
```bash
python3 backtest/optimize.py --csv data/btcusdt_5m.csv --out results --folds 4
```
- 全期間グリッドで `top10.json` と `best.set` を生成
- 4-fold ウォークフォワードで OOS 性能を確認 (過学習チェック)

### 3. 手数料感度分析
```bash
python3 backtest/compare_fees.py --csv data/btcusdt_5m.csv --set results/best.set
```
Bitget taker / Bitget maker / MT5想定 / 手数料ゼロ を比較。

### 4. MT5へ反映
- `mt5/CryptoScalper_EMA_RSI_ATR.mq5` を `MQL5/Experts/` に配置
- MT5 で コンパイル → ストラテジーテスター → `results/best.set` をロード
- ブローカーのスプレッド/手数料を「カスタム」設定で **Bitget相当 (RT 0.12%)** に
- 最適化期間とは別の OOS 期間でフォワードテスト

### 5. 紙トレ → 小ロット
1. MT5 デモ口座で2週間以上稼働
2. Bitget は MT5 と直結しないので、**EAの売買シグナルを Bitget API でミラー実行**するブリッジが必要 (今回未実装)
3. 最初は 0.001 BTC など最小単位で1ヶ月、想定通り動くか実機検証

## 実行結果サマリー (合成BTCデータ)

### 1) M5 + taker (初期実行 / 180日)

- IS best PF 1.34, ret +0.32%, DD -0.27%
- WFA OOS: PF 0.87, 0.74, 0.99 → **avg 0.87**（過剰最適化）

### 2) TF × Fee マトリクス (`run_tf_matrix.py` / 365日)

| 構成 | IS PF | IS ret% | IS n | OOS avg PF | OOS PFs | OOS avg ret% | 結論 |
|---|---|---|---|---|---|---|---|
| **M5 + taker (180d)** | 1.34 | +0.32 | 132 | 0.87 | 0.87/0.74/0.99 | -0.05 | 過剰最適化 |
| M15 + taker | 0.93 | -0.06 | 112 | 0.74 | 1.16/0.63/0.43 | -0.07 | IS でさえ負け |
| **M15 + maker** ⭐ | **2.29** | **+0.70** | **112** | **1.77** | **2.81/1.04/1.46** | **+0.11** | **OOS 全勝** |
| H1 + taker | 0.74 | -0.08 | 35 | 0.43 | 0.50/0.61/0.17 | -0.72 | TFを上げても無理 |
| H1 + maker | 1.69 | +0.12 | 31 | 1.04 | 1.30/1.38/0.45 | +0.37 | OOS 2勝1敗、n少 |

### 3) トレンドフォロー強化版 (`run_trend_mode.py`)

ADX フィルタ / 上位足EMA / Trail-only モードを追加し、M15 maker 上で再最適化:

| 項目 | baseline M15+maker | **trend-mode M15+maker** | 改善 |
|---|---|---|---|
| IS PF | 2.29 | **3.80** | +66% |
| IS ret% | +0.70 | +0.68 | ≈ |
| IS n | 112 | 68 | -39% (選別性UP) |
| IS win% | 69.6 | 76.5 | +6.9pt |
| OOS PF (Fold 1) | 2.81 | **2.97** | +6% |
| OOS PF (Fold 2) | 1.04 | **1.92** | +85% |
| OOS PF (Fold 3) | 1.46 | **1.58** | +8% |
| **OOS avg PF** | **1.77** | **2.16** | **+22%** |

**ADX 30 が決定打**: Top 5 全てに ADX≥30 が含まれる。HTF EMA / trail_only は副次的影響のみ。
取引数は 40% 減るが、勝率と PF が大きく上がり、結果として OOS で安定的にプラス。

### 結論

**勝ちパターン**: **M15 + Bitget Maker + ADX 30 フィルタ** (`results/best_m15_maker_trend.set`)
- 全 3 OOS fold で PF ≥ 1.58（最低 Fold 3）
- IS:OOS 乖離 (3.80 → 2.16) = **強いトレンドフィルタが過剰最適化を抑える**
- 「トレンド相場の到来」仮説と完全整合 — ADX が立った時のみエントリ

**敗北パターン**: **Taker (0.12% RT) は TF 問わず NG**
- M1 / M5 / M15 / H1 すべて OOS PF < 1
- 特に **M1 + taker は IS PF 0.045** （ほぼゼロエッジ）

### 採用パラメータ (M15 maker trend / `results/best_m15_maker_trend.set`)

```
EMA_Fast       = 20     EMA_Slow       = 100
RSI_BuyMin     = 55     RSI_SellMax    = 45     (非対称、強モメンタム要求)
ATR_MinMult    = 1.2    (ボラ十分な時のみ)
TP_ATR_Mult    = 10.0   SL_ATR_Mult    = 1.5    (RR 6.7:1, 大きく取りに行く)
TrailStart_ATR = 1.0    TrailStep_ATR  = 0.5
ADX_Min        = 30.0   ← 新規: トレンド強度フィルタ
HTF_Period     = 0      (使わない方が良かった)
TrailOnly      = false  (TP明示の方がわずかに優位)
FeePercentRT   = 0.04   (Maker)
```

### 推奨アクションプラン

1. **`fetch_data.py` で BTCUSDT M15 の 1〜2年実データ取得 → 再最適化**（合成データでの判断は最終結論にできない）
2. **Bitget Maker 主体の運用設計**: リミット注文中心、taker 約定を最小化
3. **MT5 デモ口座で 2 週間以上フォワードテスト**: 上記パラメータを `.set` でロードし検証
4. **小ロット実機 (0.001 BTC) で 1 ヶ月** → バックテスト乖離をログ確認
5. **MT5 → Bitget 執行ブリッジ**: 詳細は `docs/bitget_bridge.md`

**示唆**: ATR×1〜4 程度の小さな利幅ではBitget taker手数料がエッジを完全に削る。
対策案：
1. **Bitget Maker主体の運用** (リミット注文中心、taker回避)
2. **TF を上げる** (M5→M15/H1) → ATR 絶対値が大きくなり相対的に手数料が小さくなる
3. **TP_ATR_Mult を大きく** (4→10 など) して手数料の比率を下げる
4. **VIPランク or BGB ステーキング** で手数料を割引

最適化スクリプトはこの状況下で「最も傷が浅い設定」を探す。
それでも EV が負なら、**この戦略はBitgetでは収益化困難** と結論づけて別アプローチを検討すべき。

## 注意

- バックテストは過去成績の再現にすぎず、将来を保証しない
- **MT5 ↔ Bitget は別市場**。MT5 で得た最適パラメータは「方向性の参考」程度に扱い、
  Bitget 実機で必ず再検証する
- スリッページ・ファンディングレート・部分約定の影響は今のモデルでは簡略化されている
- 本リポジトリ同梱の `data/btcusdt_5m_synth.csv` は **合成データ**。本番運用前に必ず `fetch_data.py` で実データを取得して再最適化すること
