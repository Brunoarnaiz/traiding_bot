# Proyectos Nix

Colección de proyectos desarrollados con Nix.

## 📁 Proyectos

### 🤖 Trading Bot
**Directorio:** `trading/`

Bot de trading automático profesional para MT5.

**Características:**
- Trading automático 24/7
- Análisis técnico completo (10+ indicadores)
- Risk management profesional
- Stop Loss y Take Profit automáticos
- Comunicación con MT5 vía file bridge

**Estado:** ✅ Activo y operando en demo

**Scripts principales:**
- `trading_bot.py` - Bot principal
- `mt5_file_bridge.py` - Puente MT5
- `market_data.py` - Provider de datos de mercado
- `technical_analysis.py` - Análisis técnico
- `risk_manager.py` - Gestión de riesgo

---

## 🎯 Estructura de proyectos futuros

Cada proyecto nuevo debería tener:
```
nombre-proyecto/
├── scripts/          # Scripts principales
├── docs/            # Documentación
├── tests/           # Tests (opcional)
└── README.md        # Descripción del proyecto
```

## 📝 Notas

Esta carpeta es para desarrollo en PyCharm.
Los proyectos en producción están en:
- Trading Bot: `~/.openclaw/workspace/trading-bot/`

---

Última actualización: 2026-04-13
