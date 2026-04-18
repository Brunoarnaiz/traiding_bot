//+------------------------------------------------------------------+
//|                                                    NixBridge.mq5 |
//|                                  Bridge between Nix Bot and MT5 |
//+------------------------------------------------------------------+
#property copyright "Nix Trading Bot"
#property link      "https://github.com/yourusername/trading-bot"
#property version   "1.00"
#property strict

// File paths in Common/Files
string commandFile = "nix_command.txt";
string statusFile = "nix_status.txt";

// Timing
datetime lastCheck = 0;
int checkIntervalSeconds = 2;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("NixBridge EA started - Listening for commands from Nix bot");
   WriteStatus("READY");
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   WriteStatus("STOPPED");
   Print("NixBridge EA stopped");
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   // Check for commands periodically (not every tick)
   if(TimeCurrent() - lastCheck < checkIntervalSeconds)
      return;
   
   lastCheck = TimeCurrent();
   
   // Try to read command file
   string command = ReadCommand();
   if(command == "")
      return;
   
   Print("Command received: ", command);
   
   // Parse and execute
   ExecuteCommand(command);
   
   // Clear command file after execution
   ClearCommand();
}

//+------------------------------------------------------------------+
//| Read command from file                                           |
//+------------------------------------------------------------------+
string ReadCommand()
{
   int handle = FileOpen(commandFile, FILE_READ|FILE_TXT|FILE_COMMON);
   if(handle == INVALID_HANDLE)
      return "";
   
   string command = "";
   if(!FileIsEnding(handle))
      command = FileReadString(handle);
   
   FileClose(handle);
   return command;
}

//+------------------------------------------------------------------+
//| Clear command file                                               |
//+------------------------------------------------------------------+
void ClearCommand()
{
   int handle = FileOpen(commandFile, FILE_WRITE|FILE_TXT|FILE_COMMON);
   if(handle != INVALID_HANDLE)
   {
      FileWrite(handle, "");
      FileClose(handle);
   }
}

//+------------------------------------------------------------------+
//| Write status to file                                             |
//+------------------------------------------------------------------+
void WriteStatus(string status)
{
   int handle = FileOpen(statusFile, FILE_WRITE|FILE_TXT|FILE_COMMON);
   if(handle != INVALID_HANDLE)
   {
      FileWrite(handle, status);
      FileClose(handle);
   }
}

//+------------------------------------------------------------------+
//| Execute parsed command                                           |
//+------------------------------------------------------------------+
void ExecuteCommand(string command)
{
   // Command format: MARKET|EURUSD|BUY|0.01
   string parts[];
   int count = StringSplit(command, '|', parts);
   
   if(count < 4)
   {
      WriteStatus("ERROR:Invalid command format");
      Print("Invalid command format: ", command);
      return;
   }
   
   string orderType = parts[0];
   string symbol = parts[1];
   string side = parts[2];
   double lot = StringToDouble(parts[3]);
   
   if(orderType == "MARKET")
   {
      ExecuteMarketOrder(symbol, side, lot);
   }
   else
   {
      WriteStatus("ERROR:Unknown order type: " + orderType);
      Print("Unknown order type: ", orderType);
   }
}

//+------------------------------------------------------------------+
//| Execute market order                                             |
//+------------------------------------------------------------------+
void ExecuteMarketOrder(string symbol, string side, double lot)
{
   MqlTradeRequest request;
   MqlTradeResult result;
   ZeroMemory(request);
   ZeroMemory(result);
   
   // Prepare request
   request.action = TRADE_ACTION_DEAL;
   request.symbol = symbol;
   request.volume = lot;
   request.type = (side == "BUY") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   request.deviation = 10;
   request.magic = 123456;
   request.comment = "Nix Bot";
   
   // Get current price
   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick))
   {
      WriteStatus("ERROR:Failed to get price for " + symbol);
      Print("Failed to get price for ", symbol);
      return;
   }
   
   request.price = (side == "BUY") ? tick.ask : tick.bid;
   
   // Send order
   if(!OrderSend(request, result))
   {
      WriteStatus("ERROR:Order failed - " + IntegerToString(result.retcode));
      Print("Order failed: ", result.retcode, " - ", result.comment);
      return;
   }
   
   // Success
   string status = StringFormat("OK:Order %I64d executed - %s %s %.2f lots at %.5f",
                                result.order, side, symbol, lot, request.price);
   WriteStatus(status);
   Print(status);
}
//+------------------------------------------------------------------+
