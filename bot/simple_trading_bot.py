#!/usr/bin/env python3
"""
Bot simple que SÍ opera - usa precios directos de MT5
"""
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.mt5_file_bridge import MT5Bridge

def main():
    print("🤖 Bot Simple Iniciando...")
    bridge = MT5Bridge()
    
    while True:
        try:
            # Test PING
            status = bridge._send_command("PING")
            if "PONG" not in status:
                print("❌ MT5 Bridge not responding")
                time.sleep(5)
                continue
                
            print("✅ MT5 Bridge connected")
            
            # Ejecutar operación BUY inmediatamente
            print("🚀 Ejecutando operación BUY...")
            
            # BUY 0.1 lotes EURUSD
            order_result = bridge._send_command("MARKET|EURUSD|BUY|0.1|0|0")
            print(f"📊 Resultado: {order_result}")
            
            if "ORDER_OK" in order_result or "DEAL_ADD" in order_result:
                print("🎉 ¡OPERACIÓN EJECUTADA CON ÉXITO!")
                break
            else:
                print(f"❌ Error en operación: {order_result}")
                
        except Exception as e:
            print(f"Error: {e}")
            
        time.sleep(10)  # Reintentar cada 10 segundos
        
    print("Bot terminado")

if __name__ == "__main__":
    main()