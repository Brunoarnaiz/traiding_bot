# Trading Bot Project

Bot de trading automático profesional para MT5.

## 📁 Estructura

```
trading/
├── scripts/
│   ├── trading_bot.py       # Bot principal que opera automáticamente
│   └── mt5_file_bridge.py   # Puente de comunicación con MT5
├── docs/
│   └── (documentación adicional)
└── README.md
```

## 🤖 Scripts

### `trading_bot.py`
**Bot runner principal** que:
- Analiza el mercado cada 5 minutos
- Calcula indicadores técnicos (RSI, MACD, SMAs, ADX, etc.)
- Genera señales de trading con confidence score
- Ejecuta órdenes automáticamente en MT5
- Gestión de riesgo profesional (position sizing, SL/TP)

**Uso:**
```bash
python3 scripts/trading_bot.py
```

### `mt5_file_bridge.py`
**Puente de comunicación** Python ↔ MT5:
- Envía comandos al Expert Advisor en MT5
- Recibe confirmaciones de ejecución
- Soporta SL/TP automáticos
- Comunicación vía archivos (funciona con MT5 bajo Wine en Linux)

**Formato de comando:**
```
MARKET|EURUSD|BUY|0.01|1.17000|1.17500
       │      │   │    │       └─ Take Profit
       │      │   │    └───────── Stop Loss
       │      │   └────────────── Lot size
       │      └────────────────── Side (BUY/SELL)
       └───────────────────────── Symbol
```

## 🎯 Proyecto completo

El proyecto completo está en:
```
~/.openclaw/workspace/trading-bot/
```

Estos scripts son copias de referencia para desarrollo en PyCharm.

## 📊 Estado actual

- ✅ Bot operando automáticamente
- ✅ MT5 Bridge funcional con NixBridge_v2 EA
- ✅ Risk management profesional (1% por trade)
- ✅ SL/TP automáticos
- ✅ Detecta señales cada 5 minutos

## 🔗 Enlaces

- Proyecto principal: `~/.openclaw/workspace/trading-bot/`
- Logs: `~/.openclaw/workspace/trading-bot/logs/`
- Documentación: `~/.openclaw/workspace/trading-bot/docs/`

---

Creado: 2026-04-13
Bot activo en cuenta demo Vantage (5049235193)
