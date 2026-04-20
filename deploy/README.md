# VPS デプロイガイド

NY リージョン VPS で本番稼働させる手順。所要時間 ~30 分。

## 前提

- Ubuntu 22.04 LTS(他の Linux でも可)
- Python 3.11+
- `systemd`(Ubuntu は標準搭載)
- (推奨)Polygon RPC を自前で用意:
  - Alchemy: https://www.alchemy.com/ (Growth プラン $49/月、レイテンシが段違い)
  - 無料でもパブリック RPC より速い(Free Tier あり)

## 手順(systemd + venv)

```bash
# 1. ユーザー作成
sudo adduser --system --group --home /opt/polymarket-bot bot

# 2. コード配置
sudo -u bot git clone <your-fork-url> /opt/polymarket-bot
cd /opt/polymarket-bot

# 3. venv と依存
sudo -u bot python3.11 -m venv .venv
sudo -u bot ./.venv/bin/pip install -r requirements.txt

# 4. .env 設定(秘密鍵は絶対ローカルでしか入れない)
sudo -u bot cp .env.example .env
sudo -u bot nano .env
# POLYMARKET_PRIVATE_KEY, POLYMARKET_FUNDER_ADDRESS, POLYGON_RPC を設定
# BOT_DRY_RUN=true のままでまず試す

# 5. ヘルスチェック
sudo -u bot ./.venv/bin/python -m src.healthcheck

# 6. ログディレクトリ
sudo mkdir -p /var/log/polymarket-bot
sudo chown bot:bot /var/log/polymarket-bot

# 7. systemd サービス登録
sudo cp deploy/polymarket-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable polymarket-bot
sudo systemctl start polymarket-bot

# 8. 動作確認
sudo systemctl status polymarket-bot
sudo journalctl -u polymarket-bot -f    # ライブログ
curl http://localhost:9100/metrics        # Prometheus メトリクス
tail -f /opt/polymarket-bot/trades.jsonl  # 取引ログ
```

## Docker 版

```bash
docker build -t polymarket-bot .
docker run -d --name pm-bot \
  --env-file .env \
  -p 9100:9100 \
  -v $(pwd)/trades.jsonl:/app/trades.jsonl \
  --restart unless-stopped \
  polymarket-bot
```

## 稼働後の運用

| タスク | 頻度 | コマンド |
|---|---|---|
| ログ確認 | 毎日 | `sudo journalctl -u polymarket-bot --since today` |
| PnL 集計 | 毎日 | `python -m src.backtest trades.jsonl --bankroll 500` |
| Claude 健全性レビュー | 毎日 | `python -m src.analyze trades.jsonl` |
| メトリクス確認 | 随時 | `curl localhost:9100/metrics` |
| コード更新 | 必要時 | `git pull && sudo systemctl restart polymarket-bot` |

## 本番に上げる前のチェックリスト

- [ ] `python -m src.healthcheck` 全 ✓
- [ ] ドライランで数日稼働、`trades.jsonl` に妥当な数のエントリ
- [ ] `python -m src.backtest` で月利プロジェクションが期待値
- [ ] `BOT_MAX_POSITION_USD` を最小 ($5-$10) に設定
- [ ] `BOT_DRY_RUN=false` に変更
- [ ] `systemctl restart polymarket-bot`
- [ ] 最初の 1 約定を Polymarket UI で目視確認
- [ ] Prometheus メトリクスを Grafana などで可視化(任意)

## トラブルシュート

| 症状 | 対処 |
|---|---|
| WS が切れ続ける | `POLYGON_RPC` を Alchemy 等に切替、VPS のネットワーク確認 |
| rejected_depth が多い | `market_filter.py` の `min_liquidity` を上げる |
| rejected_real_edge が多い | `BOT_MIN_EDGE` を下げる(0.002〜0.003)、または諦める(レース負け) |
| 損失が膨らむ | `risk.py` の `max_daily_loss_usd` 引き下げ、即 `systemctl stop` |

## レイテンシ測定

```bash
# トレーディングループの平均レイテンシ
curl -s localhost:9100/metrics | grep trading_tick_ms
```

- WS + NY VPS + Alchemy: 15〜50ms が目安
- REST ポーリング + パブリック RPC: 500ms+
- 100ms 超えたら何かがおかしい
