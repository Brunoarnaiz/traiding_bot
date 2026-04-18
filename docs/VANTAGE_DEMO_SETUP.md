# Configuración de Cuenta Demo Vantage

## Credenciales
- **Login:** 24996717
- **Contraseña:** HN25*inN
- **Servidor:** VantageInternational-Demo

## Conectar la cuenta en MT5

### Opción 1: Desde el menú (recomendado)

1. **Abre MetaTrader 5**
2. **Ve al menú:** `File` → `Login to Trade Account`
3. **Ingresa los datos:**
   - Login: `24996717`
   - Password: `HN25*inN`
   - Server: Busca `VantageInternational-Demo` en la lista
4. **Click en OK**

### Opción 2: Desde Navigator

1. En el panel **Navigator** (izquierda), haz clic derecho en cualquier cuenta
2. Selecciona `Login to Trade Account`
3. Ingresa las credenciales como arriba

### Opción 3: Si ya existe la cuenta

1. En **Navigator**, encuentra la cuenta `24996717`
2. Haz doble clic para conectar
3. Si pide contraseña, ingresa `HN25*inN`

## Verificar conexión

En la esquina inferior derecha de MT5 deberías ver:
- **Verde con número de ping:** ✓ Conectado correctamente
- **"No connection":** ✗ No conectado
- **"Invalid account":** ✗ Credenciales incorrectas

## Después de conectar

1. **Verifica el balance:**
   - En el panel "Toolbox" (abajo), pestaña "Trade"
   - Deberías ver el balance de la cuenta demo

2. **Configura el símbolo EURUSD:**
   - Ve a `View` → `Market Watch` (o `Ctrl+M`)
   - Si no ves EURUSD, haz clic derecho → `Symbols`
   - Busca EURUSD y marca "Show"

3. **Adjunta el EA NixBridge:**
   - Abre un gráfico de EURUSD (`Ctrl+U` y escribe EURUSD)
   - Arrastra el EA `NixBridge` desde Navigator al gráfico
   - Marca "Allow Algo Trading" y click OK
   - Verifica que aparece 😊 en el gráfico

4. **Habilita AutoTrading:**
   - Click en el botón "AutoTrading" en la toolbar
   - El botón debe quedar verde/activo

## Probar el bridge

```bash
cd /home/brunoarn/.openclaw/workspace/trading-bot
python3 bot/test_bridge.py
```

Si todo está bien, deberías ver:
```
✓ MT5 EA is responding
✓ Order executed successfully
```

## Troubleshooting

### "Invalid account"
- Verifica las credenciales (login, password, server)
- Asegúrate de escribir el servidor exactamente: `VantageInternational-Demo`

### "No connection"
- Verifica tu conexión a internet
- El servidor demo puede estar en mantenimiento (poco común)

### No puedo encontrar el servidor
- En la lista de servidores, usa el buscador
- Si no aparece, ve a `File` → `Open an Account` → busca Vantage → añadir servidor

### El EA no ejecuta órdenes
- Verifica que AutoTrading está habilitado (botón verde)
- Verifica que el EA muestra 😊 (no 😐 ni ❌)
- Revisa la pestaña "Experts" para ver logs del EA
