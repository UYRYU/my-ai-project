//+------------------------------------------------------------------+
//|                                                  IranNewsEA.mq5 |
//|                                                                  |
//|  News-driven futures EA. Tails ``signals.json`` produced by      |
//|  news_monitor.py and trades crude oil + Nikkei 225 futures with  |
//|  trailing stops.                                                  |
//|                                                                  |
//|  Sentiment-to-trade mapping (matches the user's brief):          |
//|     escalation     -> crude BUY  / nikkei SELL                   |
//|     de_escalation  -> crude SELL / nikkei BUY                    |
//|     neutral / FLAT -> close any position in that leg             |
//+------------------------------------------------------------------+
#property copyright "Iran News EA"
#property version   "1.00"
#property strict

#include <Trade/Trade.mqh>

//--- inputs --------------------------------------------------------
input string  SignalFile        = "signals.json"; // file under MQL5/Files or Common/Files
input string  CrudeSymbol       = "WTI";          // crude oil futures symbol
input string  NikkeiSymbol      = "JP225";        // Nikkei 225 futures symbol
input double  CrudeLots         = 0.10;
input double  NikkeiLots        = 0.10;
input double  InitialSLPoints   = 400;            // initial stop loss in points
input double  TrailStartPoints  = 200;            // start trailing once profit > this
input double  TrailStepPoints   = 100;            // SL distance once trailing
input double  MaxSpreadPoints   = 50;
input double  MinConfidence     = 0.65;
input int     MagicNumber       = 20260407;
input int     CheckIntervalSec  = 5;

//--- state ---------------------------------------------------------
CTrade  trade;
string  g_lastSignalId = "";

//+------------------------------------------------------------------+
int OnInit()
{
    trade.SetExpertMagicNumber(MagicNumber);
    EventSetTimer(CheckIntervalSec);
    PrintFormat("IranNewsEA started; signal_file=%s crude=%s nikkei=%s",
                SignalFile, CrudeSymbol, NikkeiSymbol);
    return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
    EventKillTimer();
}

//--- OnTick handles trailing for the chart's symbol on every tick.
//--- OnTimer handles signal polling and trailing for both legs at a
//--- fixed cadence so the EA works regardless of which chart it is
//--- attached to.
void OnTick()
{
    ApplyTrailingStop(_Symbol);
}

void OnTimer()
{
    ApplyTrailingStop(CrudeSymbol);
    ApplyTrailingStop(NikkeiSymbol);
    PollSignal();
}

//+------------------------------------------------------------------+
//| Signal polling                                                   |
//+------------------------------------------------------------------+
void PollSignal()
{
    string id, crudeDir, nikkeiDir, summary;
    double conf;
    if(!ReadSignal(id, crudeDir, nikkeiDir, conf, summary))
        return;
    if(id == "" || id == g_lastSignalId)
        return;
    if(conf < MinConfidence)
    {
        PrintFormat("Signal %s ignored (conf=%.2f < %.2f)",
                    id, conf, MinConfidence);
        g_lastSignalId = id;
        return;
    }
    PrintFormat("New signal %s :: crude=%s nikkei=%s conf=%.2f :: %s",
                id, crudeDir, nikkeiDir, conf, summary);
    HandleLeg(CrudeSymbol,  CrudeLots,  crudeDir);
    HandleLeg(NikkeiSymbol, NikkeiLots, nikkeiDir);
    g_lastSignalId = id;
}

//+------------------------------------------------------------------+
//| Read the JSON signal file. Tries Common/Files first, then        |
//| MQL5/Files. Returns false if no file is found.                   |
//+------------------------------------------------------------------+
bool ReadSignal(string &id, string &crudeDir, string &nikkeiDir,
                double &confidence, string &summary)
{
    int h = FileOpen(SignalFile, FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
    if(h == INVALID_HANDLE)
        h = FileOpen(SignalFile, FILE_READ|FILE_TXT|FILE_ANSI);
    if(h == INVALID_HANDLE)
        return false;

    string content = "";
    while(!FileIsEnding(h))
        content += FileReadString(h) + "\n";
    FileClose(h);

    id         = JsonField(content, "signal_id");
    crudeDir   = JsonField(content, "crude_signal");
    nikkeiDir  = JsonField(content, "nikkei_signal");
    summary    = JsonField(content, "headline_summary");
    confidence = StringToDouble(JsonField(content, "confidence"));
    return id != "";
}

//+------------------------------------------------------------------+
//| Minimal JSON value extractor — handles strings and bare numbers. |
//| Good enough for the flat objects we produce.                     |
//+------------------------------------------------------------------+
string JsonField(const string &json, const string &key)
{
    string pat = "\"" + key + "\"";
    int p = StringFind(json, pat);
    if(p < 0)
        return "";
    p = StringFind(json, ":", p);
    if(p < 0)
        return "";
    p++;
    int len = StringLen(json);
    while(p < len)
    {
        ushort ch = StringGetCharacter(json, p);
        if(ch != ' ' && ch != '\t' && ch != '\n' && ch != '\r')
            break;
        p++;
    }
    if(p >= len)
        return "";
    if(StringGetCharacter(json, p) == '"')
    {
        int end = StringFind(json, "\"", p + 1);
        if(end < 0)
            return "";
        return StringSubstr(json, p + 1, end - p - 1);
    }
    int end = p;
    while(end < len)
    {
        ushort ch = StringGetCharacter(json, end);
        if(ch == ',' || ch == '}' || ch == '\n' || ch == '\r' || ch == ' ')
            break;
        end++;
    }
    return StringSubstr(json, p, end - p);
}

//+------------------------------------------------------------------+
//| Position management                                              |
//+------------------------------------------------------------------+
void HandleLeg(string symbol, double lots, string dir)
{
    if(dir == "FLAT" || dir == "")
    {
        CloseSymbolPositions(symbol);
        return;
    }
    if(!SymbolSelect(symbol, true))
    {
        PrintFormat("Symbol %s not available, skipping", symbol);
        return;
    }
    if(!SpreadOK(symbol))
    {
        PrintFormat("Spread too wide on %s, skipping", symbol);
        return;
    }

    bool wantBuy = (dir == "BUY");

    // Close any opposite-side position on this symbol.
    for(int i = PositionsTotal() - 1; i >= 0; i--)
    {
        ulong ticket = PositionGetTicket(i);
        if(!PositionSelectByTicket(ticket)) continue;
        if(PositionGetString(POSITION_SYMBOL)   != symbol)      continue;
        if(PositionGetInteger(POSITION_MAGIC)   != MagicNumber) continue;
        bool isBuy = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
        if(isBuy != wantBuy)
            trade.PositionClose(ticket);
    }

    // Open a new position only if we don't already have one in the right direction.
    bool already = false;
    for(int i = 0; i < PositionsTotal(); i++)
    {
        ulong ticket = PositionGetTicket(i);
        if(!PositionSelectByTicket(ticket)) continue;
        if(PositionGetString(POSITION_SYMBOL)   != symbol)      continue;
        if(PositionGetInteger(POSITION_MAGIC)   != MagicNumber) continue;
        bool isBuy = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
        if(isBuy == wantBuy) { already = true; break; }
    }
    if(!already)
        OpenTrade(symbol, wantBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, lots);
}

void OpenTrade(string symbol, ENUM_ORDER_TYPE type, double lots)
{
    double price = (type == ORDER_TYPE_BUY)
                   ? SymbolInfoDouble(symbol, SYMBOL_ASK)
                   : SymbolInfoDouble(symbol, SYMBOL_BID);
    double pt    = SymbolInfoDouble(symbol, SYMBOL_POINT);
    double sl    = (type == ORDER_TYPE_BUY)
                   ? price - InitialSLPoints * pt
                   : price + InitialSLPoints * pt;
    if(!trade.PositionOpen(symbol, type, lots, price, sl, 0))
        PrintFormat("PositionOpen failed on %s: retcode=%d",
                    symbol, trade.ResultRetcode());
    else
        PrintFormat("Opened %s %s %.2f lots @ %.5f sl=%.5f",
                    symbol, EnumToString(type), lots, price, sl);
}

void CloseSymbolPositions(string symbol)
{
    for(int i = PositionsTotal() - 1; i >= 0; i--)
    {
        ulong ticket = PositionGetTicket(i);
        if(!PositionSelectByTicket(ticket)) continue;
        if(PositionGetString(POSITION_SYMBOL)   != symbol)      continue;
        if(PositionGetInteger(POSITION_MAGIC)   != MagicNumber) continue;
        trade.PositionClose(ticket);
    }
}

//+------------------------------------------------------------------+
//| Trailing stop                                                    |
//+------------------------------------------------------------------+
void ApplyTrailingStop(string symbol)
{
    double pt = SymbolInfoDouble(symbol, SYMBOL_POINT);
    if(pt <= 0) return;

    for(int i = 0; i < PositionsTotal(); i++)
    {
        ulong ticket = PositionGetTicket(i);
        if(!PositionSelectByTicket(ticket)) continue;
        if(PositionGetString(POSITION_SYMBOL)   != symbol)      continue;
        if(PositionGetInteger(POSITION_MAGIC)   != MagicNumber) continue;

        double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
        double sl        = PositionGetDouble(POSITION_SL);
        long   type      = PositionGetInteger(POSITION_TYPE);
        double bid       = SymbolInfoDouble(symbol, SYMBOL_BID);
        double ask       = SymbolInfoDouble(symbol, SYMBOL_ASK);

        if(type == POSITION_TYPE_BUY)
        {
            double profitPts = (bid - openPrice) / pt;
            if(profitPts < TrailStartPoints) continue;
            double newSL = bid - TrailStepPoints * pt;
            if(newSL > sl)
                trade.PositionModify(ticket, newSL, 0);
        }
        else
        {
            double profitPts = (openPrice - ask) / pt;
            if(profitPts < TrailStartPoints) continue;
            double newSL = ask + TrailStepPoints * pt;
            if(sl == 0 || newSL < sl)
                trade.PositionModify(ticket, newSL, 0);
        }
    }
}

bool SpreadOK(string symbol)
{
    double pt = SymbolInfoDouble(symbol, SYMBOL_POINT);
    if(pt <= 0) return false;
    double spread = (SymbolInfoDouble(symbol, SYMBOL_ASK)
                     - SymbolInfoDouble(symbol, SYMBOL_BID)) / pt;
    return spread <= MaxSpreadPoints;
}
