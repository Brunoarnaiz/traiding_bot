# Cómo Ejecutar el Trading Bot

## ⚠️ IMPORTANTE: Siempre empieza en DEMO MODE

El bot **siempre** arranca en modo demo por seguridad. Solo cambia a live trading cuando estés 100% seguro.

## Pre-requisitos

1. **MetaTrader 5 abierto y conectado**
   - Cuenta demo: 5049235193
   - NixBridge EA adjunto a un gráfico
   - AutoTrading habilitado (botón verde)

2. **Configuración lista**
   - Archivo `.env` con credenciales
   - Virtual environment creado

## Inicio Rápido

### Opción 1: Script de inicio (recomendado)

```bash
cd /home/brunoarn/.openclaw/workspace/trading-bot
./run_bot.sh
```

### Opción 2: Manual

```bash
cd /home/brunoarn/.openclaw/workspace/trading-bot
source .venv/bin/activate
python3 bot/trading_bot.py
```

## Qué hace el bot

1. **Cada 5 minutos** (configurable):
   - Descarga datos de mercado de EURUSD
   - Calcula indicadores técnicos (RSI, MACD, SMAs, etc.)
   - Genera señal de trading (BUY/SELL/NEUTRAL)
   - Evalúa si debe operar según risk management

2. **Si detecta oportunidad:**
   - Calcula position size basado en riesgo (1% por defecto)
   - Calcula Stop Loss (basado en ATR)
   - Calcula Take Profit (risk/reward 1.5:1)
   - En DEMO: Solo muestra en log
   - En LIVE: Ejecuta orden en MT5

## Configuración del bot

Edita `bot/trading_bot.py` línea ~250:

```python
config = BotConfig(
    symbol="EURUSD",              # Par a operar
    timeframe=Timeframe.M15,      # Timeframe (M1, M5, M15, M30, H1, H4, D1)
    check_interval_seconds=300,   # Revisar cada 5 min
    risk_level=RiskLevel.CONSERVATIVE,  # CONSERVATIVE, MODERATE, AGGRESSIVE
    demo_mode=True                # ⚠️ True = demo, False = dinero real
)
```

### Niveles de riesgo

**CONSERVATIVE** (recomendado para empezar):
- 0.5% riesgo por trade
- 2% riesgo diario máximo
- Stop loss: 30 pips
- Máximo 2 posiciones abiertas

**MODERATE**:
- 1% riesgo por trade
- 3% riesgo diario máximo
- Stop loss: 20 pips
- Máximo 3 posiciones abiertas

**AGGRESSIVE** (⚠️ solo si sabes lo que haces):
- 2% riesgo por trade
- 5% riesgo diario máximo
- Stop loss: 15 pips
- Máximo 5 posiciones abiertas

## Logs

Los logs se guardan en `logs/bot_YYYYMMDD.log`

Ver en tiempo real:
```bash
tail -f logs/bot_$(date +%Y%m%d).log
```

## Parar el bot

Presiona `Ctrl+C` en la terminal donde está corriendo.

## ⚠️ Antes de pasar a LIVE TRADING

**NO cambies `demo_mode=False` hasta que:**

1. ✓ El bot haya corrido en demo al menos 1 semana
2. ✓ Hayas revisado todos los logs y entendido su comportamiento
3. ✓ Los resultados en demo sean consistentemente positivos
4. ✓ Estés 100% cómodo con el riesgo que estás tomando
5. ✓ Hayas probado en cuenta demo real (no mock data)

**Cuando estés listo:**

1. Revisa la configuración de riesgo (empieza CONSERVATIVE)
2. Verifica que la cuenta real tiene fondos suficientes
3. Cambia `demo_mode=False` en el config
4. **Monitorea constantemente las primeras horas**
5. Ten listo el botón de parar (Ctrl+C)

## Circuit Breakers de Seguridad

El bot tiene protecciones automáticas:

- **Máximo 3 pérdidas consecutivas** → Para de operar
- **Pérdida diaria > 5%** → Para de operar
- **Máximo de posiciones abiertas** → No abre más trades
- **Señales con baja confianza** → Ignora la señal

## Troubleshooting

### "MT5 Bridge not responding"
→ MT5 no está abierto o NixBridge EA no está adjunto

### "Insufficient market data"
→ Yahoo Finance bloqueado o sin internet. Cambia data source en el código.

### "Cannot trade: Daily loss limit reached"
→ Protección activada. El bot no operará más hoy.

### El bot no opera nada
→ Normal. Puede pasar horas sin encontrar oportunidades que cumplan los criterios.

## Monitoreo

**No dejes el bot sin supervisión al principio.**

Monitorea:
- Logs en tiempo real
- Panel "Trade" en MT5 (posiciones abiertas)
- Balance y equity en MT5
- Que no se acumulen pérdidas

## Datos de mercado

Por defecto usa **Yahoo Finance** (gratis, pero con delay).

Para datos en tiempo real (futuro):
- Cambiar a `DataSource.MT5_TERMINAL` (requiere implementar fetching desde MT5)
- O usar API de pago (Alpha Vantage, Twelve Data)

## Siguiente: Dashboard de Monitoreo

El Paso 5 será crear un dashboard web para ver el bot en tiempo real sin tener que leer logs.
