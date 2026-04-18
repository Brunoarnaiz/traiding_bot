from strategies.momentum import generate_signal


def run(prices, starting_balance=2500.0):
    balance = starting_balance
    position = None
    entry = 0.0
    trades = []
    for i in range(30, len(prices)):
        history = prices[: i + 1]
        px = prices[i]
        signal = generate_signal(history)
        if position is None and signal == 'buy':
            position = 'long'
            entry = px
            trades.append({'action': 'open_long', 'price': px, 'index': i})
        elif position == 'long' and signal == 'sell':
            pnl = px - entry
            balance += pnl
            trades.append({'action': 'close_long', 'price': px, 'index': i, 'pnl': pnl, 'balance': balance})
            position = None
    return {
        'starting_balance': starting_balance,
        'ending_balance': round(balance, 2),
        'trades': trades,
        'trade_count': len(trades)
    }
