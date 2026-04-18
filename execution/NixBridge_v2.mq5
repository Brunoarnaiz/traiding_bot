//+------------------------------------------------------------------+
//|                                              NixBridge_v2.mq5    |
//|              Bridge between Linux Python Bot and MT5             |
//|              Supported commands:                                 |
//|                MARKET|SYMBOL|BUY|LOT|SL|TP                      |
//|                CLOSE|TICKET                                      |
//|                CLOSE_ALL|SYMBOL                                  |
//|                PING                                              |
//|                GET_POSITIONS                                     |
//|                GET_PRICE|SYMBOL                                  |
//|                GET_OHLCV|SYMBOL|PERIOD_MINUTES|COUNT             |
//+------------------------------------------------------------------+
#property copyright "Nix Trading Bot"
#property version   "2.20"
#property strict

// File names (inside MT5 Common/Files)
string commandFile = "nix_command.txt";
string statusFile  = "nix_status.txt";

// Magic number used for all bot orders
int    MAGIC = 123456;

// How often to poll (seconds) — don't poll every tick
datetime lastCheck          = 0;
int      checkIntervalSeconds = 1;

//+------------------------------------------------------------------+
//| Init                                                             |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("NixBridge v2.10 started");
   ClearCommand();
   WriteStatus("READY");
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Deinit                                                           |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   WriteStatus("STOPPED");
   Print("NixBridge stopped");
}

//+------------------------------------------------------------------+
//| Main tick                                                        |
//+------------------------------------------------------------------+
void OnTick()
{
   // Send current price every 5 seconds
   static datetime lastPriceUpdate = 0;
   if(TimeCurrent() - lastPriceUpdate >= 5)
   {
      double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
      string priceUpdate = StringFormat("PRICE|%s|%.5f|%.5f", _Symbol, bid, ask);
      WriteStatus(priceUpdate);
      lastPriceUpdate = TimeCurrent();
   }

   if(TimeCurrent() - lastCheck < checkIntervalSeconds)
      return;
   lastCheck = TimeCurrent();

   string command = ReadCommand();
   if(command == "" || command == " ")
      return;

   Print("CMD: ", command);
   ClearCommand();
   ExecuteCommand(command);
}

//+------------------------------------------------------------------+
//| File I/O                                                         |
//+------------------------------------------------------------------+
string ReadCommand()
{
   int h = FileOpen(commandFile, FILE_READ|FILE_TXT|FILE_COMMON|FILE_ANSI);
   if(h == INVALID_HANDLE)
      return "";
   string cmd = "";
   if(!FileIsEnding(h))
      cmd = FileReadString(h);
   FileClose(h);
   StringTrimLeft(cmd);
   StringTrimRight(cmd);
   return cmd;
}

void ClearCommand()
{
   int h = FileOpen(commandFile, FILE_WRITE|FILE_TXT|FILE_COMMON|FILE_ANSI);
   if(h != INVALID_HANDLE)
   {
      FileWriteString(h, "");
      FileClose(h);
   }
}

void WriteStatus(string status)
{
   int h = FileOpen(statusFile, FILE_WRITE|FILE_TXT|FILE_COMMON|FILE_ANSI);
   if(h != INVALID_HANDLE)
   {
      FileWriteString(h, status);
      FileClose(h);
   }
   Print("STATUS: ", status);
}

//+------------------------------------------------------------------+
//| Command router                                                   |
//+------------------------------------------------------------------+
void ExecuteCommand(string command)
{
   string parts[];
   int count = StringSplit(command, '|', parts);

   if(count < 1)
   {
      WriteStatus("ERROR:Empty command");
      return;
   }

   string cmd = parts[0];

   if(cmd == "PING")
   {
      WriteStatus("PONG");
   }
   else if(cmd == "MARKET")
   {
      if(count < 4) { WriteStatus("ERROR:MARKET needs SYMBOL|SIDE|LOT[|SL|TP]"); return; }
      string symbol = parts[1];
      string side   = parts[2];
      double lot    = StringToDouble(parts[3]);
      double sl     = (count >= 5) ? StringToDouble(parts[4]) : 0.0;
      double tp     = (count >= 6) ? StringToDouble(parts[5]) : 0.0;
      ExecuteMarketOrder(symbol, side, lot, sl, tp);
   }
   else if(cmd == "CLOSE")
   {
      if(count < 2) { WriteStatus("ERROR:CLOSE needs TICKET"); return; }
      long ticket = StringToInteger(parts[1]);
      ClosePosition(ticket);
   }
   else if(cmd == "CLOSE_ALL")
   {
      string symbol = (count >= 2) ? parts[1] : "";
      CloseAllPositions(symbol);
   }
   else if(cmd == "GET_POSITIONS")
   {
      SendOpenPositions();
   }
   else if(cmd == "GET_PRICE")
   {
      if(count < 2) { WriteStatus("ERROR:GET_PRICE needs SYMBOL"); return; }
      HandleGetPrice(parts[1]);
   }
   else if(cmd == "GET_OHLCV")
   {
      if(count < 4) { WriteStatus("ERROR:GET_OHLCV needs SYMBOL|PERIOD_MINUTES|COUNT"); return; }
      int period = (int)StringToInteger(parts[2]);
      int bars   = (int)StringToInteger(parts[3]);
      HandleGetOHLCV(parts[1], period, bars);
   }
   else if(cmd == "GET_HISTORY")
   {
      int days = (count >= 2) ? (int)StringToInteger(parts[1]) : 7;
      HandleGetHistory(days);
   }
   else
   {
      WriteStatus("ERROR:Unknown command: " + cmd);
   }
}

//+------------------------------------------------------------------+
//| Open market order                                                |
//+------------------------------------------------------------------+
void ExecuteMarketOrder(string symbol, string side, double lot, double sl, double tp)
{
   MqlTradeRequest req;
   MqlTradeResult  res;
   ZeroMemory(req);
   ZeroMemory(res);

   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick))
   {
      WriteStatus("ERROR:Cannot get price for " + symbol);
      return;
   }

   req.action   = TRADE_ACTION_DEAL;
   req.symbol   = symbol;
   req.volume   = lot;
   req.type     = (side == "BUY") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   req.price    = (side == "BUY") ? tick.ask : tick.bid;
   req.deviation= 10;
   req.magic    = MAGIC;
   req.comment  = "NixBot";

   if(sl > 0.0) req.sl = sl;
   if(tp > 0.0) req.tp = tp;

   if(!OrderSend(req, res))
   {
      WriteStatus("ERROR:OrderSend failed code=" + IntegerToString(res.retcode));
      return;
   }

   string status = StringFormat("OK:MARKET|ticket=%I64d|symbol=%s|side=%s|lot=%.2f|price=%.5f|sl=%.5f|tp=%.5f",
                                res.order, symbol, side, lot, req.price, sl, tp);
   WriteStatus(status);
}

//+------------------------------------------------------------------+
//| Close a position by ticket                                       |
//+------------------------------------------------------------------+
void ClosePosition(long ticket)
{
   if(!PositionSelectByTicket(ticket))
   {
      WriteStatus("ERROR:Position " + IntegerToString(ticket) + " not found");
      return;
   }

   string symbol = PositionGetString(POSITION_SYMBOL);
   double vol    = PositionGetDouble(POSITION_VOLUME);
   int    ptype  = (int)PositionGetInteger(POSITION_TYPE);

   MqlTradeRequest req;
   MqlTradeResult  res;
   ZeroMemory(req);
   ZeroMemory(res);

   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick))
   {
      WriteStatus("ERROR:Cannot get price for close " + symbol);
      return;
   }

   req.action   = TRADE_ACTION_DEAL;
   req.symbol   = symbol;
   req.volume   = vol;
   req.position = ticket;
   req.magic    = MAGIC;
   req.comment  = "NixBot close";
   req.deviation= 10;

   // Close direction is opposite of position type
   if(ptype == POSITION_TYPE_BUY)
   {
      req.type  = ORDER_TYPE_SELL;
      req.price = tick.bid;
   }
   else
   {
      req.type  = ORDER_TYPE_BUY;
      req.price = tick.ask;
   }

   if(!OrderSend(req, res))
   {
      WriteStatus("ERROR:Close failed code=" + IntegerToString(res.retcode));
      return;
   }

   WriteStatus("OK:CLOSE|ticket=" + IntegerToString(ticket) + "|price=" + DoubleToString(req.price, 5));
}

//+------------------------------------------------------------------+
//| Close all positions (optionally filtered by symbol)             |
//+------------------------------------------------------------------+
void CloseAllPositions(string filterSymbol)
{
   int closed = 0;
   int errors = 0;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;

      string sym = PositionGetString(POSITION_SYMBOL);
      if(filterSymbol != "" && sym != filterSymbol) continue;
      if((int)PositionGetInteger(POSITION_MAGIC) != MAGIC) continue;

      ClosePosition((long)ticket);
      closed++;
   }

   WriteStatus(StringFormat("OK:CLOSE_ALL|closed=%d|errors=%d", closed, errors));
}

//+------------------------------------------------------------------+
//| Return current bid/ask for a symbol                             |
//+------------------------------------------------------------------+
void HandleGetPrice(string symbol)
{
   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick))
   {
      WriteStatus("ERROR:Cannot get price for " + symbol);
      return;
   }
   WriteStatus(StringFormat("OK:PRICE|bid=%.5f|ask=%.5f|last=%.5f|volume=%I64d",
                             tick.bid, tick.ask, tick.last, (long)tick.volume));
}

//+------------------------------------------------------------------+
//| Map period in minutes to MQL5 timeframe enum                    |
//+------------------------------------------------------------------+
ENUM_TIMEFRAMES PeriodMinutesToTF(int period)
{
   switch(period)
   {
      case 1:    return PERIOD_M1;
      case 5:    return PERIOD_M5;
      case 15:   return PERIOD_M15;
      case 30:   return PERIOD_M30;
      case 60:   return PERIOD_H1;
      case 240:  return PERIOD_H4;
      case 1440: return PERIOD_D1;
      default:   return PERIOD_H1;
   }
}

//+------------------------------------------------------------------+
//| Return OHLCV bars for a symbol — oldest bar first               |
//+------------------------------------------------------------------+
void HandleGetOHLCV(string symbol, int period, int count)
{
   ENUM_TIMEFRAMES tf = PeriodMinutesToTF(period);

   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   int copied = CopyRates(symbol, tf, 0, count, rates);
   if(copied <= 0)
   {
      WriteStatus("ERROR:CopyRates failed for " + symbol
                  + " period=" + IntegerToString(period));
      return;
   }

   string result = "OK:OHLCV|bars=" + IntegerToString(copied) + "|data=";
   for(int i = copied - 1; i >= 0; i--)   // oldest → newest
   {
      result += StringFormat("%I64d,%.5f,%.5f,%.5f,%.5f,%I64d",
                              (long)rates[i].time,
                              rates[i].open,
                              rates[i].high,
                              rates[i].low,
                              rates[i].close,
                              (long)rates[i].tick_volume);
      if(i > 0) result += ";";
   }
   WriteStatus(result);
}

//+------------------------------------------------------------------+
//| Return list of open positions as pipe-separated string          |
//+------------------------------------------------------------------+
void SendOpenPositions()
{
   int total = PositionsTotal();
   if(total == 0)
   {
      WriteStatus("POSITIONS:none");
      return;
   }

   string result = "POSITIONS:";
   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;
      if((int)PositionGetInteger(POSITION_MAGIC) != MAGIC) continue;

      string sym  = PositionGetString(POSITION_SYMBOL);
      int    ptype= (int)PositionGetInteger(POSITION_TYPE);
      double vol  = PositionGetDouble(POSITION_VOLUME);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl   = PositionGetDouble(POSITION_SL);
      double tp   = PositionGetDouble(POSITION_TP);
      double pnl  = PositionGetDouble(POSITION_PROFIT);
      string side = (ptype == POSITION_TYPE_BUY) ? "BUY" : "SELL";

      result += StringFormat("%I64d,%s,%s,%.2f,%.5f,%.5f,%.5f,%.2f",
                             ticket, sym, side, vol, open, sl, tp, pnl);
      if(i < total - 1) result += ";";
   }
   WriteStatus(result);
}

//+------------------------------------------------------------------+
//| Return closed deal history for the last N days (bot magic only) |
//+------------------------------------------------------------------+
void HandleGetHistory(int days)
{
   datetime from = TimeCurrent() - (datetime)(days * 86400);
   datetime to   = TimeCurrent();

   if(!HistorySelect(from, to))
   {
      WriteStatus("ERROR:HistorySelect failed");
      return;
   }

   int total = HistoryDealsTotal();
   string data  = "";
   int    found = 0;

   for(int i = 0; i < total; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0) continue;
      if((int)HistoryDealGetInteger(ticket, DEAL_MAGIC) != MAGIC) continue;
      if(HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;

      long   deal_time = (long)HistoryDealGetInteger(ticket, DEAL_TIME);
      string symbol    = HistoryDealGetString(ticket, DEAL_SYMBOL);
      int    dtype     = (int)HistoryDealGetInteger(ticket, DEAL_TYPE);
      double volume    = HistoryDealGetDouble(ticket, DEAL_VOLUME);
      double price     = HistoryDealGetDouble(ticket, DEAL_PRICE);
      double profit    = HistoryDealGetDouble(ticket, DEAL_PROFIT);
      string side      = (dtype == DEAL_TYPE_BUY) ? "BUY" : "SELL";

      if(found > 0) data += ";";
      data += StringFormat("%I64d,%I64d,%s,%s,%.2f,%.5f,%.2f",
                           ticket, deal_time, symbol, side, volume, price, profit);
      found++;
   }

   WriteStatus("OK:HISTORY|deals=" + IntegerToString(found) + "|data=" + data);
}
//+------------------------------------------------------------------+
