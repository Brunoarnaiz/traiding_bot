def allowed_to_trade(current_drawdown: float, max_daily_drawdown: float) -> bool:
    return current_drawdown < max_daily_drawdown

def position_size(balance: float, risk_per_trade: float, stop_distance: float) -> float:
    if stop_distance <= 0:
        return 0.0
    return (balance * risk_per_trade) / stop_distance
