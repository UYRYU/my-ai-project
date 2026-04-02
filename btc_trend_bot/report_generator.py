"""Report generator for BTC Trend Long Bot.

Produces equity curve PNGs, trade logs, metrics CSVs, regime breakdowns,
strategy rankings, top-trade analyses, and a Japanese-language summary
Markdown for the best strategy.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from loguru import logger


class ReportGenerator:
    """Generate reports from backtest results.

    Parameters
    ----------
    output_dir : str
        Directory where all report artefacts are written.  Created
        automatically if it does not exist.
    """

    def __init__(self, output_dir: str = "reports") -> None:
        self.output_dir: Path = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info("ReportGenerator initialised: output_dir={}", self.output_dir)

    # ------------------------------------------------------------------
    # Full report
    # ------------------------------------------------------------------

    def generate_full_report(self, results: dict, strategy_name: str) -> None:
        """Generate all report artefacts for a single strategy result.

        Parameters
        ----------
        results : dict
            Must contain keys ``equity_curve`` (:class:`pd.Series`),
            ``trades`` (:class:`pd.DataFrame`), ``metrics`` (dict), and
            optionally ``regime_metrics`` (dict).
        strategy_name : str
            Human-readable strategy name used in file names.
        """
        logger.info("Generating full report for strategy '{}'", strategy_name)

        equity: pd.Series = results.get("equity_curve", pd.Series(dtype=float))
        trades: pd.DataFrame = results.get("trades", pd.DataFrame())
        metrics: dict = results.get("metrics", {})
        regime_metrics: dict = results.get("regime_metrics", {})

        self.save_equity_curve(equity, strategy_name)
        self.save_trade_log(trades, strategy_name)
        self.save_metrics_csv(metrics, strategy_name)

        if regime_metrics:
            self.save_regime_metrics(regime_metrics, strategy_name)

        if not trades.empty:
            self.save_top_trades_analysis(trades, strategy_name)

        logger.info("Full report complete for '{}'", strategy_name)

    # ------------------------------------------------------------------
    # Equity curve
    # ------------------------------------------------------------------

    def save_equity_curve(self, equity: pd.Series, name: str) -> Path:
        """Save an equity-curve PNG with drawdown shading.

        Parameters
        ----------
        equity : pd.Series
            Equity curve indexed by datetime.
        name : str
            Strategy name (used in the filename and title).

        Returns
        -------
        Path
            Path to the saved PNG file.
        """
        out_path = self.output_dir / f"{name}_equity.png"

        if equity.empty:
            logger.warning("Empty equity curve for '{}'; skipping PNG", name)
            return out_path

        fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True,
                                 gridspec_kw={"height_ratios": [3, 1]})

        # --- Upper panel: equity line ---
        ax_eq = axes[0]
        ax_eq.plot(equity.index, equity.values, linewidth=1.2, color="#1f77b4",
                   label="Equity")
        ax_eq.set_title(f"Equity Curve - {name}", fontsize=14)
        ax_eq.set_ylabel("Portfolio Value")
        ax_eq.legend(loc="upper left")
        ax_eq.grid(True, alpha=0.3)

        # Mark drawdown periods (equity below running max)
        running_max = equity.cummax()
        in_drawdown = equity < running_max
        if in_drawdown.any():
            ax_eq.fill_between(
                equity.index,
                equity.values,
                running_max.values,
                where=in_drawdown.values,
                alpha=0.25,
                color="red",
                label="Drawdown",
            )
            ax_eq.legend(loc="upper left")

        # --- Lower panel: drawdown percentage ---
        ax_dd = axes[1]
        dd_pct = (running_max - equity) / running_max * 100.0
        dd_pct = dd_pct.replace([np.inf, -np.inf], 0.0).fillna(0.0)
        ax_dd.fill_between(equity.index, 0, dd_pct.values, color="red", alpha=0.4)
        ax_dd.set_ylabel("Drawdown %")
        ax_dd.set_xlabel("Date")
        ax_dd.grid(True, alpha=0.3)
        ax_dd.invert_yaxis()

        # Date formatting
        for ax in axes:
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())

        fig.tight_layout()
        fig.savefig(str(out_path), dpi=150)
        plt.close(fig)

        logger.info("Saved equity curve: {}", out_path)
        return out_path

    # ------------------------------------------------------------------
    # Trade log
    # ------------------------------------------------------------------

    def save_trade_log(self, trades: pd.DataFrame, name: str) -> Path:
        """Save the trade history as a CSV file.

        Parameters
        ----------
        trades : pd.DataFrame
            Trade log DataFrame.
        name : str
            Strategy name.

        Returns
        -------
        Path
            Path to the saved CSV.
        """
        out_path = self.output_dir / f"{name}_trades.csv"
        trades.to_csv(str(out_path), index=False)
        logger.info("Saved trade log ({} trades): {}", len(trades), out_path)
        return out_path

    # ------------------------------------------------------------------
    # Metrics CSV
    # ------------------------------------------------------------------

    def save_metrics_csv(self, metrics: dict, name: str) -> Path:
        """Save metrics dictionary as a two-column CSV (metric, value).

        Parameters
        ----------
        metrics : dict
            Key-value pairs of performance metrics.
        name : str
            Strategy name.

        Returns
        -------
        Path
            Path to the saved CSV.
        """
        out_path = self.output_dir / f"{name}_metrics.csv"
        df = pd.DataFrame(
            list(metrics.items()), columns=["metric", "value"]
        )
        df.to_csv(str(out_path), index=False)
        logger.info("Saved metrics CSV: {}", out_path)
        return out_path

    # ------------------------------------------------------------------
    # Regime metrics
    # ------------------------------------------------------------------

    def save_regime_metrics(self, regime_metrics: dict, name: str) -> Path:
        """Save per-regime metrics as a CSV.

        Parameters
        ----------
        regime_metrics : dict
            ``{regime_name: metrics_dict}`` as returned by
            :func:`calc_regime_metrics`.
        name : str
            Strategy name.

        Returns
        -------
        Path
            Path to the saved CSV.
        """
        out_path = self.output_dir / f"{name}_regime_metrics.csv"

        rows: list[dict[str, Any]] = []
        for regime, metrics in regime_metrics.items():
            row: dict[str, Any] = {"regime": regime}
            row.update(metrics)
            rows.append(row)

        df = pd.DataFrame(rows)
        df.to_csv(str(out_path), index=False)
        logger.info("Saved regime metrics ({}): {}", list(regime_metrics.keys()), out_path)
        return out_path

    # ------------------------------------------------------------------
    # Strategy ranking
    # ------------------------------------------------------------------

    def save_ranking(self, results_list: list[dict]) -> Path:
        """Save a strategy ranking CSV sorted by Calmar ratio (descending).

        Parameters
        ----------
        results_list : list[dict]
            Each dict must contain ``strategy_name`` (str) and ``metrics``
            (dict with standard metric keys).

        Returns
        -------
        Path
            Path to the saved CSV.
        """
        out_path = self.output_dir / "strategy_ranking.csv"

        rows: list[dict[str, Any]] = []
        for result in results_list:
            strategy_name = result.get("strategy_name", "unknown")
            metrics = result.get("metrics", {})
            rows.append({
                "strategy_name": strategy_name,
                "total_profit": metrics.get("total_profit", 0.0),
                "profit_factor": metrics.get("profit_factor", 0.0),
                "calmar_ratio": metrics.get("calmar_ratio", 0.0),
                "win_rate": metrics.get("win_rate", 0.0),
                "max_dd": metrics.get("max_drawdown_pct", 0.0),
                "expectancy": metrics.get("expectancy", 0.0),
                "avg_rr": metrics.get("avg_win_loss_ratio", 0.0),
                "high_tp_rate": metrics.get("high_tp_rate_3rr", 0.0),
            })

        df = pd.DataFrame(rows)
        df = df.sort_values("calmar_ratio", ascending=False).reset_index(drop=True)
        df.to_csv(str(out_path), index=False)
        logger.info("Saved strategy ranking ({} strategies): {}", len(df), out_path)
        return out_path

    # ------------------------------------------------------------------
    # Top trades analysis
    # ------------------------------------------------------------------

    def save_top_trades_analysis(self, trades: pd.DataFrame, name: str) -> Path:
        """Save the top 10 best and worst trades with analysis.

        Parameters
        ----------
        trades : pd.DataFrame
            Trade log DataFrame.
        name : str
            Strategy name.

        Returns
        -------
        Path
            Path to the saved CSV.
        """
        out_path = self.output_dir / f"{name}_top_trades.csv"

        if trades.empty:
            pd.DataFrame().to_csv(str(out_path), index=False)
            logger.warning("Empty trades for '{}'; saved empty top-trades file", name)
            return out_path

        sorted_trades = trades.sort_values("pnl", ascending=False)
        top_wins = sorted_trades.head(10).copy()
        top_wins["category"] = "top_win"

        top_losses = sorted_trades.tail(10).copy()
        top_losses["category"] = "top_loss"

        combined = pd.concat([top_wins, top_losses], ignore_index=True)

        # Add derived analysis columns
        if "entry_price" in combined.columns and "stop_loss" in combined.columns:
            risk = (combined["entry_price"] - combined["stop_loss"]).abs()
            combined["risk_per_unit"] = risk
            safe_risk = risk.replace(0, np.nan)
            combined["realised_rr"] = combined["pnl_pct"] / (
                safe_risk / combined["entry_price"] * 100
            )

        if "entry_time" in combined.columns and "exit_time" in combined.columns:
            combined["holding_hours"] = (
                pd.to_datetime(combined["exit_time"])
                - pd.to_datetime(combined["entry_time"])
            ).dt.total_seconds() / 3600.0

        combined.to_csv(str(out_path), index=False)
        logger.info("Saved top trades analysis: {}", out_path)
        return out_path

    # ------------------------------------------------------------------
    # Japanese summary Markdown
    # ------------------------------------------------------------------

    def generate_summary_md(
        self,
        best_result: dict,
        all_results: list[dict],
    ) -> Path:
        """Generate a Japanese-language Markdown summary of the best strategy.

        Parameters
        ----------
        best_result : dict
            The result dict for the best-performing strategy.  Expected
            keys: ``strategy_name``, ``metrics``, ``regime_metrics``,
            ``best_params``.
        all_results : list[dict]
            All strategy results for comparative context.

        Returns
        -------
        Path
            Path to the saved Markdown file.
        """
        out_path = self.output_dir / "ベスト戦略要約.md"

        strategy_name = best_result.get("strategy_name", "不明")
        metrics = best_result.get("metrics", {})
        regime_metrics = best_result.get("regime_metrics", {})
        best_params = best_result.get("best_params", {})

        # ---- Build Markdown content ----
        lines: list[str] = []

        lines.append(f"# ベスト戦略要約: {strategy_name}")
        lines.append("")
        lines.append(f"生成日時: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

        # --- Performance overview ---
        lines.append("## パフォーマンス概要")
        lines.append("")
        lines.append(f"| 指標 | 値 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 総利益 | {metrics.get('total_profit', 0):.2f} |")
        lines.append(f"| プロフィットファクター | {metrics.get('profit_factor', 0):.2f} |")
        lines.append(f"| カルマーレシオ | {metrics.get('calmar_ratio', 0):.2f} |")
        lines.append(f"| 勝率 | {metrics.get('win_rate', 0):.2%} |")
        lines.append(f"| 最大ドローダウン | {metrics.get('max_drawdown_pct', 0):.2%} |")
        lines.append(f"| 期待値 | {metrics.get('expectancy', 0):.2f} |")
        lines.append(f"| 平均RR比 | {metrics.get('avg_win_loss_ratio', 0):.2f} |")
        lines.append(f"| 高TP率 (3RR超) | {metrics.get('high_tp_rate_3rr', 0):.2%} |")
        lines.append(f"| 総トレード数 | {metrics.get('total_trades', 0)} |")
        lines.append(f"| 平均保有時間 | {metrics.get('avg_holding_time_hours', 0):.1f} 時間 |")
        lines.append("")

        # --- Best parameters ---
        if best_params:
            lines.append("## 最適化パラメータ")
            lines.append("")
            lines.append("| パラメータ | 値 |")
            lines.append("|------------|-----|")
            for param_name, param_value in best_params.items():
                if isinstance(param_value, float):
                    lines.append(f"| {param_name} | {param_value:.4f} |")
                else:
                    lines.append(f"| {param_name} | {param_value} |")
            lines.append("")

        # --- Why this strategy is strong in uptrends ---
        lines.append("## 上昇トレンドでの強み")
        lines.append("")
        win_rate = metrics.get("win_rate", 0)
        pf = metrics.get("profit_factor", 0)
        avg_rr = metrics.get("avg_win_loss_ratio", 0)
        high_tp = metrics.get("high_tp_rate_3rr", 0)

        lines.append(
            f"- 勝率 {win_rate:.1%} とプロフィットファクター {pf:.2f} の組み合わせにより、"
            f"上昇トレンドにおいて安定した収益を実現しています。"
        )
        if avg_rr > 1.5:
            lines.append(
                f"- 平均リスクリワード比が {avg_rr:.2f} と高く、少ない勝ちトレードでも"
                f"大きな利益を確保できる構造になっています。"
            )
        if high_tp > 0.1:
            lines.append(
                f"- トレードの {high_tp:.1%} が3RR以上の高利益を達成しており、"
                f"トレンドの大きな動きを捉える能力が高いことを示しています。"
            )
        lines.append("")

        # --- Regime-specific performance ---
        lines.append("## マーケットレジーム別パフォーマンス")
        lines.append("")
        if regime_metrics:
            for regime, r_metrics in regime_metrics.items():
                regime_jp = {"bull": "上昇相場", "bear": "下落相場", "sideways": "レンジ相場"}.get(
                    regime, regime
                )
                r_trades = r_metrics.get("total_trades", 0)
                r_profit = r_metrics.get("total_profit", 0)
                r_win = r_metrics.get("win_rate", 0)
                r_pf = r_metrics.get("profit_factor", 0)
                lines.append(f"### {regime_jp} ({regime})")
                lines.append("")
                lines.append(f"- トレード数: {r_trades}")
                lines.append(f"- 総利益: {r_profit:.2f}")
                lines.append(f"- 勝率: {r_win:.2%}")
                lines.append(f"- プロフィットファクター: {r_pf:.2f}")
                lines.append("")

            # Identify strong/weak regimes
            regime_profits = {r: m.get("total_profit", 0) for r, m in regime_metrics.items()}
            if regime_profits:
                best_regime = max(regime_profits, key=regime_profits.get)  # type: ignore[arg-type]
                worst_regime = min(regime_profits, key=regime_profits.get)  # type: ignore[arg-type]
                best_jp = {"bull": "上昇相場", "bear": "下落相場", "sideways": "レンジ相場"}.get(
                    best_regime, best_regime
                )
                worst_jp = {"bull": "上昇相場", "bear": "下落相場", "sideways": "レンジ相場"}.get(
                    worst_regime, worst_regime
                )
                lines.append(
                    f"**最も得意なレジーム**: {best_jp} (利益: {regime_profits[best_regime]:.2f})"
                )
                lines.append(
                    f"**最も苦手なレジーム**: {worst_jp} (利益: {regime_profits[worst_regime]:.2f})"
                )
                lines.append("")
        else:
            lines.append("レジーム別データなし。")
            lines.append("")

        # --- How it achieves high TP ---
        lines.append("## 高TP達成の仕組み")
        lines.append("")
        lines.append(
            "- トレンド方向への順張りエントリーにより、大きな値動きを捉える確率を最大化しています。"
        )
        lines.append(
            "- ATRトレーリングストップやパーシャルテイクプロフィットを活用し、"
            "利益を伸ばしつつリスクを管理しています。"
        )
        lines.append(
            "- エントリー条件にトレンド強度フィルターを組み合わせることで、"
            "トレンドが強い局面でのみポジションを取ります。"
        )
        lines.append("")

        # --- Operational notes ---
        lines.append("## ライブトレード運用上の注意事項")
        lines.append("")
        lines.append("1. **スリッページ**: バックテストではスリッページを考慮していますが、"
                      "ライブ環境では流動性によりさらに大きくなる可能性があります。")
        lines.append("2. **約定遅延**: シグナル発生からエントリーまでのレイテンシを最小限に抑えてください。")
        lines.append("3. **ポジションサイジング**: 資金の95%を1トレードに投入するバックテスト設定は"
                      "ライブでは推奨しません。最大でも50%程度に抑えてください。")
        lines.append("4. **レジーム確認**: エントリー前にトレンドレジームが上昇相場であることを必ず確認してください。")
        lines.append("5. **ドローダウン管理**: 最大ドローダウンがバックテスト値を超えた場合、"
                      "一時的にシステムを停止し、パラメータの再最適化を検討してください。")
        lines.append("")

        # --- False signal avoidance ---
        lines.append("## ダマシ回避条件")
        lines.append("")
        lines.append("- レンジ相場や下落相場でのエントリーシグナルは無視してください。")
        lines.append("- ADXが20未満の場合はトレンドが弱いため、エントリーを見送ります。")
        lines.append("- 出来高がSMA20を下回っている場合は、ブレイクアウトの信頼性が低いため注意してください。")
        lines.append("- RSIが70以上の過熱状態では、新規エントリーを避けてください。")
        lines.append("- 過伸展(overextended)フラグが立っている場合はエントリーを控えてください。")
        lines.append("")

        # --- Live implementation roadmap ---
        lines.append("## ライブ実装ロードマップ")
        lines.append("")
        lines.append("### フェーズ1: ペーパートレード (2-4週間)")
        lines.append("- バックテスト結果の再現性を確認")
        lines.append("- シグナル発生タイミングとAPI約定タイミングの差異を計測")
        lines.append("- ログ基盤の構築とアラート設定")
        lines.append("")
        lines.append("### フェーズ2: 小ロット実運用 (1-2ヶ月)")
        lines.append("- 資金の10-20%で実運用開始")
        lines.append("- スリッページ実測値の収集")
        lines.append("- ドローダウン監視ダッシュボードの構築")
        lines.append("")
        lines.append("### フェーズ3: フルスケール運用")
        lines.append("- パフォーマンスが安定していれば資金比率を段階的に引き上げ")
        lines.append("- ウォークフォワード最適化を定期的(月次)に実施")
        lines.append("- マーケットレジーム変化時の自動パラメータ切替を検討")
        lines.append("")

        # --- Strategy comparison ---
        if len(all_results) > 1:
            lines.append("## 他戦略との比較")
            lines.append("")
            lines.append("| 戦略名 | 総利益 | カルマーレシオ | 勝率 | PF |")
            lines.append("|--------|--------|----------------|------|-----|")
            sorted_results = sorted(
                all_results,
                key=lambda r: r.get("metrics", {}).get("calmar_ratio", 0),
                reverse=True,
            )
            for res in sorted_results:
                r_name = res.get("strategy_name", "不明")
                r_m = res.get("metrics", {})
                lines.append(
                    f"| {r_name} "
                    f"| {r_m.get('total_profit', 0):.2f} "
                    f"| {r_m.get('calmar_ratio', 0):.2f} "
                    f"| {r_m.get('win_rate', 0):.2%} "
                    f"| {r_m.get('profit_factor', 0):.2f} |"
                )
            lines.append("")

        # Write file
        content = "\n".join(lines)
        out_path.write_text(content, encoding="utf-8")
        logger.info("Saved summary Markdown: {}", out_path)
        return out_path
