"""
MT5 File Bridge v2
Comunicación entre el bot Python (Linux) y NixBridge_v2 EA (MT5/Wine).

Comandos soportados:
  MARKET  — abrir orden de mercado con SL/TP
  CLOSE   — cerrar posición por ticket
  CLOSE_ALL — cerrar todas las posiciones (opcionalmente filtradas por símbolo)
  PING    — verificar que el EA está vivo
  GET_POSITIONS — obtener posiciones abiertas del bot

Protocolo:
  Python escribe  → nix_command.txt  (UTF-8 / ASCII)
  MT5 EA escribe  → nix_status.txt   (ANSI / ASCII)
  Formato OK:     OK:MARKET|ticket=...|symbol=...|...
  Formato ERROR:  ERROR:mensaje
"""
from __future__ import annotations

import time
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from config.credentials import get_bridge_path, get_trading_config
    COMMON = get_bridge_path()
except Exception as e:
    logging.warning(f"Bridge path not in .env, using default: {e}")
    COMMON = Path('/home/brunoarn/.mt5/drive_c/users/brunoarn/AppData/Roaming'
                  '/MetaQuotes/Terminal/Common/Files')

logger = logging.getLogger(__name__)

COMMAND_FILE = COMMON / 'nix_command.txt'
STATUS_FILE  = COMMON / 'nix_status.txt'

COMMON.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# PARSED RESPONSE TYPES
# ---------------------------------------------------------------------------

class BridgeError(Exception):
    pass


def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    return {'success': True, **data}


def _err(msg: str) -> Dict[str, Any]:
    return {'success': False, 'error': msg}


# ---------------------------------------------------------------------------
# BRIDGE
# ---------------------------------------------------------------------------

class MT5Bridge:
    """
    File-based bridge to NixBridge_v2 EA running inside MT5/Wine.

    All methods are synchronous: they write a command, wait for the status
    file to be updated, and return a parsed dict.
    """

    def __init__(self, timeout: int = 30):
        self.timeout      = timeout
        self.command_file = COMMAND_FILE
        self.status_file  = STATUS_FILE

        try:
            cfg = get_trading_config()
            self.default_symbol = cfg.get('default_symbol', 'EURUSD')
            self.default_lot    = float(cfg.get('default_lot_size', 0.01))
        except Exception:
            self.default_symbol = 'EURUSD'
            self.default_lot    = 0.01

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    def ping(self) -> bool:
        """Return True if the EA responds to PING within timeout."""
        result = self._send_command('PING')
        return result.get('success', False)

    def check_connection(self) -> bool:
        """
        Check if the EA is alive.
        Uses PING (active) rather than reading stale status file.
        """
        return self.ping()

    def send_market_order(
        self,
        symbol:     str   = 'EURUSD',
        side:       str   = 'BUY',
        lot:        float = 0.01,
        stop_loss:  float = 0.0,
        take_profit: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Open a market order with optional SL/TP.

        Returns dict with keys:
          success, ticket, symbol, side, lot, price, sl, tp   (on OK)
          success, error                                        (on ERROR)
        """
        cmd = f'MARKET|{symbol}|{side}|{lot:.2f}|{stop_loss:.5f}|{take_profit:.5f}'
        return self._send_command(cmd)

    def close_position(self, ticket: int) -> Dict[str, Any]:
        """
        Close a specific position by its MT5 ticket number.

        Returns dict with keys:
          success, ticket, price   (on OK)
          success, error           (on ERROR)
        """
        return self._send_command(f'CLOSE|{ticket}')

    def close_all_positions(self, symbol: str = '') -> Dict[str, Any]:
        """
        Close all bot-opened positions, optionally filtered by symbol.

        Returns dict with keys:
          success, closed, errors
        """
        cmd = f'CLOSE_ALL|{symbol}' if symbol else 'CLOSE_ALL'
        return self._send_command(cmd)

    def get_positions(self) -> List[Dict[str, Any]]:
        """
        Get all currently open positions opened by this bot.

        Returns list of dicts, each with:
          ticket, symbol, side, lot, open_price, sl, tp, pnl
        """
        result = self._send_command('GET_POSITIONS')
        if not result.get('success'):
            logger.error(f"GET_POSITIONS failed: {result.get('error')}")
            return []
        return result.get('positions', [])

    def modify_sl(
        self,
        ticket:     int,
        new_sl:     float,
        take_profit: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Modify the Stop Loss (and optionally TP) of an open position.

        Requires the NixBridge EA to support the MODIFY command:
          MODIFY|<ticket>|<new_sl>|<new_tp>
        Returns dict with success/error.
        """
        cmd = f'MODIFY|{ticket}|{new_sl:.5f}|{take_profit:.5f}'
        return self._send_command(cmd)

    def get_price(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get current bid/ask tick for a symbol from MT5.

        Returns dict with keys: bid, ask, last, volume  (on success)
        Returns None on failure.
        """
        result = self._send_command(f'GET_PRICE|{symbol}')
        if not result.get('success'):
            logger.warning(f"GET_PRICE failed: {result.get('error')}")
            return None
        return result

    def get_history(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Get closed deal history for the last N days (bot magic only).

        Returns list of dicts with keys:
          ticket, time (unix), symbol, side, volume, price, profit
        Returns [] on failure.
        """
        result = self._send_command(f'GET_HISTORY|{days}')
        if not result.get('success'):
            logger.warning(f"GET_HISTORY failed: {result.get('error')}")
            return []

        raw_data = result.get('data', '')
        deals = []
        if not raw_data:
            return deals

        for entry in str(raw_data).split(';'):
            entry = entry.strip()
            if not entry:
                continue
            fields = entry.split(',')
            if len(fields) < 7:
                continue
            try:
                deals.append({
                    'ticket':  int(fields[0]),
                    'time':    int(fields[1]),
                    'symbol':  fields[2],
                    'side':    fields[3],
                    'volume':  float(fields[4]),
                    'price':   float(fields[5]),
                    'profit':  float(fields[6]),
                })
            except (ValueError, IndexError) as e:
                logger.warning(f'Could not parse history entry "{entry}": {e}')

        return deals

    def get_ohlcv(self, symbol: str, period_minutes: int, count: int) -> List[Dict[str, Any]]:
        """
        Get historical OHLCV bars from MT5.

        Args:
            symbol:         e.g. "EURUSD"
            period_minutes: 1, 5, 15, 30, 60, 240, or 1440
            count:          number of bars requested

        Returns list of dicts with keys: time (unix), open, high, low, close, volume
        Returns [] on failure.
        """
        result = self._send_command(f'GET_OHLCV|{symbol}|{period_minutes}|{count}')
        if not result.get('success'):
            logger.warning(f"GET_OHLCV failed: {result.get('error')}")
            return []

        raw_data = result.get('data', '')
        if not raw_data:
            return []

        bars = []
        for entry in str(raw_data).split(';'):
            entry = entry.strip()
            if not entry:
                continue
            fields = entry.split(',')
            if len(fields) < 6:
                continue
            try:
                bars.append({
                    'time':   int(fields[0]),
                    'open':   float(fields[1]),
                    'high':   float(fields[2]),
                    'low':    float(fields[3]),
                    'close':  float(fields[4]),
                    'volume': float(fields[5]),
                })
            except (ValueError, IndexError) as e:
                logger.warning(f'Could not parse OHLCV entry "{entry}": {e}')

        return bars

    # ------------------------------------------------------------------
    # INTERNAL
    # ------------------------------------------------------------------

    def _send_command(self, command: str) -> Dict[str, Any]:
        """Write command, wait for status update, return parsed response."""
        try:
            # Clear any stale status
            if self.status_file.exists():
                self.status_file.unlink()

            # Write command as UTF-16-LE with BOM — compatible with both
            # old EA (FILE_TXT = Unicode) and new EA (FILE_ANSI handles ASCII subset)
            self.command_file.write_bytes(command.encode('utf-16'))
            logger.debug(f'CMD → {command}')

            # Poll for response — skip auto price-update lines
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                raw = self._read_status()
                if raw:
                    if raw.startswith('PRICE|'):
                        # EA broadcasts bid/ask every 5s; ignore while waiting for command reply
                        time.sleep(0.1)
                        continue
                    logger.debug(f'STATUS ← {raw}')
                    return self._parse_status(raw)
                time.sleep(0.3)

            return _err(f'Timeout ({self.timeout}s) waiting for MT5 response to: {command}')

        except Exception as e:
            logger.error(f'Bridge error: {e}', exc_info=True)
            return _err(str(e))

    def _read_status(self) -> Optional[str]:
        """Read and return raw status string, or None if file is empty/missing.
        Handles UTF-16 (old EA default) and UTF-8/ANSI (new EA with FILE_ANSI)."""
        if not self.status_file.exists():
            return None
        try:
            raw = self.status_file.read_bytes()
            if not raw:
                return None
            # Detect UTF-16 by BOM (FF FE or FE FF)
            if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
                text = raw.decode('utf-16').strip().lstrip('\ufeff')
            else:
                # UTF-8 or ANSI
                text = raw.decode('utf-8', errors='replace').strip().lstrip('\ufeff')
            return text if text else None
        except Exception as e:
            logger.warning(f'Status read error: {e}')
            return None

    def _parse_status(self, raw: str) -> Dict[str, Any]:
        """Parse raw status string into a structured dict."""
        raw = raw.strip()

        if raw == 'PONG':
            return _ok({'message': 'PONG'})

        if raw == 'READY':
            return _ok({'message': 'READY'})

        if raw == 'STOPPED':
            return _err('EA stopped')

        if raw.startswith('ERROR:'):
            return _err(raw[6:])

        if raw.startswith('OK:'):
            return self._parse_ok(raw[3:])

        if raw.startswith('POSITIONS:'):
            return self._parse_positions(raw[10:])

        return _err(f'Unknown status: {raw}')

    @staticmethod
    def _parse_ok(body: str) -> Dict[str, Any]:
        """
        Parse OK body.
        Examples:
          MARKET|ticket=12345678|symbol=EURUSD|side=BUY|lot=0.10|price=1.09500|sl=1.09200|tp=1.09950
          CLOSE|ticket=12345678|price=1.09600
          CLOSE_ALL|closed=2|errors=0
        """
        parts = body.split('|')
        cmd   = parts[0] if parts else ''
        kv: Dict[str, Any] = {'command': cmd}

        for part in parts[1:]:
            if '=' in part:
                k, v = part.split('=', 1)
                # Type-cast numbers
                try:
                    kv[k] = int(v) if '.' not in v else float(v)
                except ValueError:
                    kv[k] = v

        # Rename 'ticket' to int for convenience
        if 'ticket' in kv:
            kv['ticket'] = int(kv['ticket'])

        return _ok(kv)

    @staticmethod
    def _parse_positions(body: str) -> Dict[str, Any]:
        """
        Parse POSITIONS body.
        Format: ticket,symbol,side,lot,open_price,sl,tp,pnl;ticket,...
        """
        if body.strip() == 'none':
            return _ok({'positions': [], 'message': 'No open positions'})

        positions = []
        for entry in body.split(';'):
            entry = entry.strip()
            if not entry:
                continue
            fields = entry.split(',')
            if len(fields) < 8:
                continue
            try:
                positions.append({
                    'ticket':      int(fields[0]),
                    'symbol':      fields[1],
                    'side':        fields[2],
                    'lot':         float(fields[3]),
                    'open_price':  float(fields[4]),
                    'sl':          float(fields[5]),
                    'tp':          float(fields[6]),
                    'pnl':         float(fields[7]),
                })
            except (ValueError, IndexError) as e:
                logger.warning(f'Could not parse position entry "{entry}": {e}')

        return _ok({'positions': positions, 'message': f'{len(positions)} open positions'})


# ---------------------------------------------------------------------------
# MANUAL TEST
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    logging.basicConfig(
        level  = logging.INFO,
        format = '%(asctime)s %(levelname)s %(message)s'
    )

    bridge = MT5Bridge(timeout=10)

    print('\n=== NixBridge v2 connection test ===\n')

    # 1. Ping
    print('1. PING ... ', end='', flush=True)
    if bridge.ping():
        print('OK — EA is alive')
    else:
        print('FAIL — EA not responding (is NixBridge_v2 loaded in MT5?)')
        sys.exit(1)

    # 2. Open positions
    print('\n2. GET_POSITIONS ...')
    positions = bridge.get_positions()
    if positions:
        for p in positions:
            print(f"   #{p['ticket']} {p['symbol']} {p['side']} "
                  f"{p['lot']} lots @ {p['open_price']:.5f}  PnL: ${p['pnl']:.2f}")
    else:
        print('   No open positions')

    # 3. Test market order (demo — uncomment to actually send)
    # print('\n3. MARKET ORDER ...')
    # result = bridge.send_market_order('EURUSD', 'BUY', 0.01, 1.09000, 1.10500)
    # if result['success']:
    #     print(f"   Ticket: {result.get('ticket')}  Price: {result.get('price')}")
    # else:
    #     print(f"   FAIL: {result['error']}")

    print('\nTest complete.')
