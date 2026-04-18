from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()

class Settings(BaseModel):
    exchange_name: str = os.getenv('EXCHANGE_NAME', '')
    api_key: str = os.getenv('EXCHANGE_API_KEY', '')
    api_secret: str = os.getenv('EXCHANGE_API_SECRET', '')
    api_passphrase: str = os.getenv('EXCHANGE_PASSPHRASE', '')
    use_sandbox: bool = os.getenv('USE_SANDBOX', 'true').lower() == 'true'
    default_symbol: str = os.getenv('DEFAULT_SYMBOL', 'BTC/USDT')
    default_timeframe: str = os.getenv('DEFAULT_TIMEFRAME', '1h')
    max_risk_per_trade: float = float(os.getenv('MAX_RISK_PER_TRADE', '0.01'))
    max_daily_drawdown: float = float(os.getenv('MAX_DAILY_DRAWDOWN', '0.03'))
