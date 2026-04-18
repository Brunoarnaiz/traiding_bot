"""MT5 File Bridge - Communication layer between Python bot and MT5 EA"""
from pathlib import Path
import json
import time
import sys
from typing import Optional, Dict, Any
import logging

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from config.credentials import get_bridge_path, get_trading_config
    COMMON = get_bridge_path()
except Exception as e:
    # Fallback to hardcoded path if .env not available
    logging.warning(f"Could not load bridge path from .env: {e}")
    COMMON = Path('/home/brunoarn/.mt5/drive_c/users/brunoarn/AppData/Roaming/MetaQuotes/Terminal/Common/Files')

logger = logging.getLogger(__name__)

COMMON.mkdir(parents=True, exist_ok=True)
COMMAND = COMMON / 'nix_command.txt'
STATUS = COMMON / 'nix_status.txt'


class MT5Bridge:
    """Bridge to communicate with MT5 via file system"""
    
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.command_file = COMMAND
        self.status_file = STATUS
        
        # Load default trading config
        try:
            self.config = get_trading_config()
            self.default_symbol = self.config['default_symbol']
            self.default_lot = self.config['default_lot_size']
        except:
            self.default_symbol = 'EURUSD'
            self.default_lot = 0.01
        
    def send_market_order(self, symbol: str = 'EURUSD', side: str = 'BUY', lot: float = 0.01,
                         stop_loss: float = 0.0, take_profit: float = 0.0) -> Dict[str, Any]:
        """Send a market order command with SL/TP and wait for response"""
        command = f'MARKET|{symbol}|{side}|{lot}|{stop_loss}|{take_profit}'
        return self._send_command(command)
    
    def _send_command(self, command: str) -> Dict[str, Any]:
        """Send command and wait for status response"""
        try:
            # Clear previous status
            if self.status_file.exists():
                self.status_file.unlink()
            
            # Write command (UTF-16 LE with BOM for MT5)
            with open(self.command_file, 'w', encoding='utf-16-le') as f:
                f.write(command)
            logger.info(f'Command sent: {command}')
            
            # Wait for response
            start_time = time.time()
            while time.time() - start_time < self.timeout:
                status = self._read_status()
                if status:
                    logger.info(f'Status received: {status}')
                    return self._parse_status(status)
                time.sleep(0.5)
            
            # Timeout
            logger.error('Timeout waiting for MT5 response')
            return {'success': False, 'error': 'Timeout waiting for MT5 response'}
            
        except Exception as e:
            logger.error(f'Bridge error: {e}')
            return {'success': False, 'error': str(e)}
    
    def _read_status(self) -> Optional[str]:
        """Read status from file"""
        if self.status_file.exists():
            try:
                # Try UTF-16 first (MT5 default)
                content = self.status_file.read_text(encoding='utf-16-le', errors='ignore').strip()
                if content:
                    return content
            except:
                pass
            
            try:
                # Fallback to UTF-8
                content = self.status_file.read_text(encoding='utf-8', errors='ignore').strip()
                if content:
                    return content
            except:
                pass
        
        return None
    
    def _parse_status(self, status: str) -> Dict[str, Any]:
        """Parse status response from MT5"""
        # Remove BOM if present
        status = status.lstrip('\ufeff').strip()
        
        if status.startswith('OK:'):
            return {'success': True, 'message': status[3:]}
        elif status.startswith('ERROR:'):
            return {'success': False, 'error': status[6:]}
        elif status == 'READY':
            return {'success': True, 'message': 'MT5 EA is ready'}
        else:
            return {'success': False, 'error': f'Unknown status: {status}'}
    
    def check_connection(self) -> bool:
        """Check if MT5 EA is running and responding"""
        status = self._read_status()
        if status is None:
            return False
        
        # Remove BOM if present
        status = status.lstrip('\ufeff').strip()
        return status == 'READY' or status.startswith('OK')


if __name__ == '__main__':
    # Test the bridge
    logging.basicConfig(level=logging.INFO)
    bridge = MT5Bridge()
    
    print('Testing MT5 Bridge...')
    print('Checking connection...', end=' ')
    if bridge.check_connection():
        print('✓ MT5 EA is responding')
    else:
        print('✗ MT5 EA not responding (make sure NixBridge EA is running in MT5)')
    
    print('\nSending test order...')
    result = bridge.send_market_order(symbol='EURUSD', side='BUY', lot=0.01)
    
    if result['success']:
        print('✓ Order executed successfully')
        print(f"  {result['message']}")
    else:
        print('✗ Order failed')
        print(f"  {result['error']}")
