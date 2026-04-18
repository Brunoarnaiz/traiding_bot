from config.settings import Settings
from strategies.example_strategy import generate_signal
from execution.paper_executor import PaperExecutor


def main():
    settings = Settings()
    executor = PaperExecutor()
    candles = []
    signal = generate_signal(candles)
    print('Trading bot initialized')
    print('Exchange:', settings.exchange_name or 'NOT_CONFIGURED')
    print('Mode:', 'SANDBOX/PAPER' if settings.use_sandbox else 'LIVE_DISABLED_RECOMMENDED')
    print('Signal:', signal)
    print('Orders:', executor.orders)

if __name__ == '__main__':
    main()
