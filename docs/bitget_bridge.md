# MT5 → Bitget ブリッジ設計メモ

MT5 と Bitget は接続できないため、EAのシグナルを Bitget の口座に反映するには
**ブリッジ（仲介プログラム）** が必要。本リポジトリでは未実装だが、選択肢を整理しておく。

## 選択肢

### A. EA がファイル/HTTPで通知 → ブリッジが Bitget API を叩く
- MT5 EA 側で `FileWrite` で JSON を吐く or ローカル HTTP に POST
- Python 側で監視し、Bitget V2 REST/WebSocket に橋渡し
- 利点: 実装が単純、テスト容易
- 欠点: MT5 と Bitget の約定タイミングがズレる (秒単位の遅延)

### B. シグナル生成自体を Python に移して MT5 を捨てる
- `backtest/strategy.py` をライブで動かし、Bitget で直接執行
- MT5 は最適化の検証用に残す
- 利点: 単一データソース、遅延なし、一貫性
- 欠点: MT5 のチャート/可視化メリットを失う

→ **推奨は B**（最適化は MT5 で並列実行する利点があるが、運用一貫性が勝る）

## Bitget API キーの安全な扱い

- 環境変数 `BITGET_API_KEY` / `BITGET_API_SECRET` / `BITGET_PASSPHRASE`
- `.env` を `.gitignore` で除外 (本リポジトリ済)
- IP 制限とポジション最大値を取引所側で設定
- 最初は **テストネット** または **小ロット** で接続検証

## 実装したくなったら

```
bitget_bridge/
  ├─ live_runner.py      # 5秒/1分ごとに足を取ってシグナル判定
  ├─ bitget_client.py    # 注文/ポジ/残高ラッパ (REST + WS)
  ├─ risk_guard.py       # 最大DD / 連続負け / 緊急停止
  └─ logs/               # トレード履歴 + シグナル監査ログ
```

最初に `bitget_client.py` の paper モード（注文を打たずログだけ出す）を作って
1〜2週間ライブ実行 → ログを backtest 結果と突き合わせる。
ここで乖離が大きければ、バックテストモデルを修正してから本番化する。
