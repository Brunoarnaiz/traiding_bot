def moving_average(values, window):
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def generate_signal(prices, fast=10, slow=30):
    if len(prices) < slow:
        return 'hold'
    ma_fast = moving_average(prices, fast)
    ma_slow = moving_average(prices, slow)
    if ma_fast is None or ma_slow is None:
        return 'hold'
    if ma_fast > ma_slow:
        return 'buy'
    if ma_fast < ma_slow:
        return 'sell'
    return 'hold'
