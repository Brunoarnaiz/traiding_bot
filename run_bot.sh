#!/bin/bash
# Trading Bot Launcher

cd "$(dirname "$0")"

echo "=================================="
echo "🤖 Trading Bot Launcher"
echo "=================================="
echo ""

# Check if venv exists
if [ ! -d ".venv" ]; then
    echo "❌ Virtual environment not found!"
    echo "Creating venv..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt --quiet
else
    source .venv/bin/activate
fi

# Check if MT5 is running
if ! pgrep -f "terminal64.exe" > /dev/null; then
    echo "⚠️  WARNING: MetaTrader 5 does not appear to be running"
    echo "   Make sure MT5 is open with NixBridge EA attached"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""
echo "Starting bot..."
echo ""

python3 bot/trading_bot.py
