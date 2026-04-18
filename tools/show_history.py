#!/usr/bin/env python3
"""
Show closed trade history from MT5 via NixBridge.
Usage:
    .venv/bin/python tools/show_history.py [days]

    days: how many days of history to fetch (default: 7)
"""
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bot.mt5_file_bridge import MT5Bridge


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7

    bridge = MT5Bridge(timeout=15)

    print(f"\nFetching last {days} day(s) of closed trades from MT5...\n")
    deals = bridge.get_history(days=days)

    if not deals:
        print("No closed trades found (or EA not responding).")
        return

    # Sort by time
    deals.sort(key=lambda d: d['time'])

    wins   = [d for d in deals if d['profit'] > 0]
    losses = [d for d in deals if d['profit'] < 0]
    be     = [d for d in deals if d['profit'] == 0]

    total_pnl  = sum(d['profit'] for d in deals)
    win_rate   = len(wins) / len(deals) * 100 if deals else 0
    avg_win    = sum(d['profit'] for d in wins)   / len(wins)   if wins   else 0
    avg_loss   = sum(d['profit'] for d in losses) / len(losses) if losses else 0
    best_trade = max(deals, key=lambda d: d['profit'])
    worst_trade= min(deals, key=lambda d: d['profit'])

    # Header
    print(f"{'='*66}")
    print(f"  TRADE HISTORY — last {days} day(s)   |   {len(deals)} deals")
    print(f"{'='*66}")
    print(f"  {'#':<6} {'Time':<20} {'Symbol':<8} {'Side':<5} {'Vol':<6} {'Price':<10} {'P&L':>8}")
    print(f"  {'-'*60}")

    for i, d in enumerate(deals, 1):
        dt   = datetime.fromtimestamp(d['time'], tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        pnl  = f"${d['profit']:+.2f}"
        marker = " ✓" if d['profit'] > 0 else (" ✗" if d['profit'] < 0 else "  ")
        print(f"  {i:<6} {dt:<20} {d['symbol']:<8} {d['side']:<5} "
              f"{d['volume']:<6.2f} {d['price']:<10.5f} {pnl:>8}{marker}")

    # Summary
    print(f"\n{'='*66}")
    print(f"  SUMMARY")
    print(f"{'='*66}")
    print(f"  Total P&L   : ${total_pnl:+.2f}")
    print(f"  Win rate    : {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L / {len(be)}BE)")
    print(f"  Avg win     : ${avg_win:+.2f}")
    print(f"  Avg loss    : ${avg_loss:+.2f}")
    if wins and losses:
        rr = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
        print(f"  Reward/Risk : {rr:.2f}x")
    print(f"  Best trade  : #{best_trade['ticket']}  ${best_trade['profit']:+.2f}"
          f"  ({best_trade['symbol']} {best_trade['side']})")
    print(f"  Worst trade : #{worst_trade['ticket']}  ${worst_trade['profit']:+.2f}"
          f"  ({worst_trade['symbol']} {worst_trade['side']})")
    print(f"{'='*66}\n")


if __name__ == '__main__':
    main()
