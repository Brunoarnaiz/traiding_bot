"""Load credentials and configuration from .env file"""
import os
from pathlib import Path
from typing import Dict, Any

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / '.env'


def load_env() -> Dict[str, str]:
    """Load environment variables from .env file"""
    env = {}
    
    if not ENV_FILE.exists():
        raise FileNotFoundError(f".env file not found at {ENV_FILE}")
    
    with open(ENV_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            
            # Parse KEY=VALUE
            if '=' in line:
                key, value = line.split('=', 1)
                env[key.strip()] = value.strip()
    
    return env


def get_mt5_credentials() -> Dict[str, Any]:
    """Get MT5 account credentials"""
    env = load_env()
    
    return {
        'login': int(env.get('MT5_LOGIN', 0)),
        'password': env.get('MT5_PASSWORD', ''),
        'server': env.get('MT5_SERVER', ''),
    }


def get_trading_config() -> Dict[str, Any]:
    """Get trading configuration"""
    env = load_env()
    
    return {
        'default_symbol': env.get('DEFAULT_SYMBOL', 'EURUSD'),
        'default_lot_size': float(env.get('DEFAULT_LOT_SIZE', 0.01)),
        'max_risk_per_trade': float(env.get('MAX_RISK_PER_TRADE', 0.02)),
        'max_daily_risk': float(env.get('MAX_DAILY_RISK', 0.05)),
    }


def get_bridge_path() -> Path:
    """Get MT5 bridge path"""
    env = load_env()
    path_str = env.get('MT5_BRIDGE_PATH', '')
    
    if not path_str:
        raise ValueError("MT5_BRIDGE_PATH not set in .env")
    
    return Path(path_str)


if __name__ == '__main__':
    # Test loading
    print("Testing credentials loading...")
    print()
    
    try:
        creds = get_mt5_credentials()
        print("✓ MT5 Credentials:")
        print(f"  Login: {creds['login']}")
        print(f"  Password: {'*' * len(creds['password'])}")
        print(f"  Server: {creds['server']}")
        print()
        
        config = get_trading_config()
        print("✓ Trading Config:")
        print(f"  Default symbol: {config['default_symbol']}")
        print(f"  Default lot size: {config['default_lot_size']}")
        print(f"  Max risk per trade: {config['max_risk_per_trade']*100}%")
        print(f"  Max daily risk: {config['max_daily_risk']*100}%")
        print()
        
        bridge_path = get_bridge_path()
        print("✓ Bridge Path:")
        print(f"  {bridge_path}")
        print(f"  Exists: {bridge_path.exists()}")
        
    except Exception as e:
        print(f"✗ Error: {e}")
