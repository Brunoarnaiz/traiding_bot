# MT5 Bridge Setup Guide

Este documento explica cómo configurar y usar el puente entre el bot Python y MetaTrader 5.

## Arquitectura

El bot Python (Linux) se comunica con MT5 (Wine) mediante archivos de texto:

```
Python Bot (Linux)          MT5 EA (Wine)
─────────────────          ────────────────
      │                         │
      │  nix_command.txt        │
      ├────────────────────────>│ Lee comandos cada 2s
      │                         │ Ejecuta órdenes
      │                         │
      │  nix_status.txt         │
      │<────────────────────────┤ Escribe resultados
      │                         │
```

**Archivos de comunicación:**
- `nix_command.txt` - Bot → MT5 (comandos)
- `nix_status.txt` - MT5 → Bot (respuestas)
- Ubicación: `~/.mt5/drive_c/users/brunoarn/AppData/Roaming/MetaQuotes/Terminal/Common/Files/`

## Instalación del EA

### 1. El archivo ya está copiado
El Expert Advisor `NixBridge.mq5` ya está en la carpeta de Experts de MT5.

### 2. Compilar el EA en MT5

1. Abre MetaTrader 5
2. Presiona `F4` para abrir MetaEditor
3. En el navegador (izquierda), encuentra: `Experts → NixBridge.mq5`
4. Haz clic derecho → `Compile` (o presiona `F7`)
5. Verifica que no hay errores en la pestaña "Errors"

### 3. Adjuntar el EA a un gráfico

1. En MT5, abre un gráfico de EURUSD (o el par que quieras operar)
2. En el navegador (izquierda), arrastra `NixBridge` al gráfico
3. En la ventana de configuración:
   - Marca "Allow Algo Trading" ✓
   - Click OK
4. Verifica que aparece una carita sonriente 😊 en la esquina superior derecha del gráfico
   - 😊 = EA funcionando
   - 😐 = EA adjunto pero AutoTrading deshabilitado
   - ❌ = Error

### 4. Habilitar AutoTrading

- En la barra de herramientas de MT5, click en el botón "AutoTrading" (o presiona `Ctrl+E`)
- El botón debe quedar verde/activo

## Uso desde Python

### Prueba básica de conexión

```bash
cd /home/brunoarn/.openclaw/workspace/trading-bot
python3 bot/test_bridge.py
```

Esto verificará:
1. Que el EA está respondiendo
2. Que puede ejecutar órdenes

### Usar el bridge en tu código

```python
from bot.mt5_file_bridge import MT5Bridge

# Crear instancia
bridge = MT5Bridge(timeout=30)

# Verificar conexión
if not bridge.check_connection():
    print("MT5 no está respondiendo")
    exit(1)

# Enviar orden de mercado
result = bridge.send_market_order(
    symbol='EURUSD',
    side='BUY',      # o 'SELL'
    lot=0.01         # tamaño de la posición
)

if result['success']:
    print(f"Orden ejecutada: {result['message']}")
else:
    print(f"Error: {result['error']}")
```

## Formato de comandos

### Orden de mercado
```
MARKET|SYMBOL|SIDE|LOT
```

Ejemplo:
```
MARKET|EURUSD|BUY|0.01
```

## Formato de respuestas

### Éxito
```
OK:Order 12345 executed - BUY EURUSD 0.01 lots at 1.08450
```

### Error
```
ERROR:Failed to get price for EURUSD
ERROR:Order failed - 10009
ERROR:Unknown order type: LIMIT
```

### Estado listo
```
READY
```

## Troubleshooting

### El EA no responde
1. Verifica que MT5 está abierto
2. Verifica que el EA está adjunto a un gráfico (debe verse 😊)
3. Verifica que AutoTrading está habilitado (botón verde en toolbar)
4. Mira la pestaña "Experts" en MT5 para ver logs del EA

### Error "Order failed"
1. Verifica que la cuenta demo tiene saldo
2. Verifica que el símbolo existe y está disponible
3. Revisa el código de error en la [documentación de MT5](https://www.mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes)

### El archivo de comando no se limpia
1. El EA limpia el archivo después de leerlo
2. Si el EA no está corriendo, el archivo permanecerá con el último comando
3. Puedes limpiar manualmente: `echo "" > ~/.mt5/drive_c/.../nix_command.txt`

## Próximos pasos

- [ ] Implementar más tipos de órdenes (LIMIT, STOP, etc)
- [ ] Añadir consulta de posiciones abiertas
- [ ] Añadir consulta de balance/equity
- [ ] Cerrar posiciones
- [ ] Modificar Stop Loss / Take Profit

## Logs

### Python side
Los logs se guardan en `trading-bot/logs/`

### MT5 side
En MT5, pestaña "Experts" muestra los logs del EA en tiempo real.
