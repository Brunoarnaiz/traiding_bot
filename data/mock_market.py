from random import gauss

def generate_mock_prices(start=100.0, n=300):
    prices = [start]
    for _ in range(n - 1):
        prices.append(max(1.0, prices[-1] + gauss(0, 1.2)))
    return prices
