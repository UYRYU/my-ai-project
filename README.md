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

## 実行結果サマリー (合成BTC 5m / 180日)

### 全期間グリッド最適化 (Bitget taker手数料込)
ベスト: EMA 34/200, RSI 55/45 非対称, ATR≥1.2×avg, TP=6×ATR, SL=2×ATR
- PF=1.34, ret=+0.32%, DD=-0.27%, win=76.5%, n=132

### ⚠ ウォークフォワード結果 (重大): **過剰最適化を検出**

| Fold | IS PF | OOS PF | OOS ret | OOS n |
|---|---|---|---|---|
| 1 | 1.85 | **0.87** | -0.04% | 34 |
| 2 | 1.55 | **0.74** | -0.10% | 46 |
| 3 | 1.36 | **0.99** | -0.00% | 33 |
| **平均** | 1.59 | **0.87** | -0.05% | |

→ **In-Sample で勝てる設定が Out-of-Sample では負け越す** 典型的な過剰最適化パターン。
3 fold とも fold ごとに最良パラメータが変わっており（EMA 20/200 → 20/200 → 34/50）、
**安定した勝ちパターンは存在しない可能性が高い**。

### 手数料感度分析 (`compare_fees.py`)

| シナリオ | PF | DD | 解釈 |
|---|---|---|---|
| Bitget taker往復 0.12% | 1.34 | -0.27% | エッジが薄い |
| Bitget maker往復 0.04% | **2.89** | -0.11% | 健全 |
| MT5想定 (0.005%) | 3.83 | -0.08% | 強い |
| 手数料ゼロ | 4.11 | -0.07% | 戦略本体は機能している |

### 結論と推奨アクション

1. **このパラメータ/TFをBitget takerでそのまま動かすのは非推奨** (OOS で負け越し)
2. 試すべき改善案:
   - **TF を M15/H1 に上げる**：ATR が大きくなり相対的に手数料が小さくなる
   - **Maker 主体の運用** (リミット注文)：PF 2倍以上の改善が見込める
   - **より長い期間** (1〜2年) で再最適化：合成データではなく `fetch_data.py` で実データを取る
   - **シンボル分散** (BTC/ETH/SOL の3本立てで個別最適化)
3. **MT5 → Bitget の移植時は必ず実機 paper トレードで2週間以上検証** (`docs/bitget_bridge.md`)

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
