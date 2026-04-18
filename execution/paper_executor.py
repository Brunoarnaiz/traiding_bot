class PaperExecutor:
    def __init__(self):
        self.orders = []

    def place_order(self, symbol: str, side: str, quantity: float, price: float):
        order = {
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'price': price,
            'mode': 'paper'
        }
        self.orders.append(order)
        return order
