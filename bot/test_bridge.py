#!/usr/bin/env python3
"""Test script for MT5 Bridge"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.mt5_file_bridge import MT5Bridge
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def main():
    print("="*60)
    print("MT5 Bridge Connection Test")
    print("="*60)
    print()
    
    bridge = MT5Bridge(timeout=10)
    
    # Test 1: Check connection
    print("1. Checking if MT5 EA is running...")
    if bridge.check_connection():
        print("   ✓ MT5 EA is responding\n")
    else:
        print("   ✗ MT5 EA not responding")
        print("   → Make sure MetaTrader 5 is running")
        print("   → Make sure NixBridge EA is attached to a chart")
        print("   → Check that AutoTrading is enabled (button in toolbar)\n")
        return
    
    # Test 2: Send test order
    symbol = bridge.default_symbol
    lot = bridge.default_lot
    print(f"2. Sending test market order ({symbol} BUY {lot})...")
    result = bridge.send_market_order(symbol=symbol, side='BUY', lot=lot)
    
    if result['success']:
        print(f"   ✓ {result['message']}\n")
    else:
        print(f"   ✗ {result['error']}\n")
    
    print("="*60)
    print("Test complete!")
    print("="*60)

if __name__ == '__main__':
    main()
