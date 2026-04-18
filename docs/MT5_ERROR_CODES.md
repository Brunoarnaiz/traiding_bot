# MT5 Error Codes Reference

## Errores comunes del bridge

### 10027 - TRADE_RETCODE_CLIENT_DISABLES_AT
**AutoTrading deshabilitado por el cliente**

**Causas:**
1. El botón "AutoTrading" en MT5 no está habilitado (debe estar verde)
2. El EA no tiene permiso para operar (configuración del EA)

**Solución:**
1. En MT5, busca el botón "AutoTrading" en la barra de herramientas
2. Click para habilitarlo (debe quedar verde/activo)
3. Si ya está verde, verifica la configuración del EA:
   - Haz clic derecho en el EA en el gráfico
   - Selecciona "Expert properties"
   - Pestaña "Common"
   - Marca "Allow Algo Trading" ✓

### 10009 - TRADE_RETCODE_DONE
**Orden ejecutada correctamente**

### 10013 - TRADE_RETCODE_INVALID_REQUEST
**Request inválida**
- Parámetros incorrectos
- Símbolo no disponible
- Lote inválido

### 10014 - TRADE_RETCODE_INVALID_VOLUME
**Volumen inválido**
- Lot size fuera de rango
- No cumple con el step del símbolo

### 10015 - TRADE_RETCODE_INVALID_PRICE
**Precio inválido**
- Precio fuera de rango permitido
- Deslizamiento muy grande

### 10016 - TRADE_RETCODE_INVALID_STOPS
**Stop Loss o Take Profit inválido**
- Muy cerca del precio actual
- No cumple con stop level mínimo

### 10018 - TRADE_RETCODE_MARKET_CLOSED
**Mercado cerrado**
- Fuera de horario de trading
- Símbolo deshabilitado

### 10019 - TRADE_RETCODE_NO_MONEY
**Fondos insuficientes**
- Balance no alcanza para la operación
- Margen insuficiente

### 10021 - TRADE_RETCODE_PRICE_OFF
**Precio no disponible**
- No hay cotización actual
- Reconectar al servidor

## Más información

Documentación completa de MT5:
https://www.mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes
