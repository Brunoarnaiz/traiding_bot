from pathlib import Path
from datetime import datetime
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.mock_market import generate_mock_prices
from backtesting.simple_backtest import run

LOGS = ROOT / 'logs'
LOGS.mkdir(exist_ok=True)

prices = generate_mock_prices(start=100, n=500)
result = run(prices, starting_balance=2500.0)

stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
out = LOGS / f'demo_run_{stamp}.json'
out.write_text(json.dumps(result, indent=2), encoding='utf-8')

print('DEMO BOT RUN COMPLETE')
print('Starting balance:', result['starting_balance'])
print('Ending balance:', result['ending_balance'])
print('Trades logged:', result['trade_count'])
print('Log file:', out)
