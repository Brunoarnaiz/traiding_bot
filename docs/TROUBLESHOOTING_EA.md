# Troubleshooting: NixBridge EA no responde

## Síntomas
- El test del bridge dice "EA not responding"
- No aparecen órdenes en MT5
- Los archivos `nix_status.txt` y `nix_command.txt` no se actualizan

## Diagnóstico paso a paso

### 1. ¿Está MT5 abierto?
```bash
ps aux | grep terminal64.exe
```
Debe mostrar el proceso. Si no, abre MT5.

### 2. ¿Está el EA compilado?
En MT5:
1. Presiona `F4` (abre MetaEditor)
2. En Navigator (izquierda) → Experts → busca `NixBridge.mq5`
3. Si no existe, copia desde `/home/brunoarn/.openclaw/workspace/trading-bot/execution/NixBridge.mq5`
4. Presiona `F7` para compilar
5. Verifica que no hay errores en la pestaña "Errors"
6. Debe crear `NixBridge.ex5` (archivo compilado)

### 3. ¿Está el EA adjunto al gráfico?
En MT5:
1. Mira la esquina superior derecha del gráfico EURUSD
2. Debe haber un **emoji**:
   - 😊 = EA funcionando correctamente ✓
   - 😐 = EA adjunto pero AutoTrading deshabilitado
   - ❌ = Error en el EA
   - *Nada* = EA no está adjunto ✗

Si no hay emoji, el EA NO está adjunto.

### 4. ¿Cómo adjuntar el EA?
1. En MT5, abre un gráfico de EURUSD (`Ctrl+U`, escribe EURUSD, Enter)
2. En Navigator (izquierda) → Expert Advisors → busca `NixBridge`
3. **Arrastra `NixBridge`** al gráfico
4. En la ventana de configuración:
   - Pestaña "Common"
   - Marca ✓ "Allow Algo Trading"
   - Marca ✓ "Allow DLL imports" (si aparece)
   - Click OK

### 5. ¿Está AutoTrading habilitado globalmente?
En la barra de herramientas de MT5:
1. Busca el botón **"AutoTrading"** o **"Algo Trading"**
2. Click para habilitarlo
3. El botón debe quedar **VERDE** ✓

### 6. ¿Hay errores en los logs del EA?
En MT5:
1. Abre el panel "Toolbox" (parte inferior, o `Ctrl+T`)
2. Pestaña **"Experts"**
3. Busca mensajes de `NixBridge`
4. Debe decir algo como:
   ```
   NixBridge EA started - Listening for commands from Nix bot
   ```

Si ves errores, anótalos.

### 7. ¿El EA está escribiendo en los archivos correctos?
Verifica la ruta:
```bash
ls -la ~/.mt5/drive_c/users/brunoarn/AppData/Roaming/MetaQuotes/Terminal/Common/Files/
```

Debe mostrar:
- `nix_command.txt`
- `nix_status.txt`

### 8. Test manual del EA
Desde Python:
```bash
cd /home/brunoarn/.openclaw/workspace/trading-bot
python3 << 'EOF'
from pathlib import Path
import time

common = Path('/home/brunoarn/.mt5/drive_c/users/brunoarn/AppData/Roaming/MetaQuotes/Terminal/Common/Files')
status = common / 'nix_status.txt'

# Clear and wait
status.write_text('', encoding='utf-16-le')
print("Cleared status file. Waiting for EA to write READY...")

for i in range(10):
    time.sleep(2)
    if status.exists() and status.stat().st_size > 0:
        content = status.read_text(encoding='utf-16-le', errors='ignore').strip()
        print(f"✓ EA responded: '{content}'")
        break
    print(f"  Waiting {i*2}s...")
else:
    print("✗ EA did not respond in 20s")
EOF
```

## Checklist rápido

- [ ] MT5 está abierto
- [ ] EA compilado (existe `NixBridge.ex5`)
- [ ] EA adjunto al gráfico (se ve emoji 😊)
- [ ] AutoTrading habilitado (botón verde)
- [ ] EA tiene permisos (Allow Algo Trading ✓)
- [ ] No hay errores en pestaña "Experts"
- [ ] Archivos de comunicación existen en Common/Files

## Si nada funciona

1. **Reinicia el EA:**
   - Haz clic derecho en el gráfico → Remove Expert
   - Vuelve a arrastrarlo

2. **Reinicia MT5:**
   - Cierra MT5 completamente
   - Abre de nuevo
   - Vuelve a adjuntar el EA

3. **Revisa la cuenta:**
   - ¿Estás conectado a la cuenta correcta? (5049235193)
   - ¿La cuenta tiene permisos de AutoTrading?
   - ¿Hay saldo disponible?

4. **Verifica el código del EA:**
   ```bash
   cat /home/brunoarn/.openclaw/workspace/trading-bot/execution/NixBridge.mq5 | grep "OnInit"
   ```
   Debe decir `WriteStatus("READY");`
