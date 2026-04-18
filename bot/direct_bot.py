#!/usr/bin/env python3
"""
Bot directo que opera cada minuto
"""
import time
import os
from datetime import datetime

def send_trade_command(action="BUY", lot=0.1, sl_pips=50, tp_pips=100):
    """Send trade command directly to MT5 EA"""
    
    # Mock current price for EURUSD
    current_price = 1.17000
    
    if action == "BUY":
        sl = current_price - (sl_pips * 0.00001)
        tp = current_price + (tp_pips * 0.00001)
    else:  # SELL
        sl = current_price + (sl_pips * 0.00001)
        tp = current_price - (tp_pips * 0.00001)
    
    command = f"MARKET|EURUSD|{action}|{lot}|{sl:.5f}|{tp:.5f}"
    
    print(f"📊 {datetime.now().strftime('%H:%M:%S')} - Sending: {command}")
    
    # Write command to file
    command_file = "/home/brunoarn/.mt5/drive_c/users/brunoarn/AppData/Roaming/MetaQuotes/Terminal/Common/Files/nix_command.txt"
    
    try:
        with open(command_file, 'w') as f:
            f.write(command)
        
        # Wait for response
        time.sleep(3)
        
        # Check status
        status_file = "/home/brunoarn/.mt5/drive_c/users/brunoarn/AppData/Roaming/MetaQuotes/Terminal/Common/Files/nix_status.txt"
        
        if os.path.exists(status_file):
            with open(status_file, 'r') as f:
                response = f.read().strip()
            print(f"✅ MT5 Response: {response}")
            return response
        else:
            print("❌ No response file")
            return None
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return None

def main():
    print("🤖 Direct Trading Bot Starting...")
    print("Will execute 1 trade per minute for 5 minutes")
    
    trades = ["BUY", "SELL", "BUY", "SELL", "BUY"]
    
    for i, action in enumerate(trades, 1):
        print(f"\n📈 Trade {i}/5 - {action}")
        response = send_trade_command(action)
        
        if i < len(trades):
            print("😴 Waiting 60 seconds...")
            time.sleep(60)
    
    print("\n🏁 Direct bot finished!")

if __name__ == "__main__":
    main()