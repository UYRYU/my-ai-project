//+------------------------------------------------------------------+
//|                                        XAU_Scalper_EMA_RSI.mq5  |
//|                              1分足 EMA+RSI+ATR 順張りスキャルパー |
//|                                         XAUUSD 対応               |
//+------------------------------------------------------------------+
#property copyright "2024"
#property link      ""
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//=== 入力パラメータ ===================================================

input group "=== トレード設定 ==="
input double   InpLotSize        = 0.01;     // ロットサイズ
input int      InpTakeProfit     = 500;      // テイクプロフィット (points: XAUUSDは0.01単位)
input int      InpStopLoss       = 300;      // ストップロス (points)
input int      InpMaxSpread      = 50;       // 最大スプレッド許容値 (points)

input group "=== インジケーター設定 ==="
input int      InpEmaFast        = 9;        // EMA 速い期間
input int      InpEmaSlow        = 21;       // EMA 遅い期間
input int      InpRsiPeriod      = 14;       // RSI 期間
input double   InpRsiBuyMin      = 50.0;     // RSI 買い最小値 (上昇モメンタム確認)
input double   InpRsiSellMax     = 50.0;     // RSI 売り最大値 (下落モメンタム確認)
input int      InpAtrPeriod      = 14;       // ATR 期間
input double   InpAtrMinPoints   = 100.0;    // ATR 最小閾値 (points, ボラティリティフィルター)

input group "=== トレーリングストップ ==="
input bool     InpTrailingOn     = true;     // トレーリングストップ ON/OFF
input int      InpTrailingStart  = 150;      // トレーリング開始利益距離 (points)
input int      InpTrailingStep   = 80;       // トレーリングステップ (points)

input group "=== リスク管理 ==="
input bool     InpCloseOnSignal  = true;     // 逆シグナルで強制決済
input int      InpMaxConsecLoss  = 3;        // クールダウン発動の連敗数
input int      InpCooldownSec    = 1800;     // クールダウン時間 (秒)

input group "=== システム ==="
input long     InpMagicNumber    = 20240101; // マジックナンバー

//=== グローバル変数 ===================================================

CTrade         g_trade;
CPositionInfo  g_pos;

int            g_hEmaFast   = INVALID_HANDLE;
int            g_hEmaSlow   = INVALID_HANDLE;
int            g_hRsi       = INVALID_HANDLE;
int            g_hAtr       = INVALID_HANDLE;

datetime       g_lastBar    = 0;
int            g_consecLoss = 0;
datetime       g_cooldownUntil = 0;

//+------------------------------------------------------------------+
//| Expert initialization                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   // インジケーターハンドル作成
   g_hEmaFast = iMA(_Symbol, PERIOD_M1, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   g_hEmaSlow = iMA(_Symbol, PERIOD_M1, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
   g_hRsi     = iRSI(_Symbol, PERIOD_M1, InpRsiPeriod, PRICE_CLOSE);
   g_hAtr     = iATR(_Symbol, PERIOD_M1, InpAtrPeriod);

   if(g_hEmaFast == INVALID_HANDLE || g_hEmaSlow == INVALID_HANDLE ||
      g_hRsi     == INVALID_HANDLE || g_hAtr     == INVALID_HANDLE)
   {
      Print("[ERROR] インジケーターハンドル作成失敗");
      return INIT_FAILED;
   }

   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetDeviationInPoints(10);
   g_trade.SetTypeFilling(ORDER_FILLING_IOC);

   PrintFormat("[INIT] %s EA起動 Magic=%I64d TP=%d SL=%d Lot=%.2f",
               _Symbol, InpMagicNumber, InpTakeProfit, InpStopLoss, InpLotSize);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   if(g_hEmaFast != INVALID_HANDLE) IndicatorRelease(g_hEmaFast);
   if(g_hEmaSlow != INVALID_HANDLE) IndicatorRelease(g_hEmaSlow);
   if(g_hRsi     != INVALID_HANDLE) IndicatorRelease(g_hRsi);
   if(g_hAtr     != INVALID_HANDLE) IndicatorRelease(g_hAtr);
   Comment("");
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   // トレーリングストップは毎Tickで更新
   if(InpTrailingOn)
      ManageTrailing();

   // 新バー確定チェック
   datetime curBar = iTime(_Symbol, PERIOD_M1, 0);
   if(curBar == g_lastBar)
      return;
   g_lastBar = curBar;

   // クールダウン中チェック
   if(TimeCurrent() < g_cooldownUntil)
   {
      int remaining = (int)(g_cooldownUntil - TimeCurrent());
      Comment(StringFormat("【クールダウン中】残り %d 秒 (%s まで)",
                           remaining, TimeToString(g_cooldownUntil, TIME_DATE | TIME_MINUTES)));
      return;
   }
   Comment("");

   // スプレッドチェック
   long spreadPoints = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spreadPoints > InpMaxSpread)
   {
      PrintFormat("[SKIP] スプレッド超過: %d > %d", spreadPoints, InpMaxSpread);
      return;
   }

   // インジケーター値取得 (バー1=直前確定足)
   double emaFast[3], emaSlow[3], rsi[3], atr[3];
   ArraySetAsSeries(emaFast, true);
   ArraySetAsSeries(emaSlow, true);
   ArraySetAsSeries(rsi,     true);
   ArraySetAsSeries(atr,     true);

   if(CopyBuffer(g_hEmaFast, 0, 1, 3, emaFast) < 3) return;
   if(CopyBuffer(g_hEmaSlow, 0, 1, 3, emaSlow) < 3) return;
   if(CopyBuffer(g_hRsi,     0, 1, 3, rsi)     < 3) return;
   if(CopyBuffer(g_hAtr,     0, 1, 3, atr)     < 3) return;

   // ATRフィルター: ボラティリティ確認
   double atrPoints = atr[0] / _Point;
   if(atrPoints < InpAtrMinPoints)
      return;

   // シグナル判定 (バー1の値を使用)
   bool emaBull = (emaFast[0] > emaSlow[0]);  // 上昇トレンド
   bool emaBear = (emaFast[0] < emaSlow[0]);  // 下降トレンド
   bool rsiBuy  = (rsi[0] >= InpRsiBuyMin);   // RSI上昇モメンタム
   bool rsiSell = (rsi[0] <= InpRsiSellMax);  // RSI下落モメンタム

   bool buySignal  = emaBull && rsiBuy;
   bool sellSignal = emaBear && rsiSell;

   // ポジション管理
   if(HasPosition())
   {
      if(InpCloseOnSignal)
      {
         ENUM_POSITION_TYPE posType = GetPositionType();
         if(posType == POSITION_TYPE_BUY  && sellSignal) ClosePosition("逆シグナル(売)");
         if(posType == POSITION_TYPE_SELL && buySignal)  ClosePosition("逆シグナル(買)");
      }
   }
   else
   {
      if(buySignal)
      {
         PrintFormat("[SIGNAL] BUY: EMA9=%.3f EMA21=%.3f RSI=%.1f ATR_pts=%.0f",
                     emaFast[0], emaSlow[0], rsi[0], atrPoints);
         OpenBuy();
      }
      else if(sellSignal)
      {
         PrintFormat("[SIGNAL] SELL: EMA9=%.3f EMA21=%.3f RSI=%.1f ATR_pts=%.0f",
                     emaFast[0], emaSlow[0], rsi[0], atrPoints);
         OpenSell();
      }
   }
}

//+------------------------------------------------------------------+
//| 買いエントリー                                                    |
//+------------------------------------------------------------------+
void OpenBuy()
{
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double sl  = NormalizeDouble(ask - InpStopLoss   * _Point, _Digits);
   double tp  = NormalizeDouble(ask + InpTakeProfit * _Point, _Digits);

   if(g_trade.Buy(InpLotSize, _Symbol, ask, sl, tp, "EMA_RSI_BUY"))
      PrintFormat("[OPEN] BUY %.2f @ %.5f SL=%.5f TP=%.5f", InpLotSize, ask, sl, tp);
   else
      PrintFormat("[ERROR] Buy失敗: %d %s", g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
//| 売りエントリー                                                    |
//+------------------------------------------------------------------+
void OpenSell()
{
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double sl  = NormalizeDouble(bid + InpStopLoss   * _Point, _Digits);
   double tp  = NormalizeDouble(bid - InpTakeProfit * _Point, _Digits);

   if(g_trade.Sell(InpLotSize, _Symbol, bid, sl, tp, "EMA_RSI_SELL"))
      PrintFormat("[OPEN] SELL %.2f @ %.5f SL=%.5f TP=%.5f", InpLotSize, bid, sl, tp);
   else
      PrintFormat("[ERROR] Sell失敗: %d %s", g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
//| ポジション決済                                                    |
//+------------------------------------------------------------------+
void ClosePosition(const string reason)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!g_pos.SelectByIndex(i)) continue;
      if(g_pos.Symbol() != _Symbol || g_pos.Magic() != InpMagicNumber) continue;

      ulong ticket = g_pos.Ticket();
      if(g_trade.PositionClose(ticket))
         PrintFormat("[CLOSE] %s Ticket=%I64u", reason, ticket);
      else
         PrintFormat("[ERROR] 決済失敗: %d %s", g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
      return;
   }
}

//+------------------------------------------------------------------+
//| 自EA管理ポジションの有無                                          |
//+------------------------------------------------------------------+
bool HasPosition()
{
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(!g_pos.SelectByIndex(i)) continue;
      if(g_pos.Symbol() == _Symbol && g_pos.Magic() == InpMagicNumber)
         return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| ポジションタイプ取得                                              |
//+------------------------------------------------------------------+
ENUM_POSITION_TYPE GetPositionType()
{
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(!g_pos.SelectByIndex(i)) continue;
      if(g_pos.Symbol() == _Symbol && g_pos.Magic() == InpMagicNumber)
         return g_pos.PositionType();
   }
   return (ENUM_POSITION_TYPE)-1;
}

//+------------------------------------------------------------------+
//| トレーリングストップ管理 (毎Tick呼び出し)                         |
//+------------------------------------------------------------------+
void ManageTrailing()
{
   for(int i = 0; i < PositionsTotal(); i++)
   {
      if(!g_pos.SelectByIndex(i)) continue;
      if(g_pos.Symbol() != _Symbol || g_pos.Magic() != InpMagicNumber) continue;

      ulong  ticket    = g_pos.Ticket();
      double openPrice = g_pos.PriceOpen();
      double curSL     = g_pos.StopLoss();
      double curTP     = g_pos.TakeProfit();

      if(g_pos.PositionType() == POSITION_TYPE_BUY)
      {
         double bid         = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         double profitPts   = (bid - openPrice) / _Point;

         if(profitPts >= InpTrailingStart)
         {
            double newSL = NormalizeDouble(bid - InpTrailingStep * _Point, _Digits);
            if(newSL > curSL + _Point)
               g_trade.PositionModify(ticket, newSL, curTP);
         }
      }
      else if(g_pos.PositionType() == POSITION_TYPE_SELL)
      {
         double ask       = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         double profitPts = (openPrice - ask) / _Point;

         if(profitPts >= InpTrailingStart)
         {
            double newSL = NormalizeDouble(ask + InpTrailingStep * _Point, _Digits);
            if(curSL == 0.0 || newSL < curSL - _Point)
               g_trade.PositionModify(ticket, newSL, curTP);
         }
      }
   }
}

//+------------------------------------------------------------------+
//| 取引完了イベント: 連敗管理・クールダウン                          |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest     &request,
                        const MqlTradeResult      &result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD)
      return;

   ulong dealTicket = trans.deal;

   // 直近履歴を取得してDEALを検索
   if(!HistoryDealSelect(dealTicket))
   {
      HistorySelect(TimeCurrent() - 86400, TimeCurrent());
      if(!HistoryDealSelect(dealTicket))
         return;
   }

   long   dealMagic  = HistoryDealGetInteger(dealTicket, DEAL_MAGIC);
   long   dealEntry  = HistoryDealGetInteger(dealTicket, DEAL_ENTRY);
   double dealProfit = HistoryDealGetDouble(dealTicket,  DEAL_PROFIT);

   // 自EA の決済ディールのみ対象
   if(dealMagic != InpMagicNumber) return;
   if(dealEntry != DEAL_ENTRY_OUT) return;

   if(dealProfit < 0.0)
   {
      g_consecLoss++;
      PrintFormat("[LOSS] 連敗カウント: %d / %d (損失=%.2f)", g_consecLoss, InpMaxConsecLoss, dealProfit);

      if(g_consecLoss >= InpMaxConsecLoss)
      {
         g_cooldownUntil = TimeCurrent() + InpCooldownSec;
         g_consecLoss    = 0;
         PrintFormat("[COOLDOWN] 開始 → %s まで待機", TimeToString(g_cooldownUntil, TIME_DATE | TIME_MINUTES));
      }
   }
   else
   {
      if(g_consecLoss > 0)
         PrintFormat("[WIN] 連敗リセット (利益=%.2f)", dealProfit);
      g_consecLoss = 0;
   }
}

//+------------------------------------------------------------------+
