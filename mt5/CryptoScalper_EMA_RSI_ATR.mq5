//+------------------------------------------------------------------+
//|                              CryptoScalper_EMA_RSI_ATR.mq5      |
//|  XAU_Scalper_EMA_RSI のクリプト対応版                            |
//|  - TP/SL/Trailing を ATR 比例化（ポイント直値依存を排除）        |
//|  - 24/7運用前提のセッションフィルタ                             |
//|  - Bitget 相当の手数料を Slippage パラメータで吸収               |
//+------------------------------------------------------------------+
#property copyright "my-ai-project"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

CTrade        trade;
CPositionInfo position;

//--- Inputs: indicators
input int      EMA_Fast        = 20;     // EMA 短期
input int      EMA_Slow        = 50;     // EMA 長期 (BTC は 25 より長めが安定)
input int      RSI_Period      = 14;
input double   RSI_BuyMin      = 50.0;   // 買いモメンタム閾値
input double   RSI_SellMax     = 50.0;   // 売りモメンタム閾値
input int      ATR_Period      = 14;
input double   ATR_MinMult     = 1.0;    // ATR が直近平均の何倍以上で許可

//--- Inputs: exits (ATR-proportional)
input double   TP_ATR_Mult     = 4.0;    // TP = ATR × この倍率
input double   SL_ATR_Mult     = 1.0;    // SL = ATR × この倍率 (RR 4:1)
input double   TrailStart_ATR  = 0.5;    // 含み益が ATR×これを超えたら発動
input double   TrailStep_ATR   = 0.3;    // ATR×これ刻みで追従
input bool     CloseOnSignal   = true;   // 逆シグナルで早期決済

//--- Inputs: risk / sizing
input double   RiskPercent     = 0.5;    // 1トレードのリスク% (0なら固定ロット)
input double   FixedLot        = 0.01;
input int      MaxConsecLoss   = 3;
input int      CooldownMinutes = 60;     // クールダウン時間

//--- Inputs: execution
input int      MagicNumber     = 20260426;
input int      SlippagePoints  = 30;
input double   FeePercentRT    = 0.12;   // Bitget 想定の往復手数料% (記録用)

//--- handles
int hEMAfast=INVALID_HANDLE, hEMAslow=INVALID_HANDLE;
int hRSI=INVALID_HANDLE, hATR=INVALID_HANDLE;

//--- state
int      consecLosses = 0;
datetime cooldownUntil = 0;
datetime lastBarTime  = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(SlippagePoints);

   hEMAfast = iMA(_Symbol, _Period, EMA_Fast, 0, MODE_EMA, PRICE_CLOSE);
   hEMAslow = iMA(_Symbol, _Period, EMA_Slow, 0, MODE_EMA, PRICE_CLOSE);
   hRSI     = iRSI(_Symbol, _Period, RSI_Period, PRICE_CLOSE);
   hATR     = iATR(_Symbol, _Period, ATR_Period);

   if(hEMAfast==INVALID_HANDLE || hEMAslow==INVALID_HANDLE ||
      hRSI==INVALID_HANDLE || hATR==INVALID_HANDLE)
   {
      Print("Indicator init failed");
      return INIT_FAILED;
   }
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   if(hEMAfast!=INVALID_HANDLE) IndicatorRelease(hEMAfast);
   if(hEMAslow!=INVALID_HANDLE) IndicatorRelease(hEMAslow);
   if(hRSI    !=INVALID_HANDLE) IndicatorRelease(hRSI);
   if(hATR    !=INVALID_HANDLE) IndicatorRelease(hATR);
}

//+------------------------------------------------------------------+
bool GetBuf(int handle, int shift, double &out)
{
   double b[];
   if(CopyBuffer(handle, 0, shift, 1, b) <= 0) return false;
   out = b[0];
   return true;
}

bool HasPosition(ENUM_POSITION_TYPE type=-1)
{
   for(int i=PositionsTotal()-1; i>=0; --i)
   {
      if(!position.SelectByIndex(i)) continue;
      if(position.Symbol()!=_Symbol || position.Magic()!=MagicNumber) continue;
      if(type==-1 || position.PositionType()==type) return true;
   }
   return false;
}

double CalcLotByRisk(double slPriceDist)
{
   if(RiskPercent<=0.0 || slPriceDist<=0.0) return FixedLot;
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskMoney = balance * RiskPercent / 100.0;
   double tickVal   = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickVal<=0.0 || tickSize<=0.0) return FixedLot;
   double lossPerLot = (slPriceDist / tickSize) * tickVal;
   if(lossPerLot<=0.0) return FixedLot;
   double lot = riskMoney / lossPerLot;
   double minL = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxL = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   lot = MathMax(minL, MathMin(maxL, MathFloor(lot/step)*step));
   return lot;
}

//+------------------------------------------------------------------+
void ManageTrailing(double atr)
{
   double trailStart = atr * TrailStart_ATR;
   double trailStep  = atr * TrailStep_ATR;
   if(trailStart<=0.0) return;

   for(int i=PositionsTotal()-1; i>=0; --i)
   {
      if(!position.SelectByIndex(i)) continue;
      if(position.Symbol()!=_Symbol || position.Magic()!=MagicNumber) continue;

      double bid  = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double ask  = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      double open = position.PriceOpen();
      double sl   = position.StopLoss();
      double tp   = position.TakeProfit();

      if(position.PositionType()==POSITION_TYPE_BUY)
      {
         double profit = bid - open;
         if(profit < trailStart) continue;
         double newSL = bid - trailStep;
         if(newSL > sl) trade.PositionModify(position.Ticket(), newSL, tp);
      }
      else
      {
         double profit = open - ask;
         if(profit < trailStart) continue;
         double newSL = ask + trailStep;
         if(sl==0.0 || newSL < sl) trade.PositionModify(position.Ticket(), newSL, tp);
      }
   }
}

void ClosePositionsByMagic()
{
   for(int i=PositionsTotal()-1; i>=0; --i)
   {
      if(!position.SelectByIndex(i)) continue;
      if(position.Symbol()!=_Symbol || position.Magic()!=MagicNumber) continue;
      trade.PositionClose(position.Ticket());
   }
}

//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &req,
                        const MqlTradeResult  &res)
{
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD) return;
   if(!HistoryDealSelect(trans.deal)) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC)!=MagicNumber) return;
   long entry = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
   if(entry!=DEAL_ENTRY_OUT) return;

   double profit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT)
                 + HistoryDealGetDouble(trans.deal, DEAL_SWAP)
                 + HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);
   if(profit < 0.0)
   {
      consecLosses++;
      if(consecLosses >= MaxConsecLoss)
      {
         cooldownUntil = TimeCurrent() + CooldownMinutes*60;
         consecLosses = 0;
      }
   }
   else if(profit > 0.0) consecLosses = 0;
}

//+------------------------------------------------------------------+
void OnTick()
{
   // 新足のみで判定（M1/M5 兼用、ノイズ抑制）
   datetime t = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_LASTBAR_DATE);
   double atr;
   if(!GetBuf(hATR, 0, atr) || atr<=0.0) return;

   ManageTrailing(atr);

   if(t == lastBarTime) return;
   lastBarTime = t;

   if(TimeCurrent() < cooldownUntil) return;

   double emaF, emaS, rsi, atrPrev;
   if(!GetBuf(hEMAfast, 1, emaF))   return;
   if(!GetBuf(hEMAslow, 1, emaS))   return;
   if(!GetBuf(hRSI,     1, rsi))    return;
   if(!GetBuf(hATR,     1, atrPrev)) return;

   // ATR 平均との比較でボラフィルタ
   double atrAvg = 0.0; int n=0;
   for(int s=1; s<=20; ++s) { double v; if(GetBuf(hATR, s, v)) { atrAvg+=v; n++; } }
   if(n>0) atrAvg /= n;
   bool volOK = (atrAvg>0.0 && atrPrev >= atrAvg * ATR_MinMult);

   bool buySignal  = (emaF > emaS) && (rsi >= RSI_BuyMin)  && volOK;
   bool sellSignal = (emaF < emaS) && (rsi <= RSI_SellMax) && volOK;

   // 逆シグナルで早期決済
   if(CloseOnSignal)
   {
      if(buySignal && HasPosition(POSITION_TYPE_SELL))  ClosePositionsByMagic();
      if(sellSignal && HasPosition(POSITION_TYPE_BUY))  ClosePositionsByMagic();
   }

   if(HasPosition()) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double tpDist = atrPrev * TP_ATR_Mult;
   double slDist = atrPrev * SL_ATR_Mult;

   if(buySignal)
   {
      double sl = ask - slDist;
      double tp = ask + tpDist;
      double lot = CalcLotByRisk(slDist);
      trade.Buy(lot, _Symbol, ask, sl, tp, "CryptoScalper");
   }
   else if(sellSignal)
   {
      double sl = bid + slDist;
      double tp = bid - tpDist;
      double lot = CalcLotByRisk(slDist);
      trade.Sell(lot, _Symbol, bid, sl, tp, "CryptoScalper");
   }
}
//+------------------------------------------------------------------+
