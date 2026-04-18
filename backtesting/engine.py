"""
Professional Backtesting Engine
Event-driven simulation with realistic slippage, spread, commissions,
equity curve tracking, and full statistical metrics.
Generates detailed HTML reports.
"""
from __future__ import annotations

import math
import json
import random
import sys
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategies.technical_analysis import TechnicalAnalyzer, TechnicalIndicators, Signal, ohlcv_to_dataframe


# ---------------------------------------------------------------------------
# DATA STRUCTURES
# ---------------------------------------------------------------------------

class OrderSide(Enum):
    BUY  = "BUY"
    SELL = "SELL"


class TradeStatus(Enum):
    OPEN   = "OPEN"
    CLOSED = "CLOSED"


@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""
    symbol:              str   = "EURUSD"
    initial_balance:     float = 10_000.0
    risk_per_trade_pct:  float = 0.01       # 1 %
    min_rr_ratio:        float = 1.5        # Minimum Risk:Reward
    atr_sl_multiplier:   float = 2.0        # SL = N × ATR
    spread_pips:         float = 1.0        # Spread in pips (1 pip = 0.0001)
    slippage_pips:       float = 0.5        # Slippage in pips
    commission_per_lot:  float = 7.0        # USD per standard lot (round-trip)
    pip_value_per_lot:   float = 10.0       # USD per pip per standard lot
    max_open_positions:  int   = 3
    min_signal_confidence: float = 0.55
    # Extra filters
    require_adx_above:   float = 20.0       # Only trade when ADX > this
    min_bars_between_trades: int = 0        # Cool-down bars after a trade
    # --- Phase A: Exit management ---
    trailing_stop_pips:      float = 0.0    # A1: 0 = disabled. Pips distance that trails price
    breakeven_trigger_pips:  float = 0.0    # A3: 0 = disabled. Pips profit needed to activate BE
    trailing_ma_period:      int   = 0      # A2: 0 = disabled. EMA period for MA-based trailing SL


@dataclass
class Trade:
    """Represents a completed or open trade."""
    trade_id:       int
    side:           str
    entry_bar:      int
    entry_time:     str
    entry_price:    float
    lot_size:       float
    stop_loss:      float
    take_profit:    float
    risk_amount:    float

    exit_bar:       Optional[int]   = None
    exit_time:      Optional[str]   = None
    exit_price:     Optional[float] = None
    exit_reason:    Optional[str]   = None   # "TP", "SL", "EOD", "TRAILING_SL", "MA_TRAIL"

    gross_pnl:      float = 0.0
    commission:     float = 0.0
    net_pnl:        float = 0.0
    status:         TradeStatus = TradeStatus.OPEN
    # Exit management state
    breakeven_activated: bool = False

    @property
    def is_winner(self) -> bool:
        return self.net_pnl > 0

    @property
    def duration_bars(self) -> Optional[int]:
        if self.exit_bar is not None:
            return self.exit_bar - self.entry_bar
        return None


@dataclass
class EquityPoint:
    bar:     int
    time:    str
    equity:  float
    balance: float
    drawdown_pct: float


@dataclass
class BacktestResult:
    """Full result of a backtest run."""
    config:           BacktestConfig
    trades:           List[Trade]
    equity_curve:     List[EquityPoint]

    # --- Performance metrics ---
    initial_balance:  float = 0.0
    final_balance:    float = 0.0
    total_return_pct: float = 0.0

    total_trades:     int   = 0
    winning_trades:   int   = 0
    losing_trades:    int   = 0
    win_rate:         float = 0.0

    gross_profit:     float = 0.0
    gross_loss:       float = 0.0
    net_profit:       float = 0.0
    profit_factor:    float = 0.0

    max_drawdown_pct: float = 0.0
    max_drawdown_abs: float = 0.0
    recovery_factor:  float = 0.0

    sharpe_ratio:     float = 0.0
    sortino_ratio:    float = 0.0
    calmar_ratio:     float = 0.0

    avg_win:          float = 0.0
    avg_loss:         float = 0.0
    avg_rr_ratio:     float = 0.0
    max_consecutive_wins:   int = 0
    max_consecutive_losses: int = 0

    expectancy:       float = 0.0   # $ per trade
    sqn:              float = 0.0   # System Quality Number


# ---------------------------------------------------------------------------
# ENGINE
# ---------------------------------------------------------------------------

class BacktestEngine:
    """
    Event-driven backtesting engine.

    Walk bar-by-bar through historical data, generate signals, open/close
    trades with realistic transaction costs, and compute full statistics.
    """

    def __init__(self, config: BacktestConfig = None):
        self.config   = config or BacktestConfig()
        self.analyzer = TechnicalAnalyzer()

    def run(
        self,
        df: pd.DataFrame,
        verbose: bool = True
    ) -> BacktestResult:
        """
        Run a full backtest on the supplied OHLCV dataframe.

        Args:
            df:      DataFrame indexed by timestamp with open/high/low/close/volume
            verbose: Print progress to stdout

        Returns:
            BacktestResult with full metrics and trade log
        """
        cfg     = self.config
        n_bars  = len(df)
        pip     = 0.0001  # For EURUSD / most 4-decimal pairs
        spread  = cfg.spread_pips  * pip
        slip    = cfg.slippage_pips * pip

        balance      = cfg.initial_balance
        equity       = balance
        open_trades: List[Trade] = []
        closed_trades: List[Trade] = []
        equity_curve: List[EquityPoint] = []
        peak_equity  = balance
        max_dd_abs   = 0.0
        max_dd_pct   = 0.0
        trade_counter = 0
        last_trade_bar = -999

        # Warm-up: need at least 55 bars for all indicators
        warmup = 55

        if verbose:
            print(f"\nBacktest: {cfg.symbol}  |  {n_bars} bars  |  Balance: ${balance:,.2f}")
            print("-" * 60)

        # Pre-compute MA trailing EMA series if needed (A2)
        ema_series: Optional[pd.Series] = None
        if cfg.trailing_ma_period > 0:
            ema_series = df['close'].ewm(
                span=cfg.trailing_ma_period, adjust=False
            ).mean()

        for bar_idx in range(warmup, n_bars):
            bar      = df.iloc[bar_idx]
            bar_high = float(bar['high'])
            bar_low  = float(bar['low'])
            bar_open = float(bar['open'])
            bar_close= float(bar['close'])
            bar_time = str(df.index[bar_idx])

            # Current EMA value for MA trailing (A2)
            current_ema = float(ema_series.iloc[bar_idx]) if ema_series is not None else None

            # --- Phase A: Update trailing SL and breakeven BEFORE checking hits ---
            for trade in open_trades:
                # A3 — Breakeven: move SL to entry once profit target is reached
                if cfg.breakeven_trigger_pips > 0 and not trade.breakeven_activated:
                    if trade.side == OrderSide.BUY.value:
                        profit_pips = (bar_close - trade.entry_price) / pip
                    else:
                        profit_pips = (trade.entry_price - bar_close) / pip
                    if profit_pips >= cfg.breakeven_trigger_pips:
                        trade.stop_loss = trade.entry_price
                        trade.breakeven_activated = True

                # A1 — Trailing Stop: SL follows price, never moves against us
                if cfg.trailing_stop_pips > 0:
                    trail_dist = cfg.trailing_stop_pips * pip
                    if trade.side == OrderSide.BUY.value:
                        new_sl = bar_close - trail_dist
                        if new_sl > trade.stop_loss:
                            trade.stop_loss = round(new_sl, 5)
                    else:
                        new_sl = bar_close + trail_dist
                        if new_sl < trade.stop_loss:
                            trade.stop_loss = round(new_sl, 5)

                # A2 — MA Trailing: SL = EMA level; close when price crosses EMA
                if current_ema is not None:
                    if trade.side == OrderSide.BUY.value:
                        new_sl = current_ema
                        if new_sl > trade.stop_loss:
                            trade.stop_loss = round(new_sl, 5)
                    else:
                        new_sl = current_ema
                        if new_sl < trade.stop_loss:
                            trade.stop_loss = round(new_sl, 5)

            # --- Check open trades for SL/TP hits (use bar's H/L) ---
            still_open: List[Trade] = []
            for trade in open_trades:
                hit_sl = False
                hit_tp = False
                exit_reason_str = "SL"

                if trade.side == OrderSide.BUY.value:
                    if bar_low <= trade.stop_loss:
                        hit_sl = True
                        exit_price = trade.stop_loss - slip
                        exit_reason_str = "TRAILING_SL" if (
                            trade.breakeven_activated
                            or cfg.trailing_stop_pips > 0
                            or cfg.trailing_ma_period > 0
                        ) else "SL"
                    elif bar_high >= trade.take_profit:
                        hit_tp = True
                        exit_price = trade.take_profit - slip
                else:  # SELL
                    if bar_high >= trade.stop_loss:
                        hit_sl = True
                        exit_price = trade.stop_loss + slip
                        exit_reason_str = "TRAILING_SL" if (
                            trade.breakeven_activated
                            or cfg.trailing_stop_pips > 0
                            or cfg.trailing_ma_period > 0
                        ) else "SL"
                    elif bar_low <= trade.take_profit:
                        hit_tp = True
                        exit_price = trade.take_profit + slip

                if hit_sl or hit_tp:
                    # Calculate PnL
                    if trade.side == OrderSide.BUY.value:
                        pip_diff = (exit_price - trade.entry_price) / pip
                    else:
                        pip_diff = (trade.entry_price - exit_price) / pip

                    gross = pip_diff * cfg.pip_value_per_lot * trade.lot_size
                    comm  = cfg.commission_per_lot * trade.lot_size
                    net   = gross - comm

                    trade.exit_bar    = bar_idx
                    trade.exit_time   = bar_time
                    trade.exit_price  = round(exit_price, 5)
                    trade.exit_reason = "TP" if hit_tp else exit_reason_str
                    trade.gross_pnl   = round(gross, 2)
                    trade.commission  = round(comm, 2)
                    trade.net_pnl     = round(net, 2)
                    trade.status      = TradeStatus.CLOSED
                    balance          += net
                    closed_trades.append(trade)
                else:
                    still_open.append(trade)

            open_trades = still_open

            # --- Compute equity (balance + unrealised PnL) ---
            unrealised = 0.0
            for trade in open_trades:
                if trade.side == OrderSide.BUY.value:
                    pip_diff = (bar_close - trade.entry_price) / pip
                else:
                    pip_diff = (trade.entry_price - bar_close) / pip
                unrealised += pip_diff * cfg.pip_value_per_lot * trade.lot_size

            equity = balance + unrealised

            # Drawdown
            if equity > peak_equity:
                peak_equity = equity
            dd_abs = peak_equity - equity
            dd_pct = dd_abs / peak_equity * 100 if peak_equity > 0 else 0.0
            max_dd_abs = max(max_dd_abs, dd_abs)
            max_dd_pct = max(max_dd_pct, dd_pct)

            equity_curve.append(EquityPoint(
                bar=bar_idx,
                time=bar_time,
                equity=round(equity, 2),
                balance=round(balance, 2),
                drawdown_pct=round(dd_pct, 2)
            ))

            # --- Generate signal (use last 200 bars for indicator calculation) ---
            start = max(0, bar_idx - 200)
            window_df = df.iloc[start : bar_idx + 1]
            if len(window_df) < warmup:
                continue

            ind = self.analyzer.calculate_indicators(window_df)
            signal, confidence, reason = self.analyzer.generate_signal(ind)

            # --- Entry conditions ---
            enough_cooldown = (bar_idx - last_trade_bar) >= cfg.min_bars_between_trades
            can_open = (
                len(open_trades) < cfg.max_open_positions
                and confidence >= cfg.min_signal_confidence
                and signal != Signal.NEUTRAL
                and enough_cooldown
                and ind.atr is not None
                and (ind.adx is None or ind.adx >= cfg.require_adx_above)
            )

            if can_open and signal in (Signal.BUY, Signal.STRONG_BUY, Signal.SELL, Signal.STRONG_SELL):
                side = OrderSide.BUY if signal in (Signal.BUY, Signal.STRONG_BUY) else OrderSide.SELL

                # Entry price with spread + slippage
                if side == OrderSide.BUY:
                    entry_price = bar_close + spread + slip
                else:
                    entry_price = bar_close - spread - slip

                # Stop loss (ATR-based)
                sl_distance = ind.atr * cfg.atr_sl_multiplier
                if side == OrderSide.BUY:
                    sl = round(entry_price - sl_distance, 5)
                    tp = round(entry_price + sl_distance * cfg.min_rr_ratio, 5)
                else:
                    sl = round(entry_price + sl_distance, 5)
                    tp = round(entry_price - sl_distance * cfg.min_rr_ratio, 5)

                # Position size
                pips_risked = sl_distance / pip
                max_risk    = balance * cfg.risk_per_trade_pct
                lot_size    = round(max_risk / (pips_risked * cfg.pip_value_per_lot), 2)
                lot_size    = max(0.01, min(lot_size, 10.0))
                risk_amount = pips_risked * cfg.pip_value_per_lot * lot_size

                trade_counter += 1
                trade = Trade(
                    trade_id    = trade_counter,
                    side        = side.value,
                    entry_bar   = bar_idx,
                    entry_time  = bar_time,
                    entry_price = round(entry_price, 5),
                    lot_size    = lot_size,
                    stop_loss   = sl,
                    take_profit = tp,
                    risk_amount = round(risk_amount, 2),
                )
                open_trades.append(trade)
                last_trade_bar = bar_idx

        # --- Close any remaining open trades at last bar price ---
        last_close = float(df['close'].iloc[-1])
        last_time  = str(df.index[-1])
        for trade in open_trades:
            if trade.side == OrderSide.BUY.value:
                pip_diff = (last_close - trade.entry_price) / pip
            else:
                pip_diff = (trade.entry_price - last_close) / pip
            gross = pip_diff * cfg.pip_value_per_lot * trade.lot_size
            comm  = cfg.commission_per_lot * trade.lot_size
            net   = gross - comm

            trade.exit_bar    = n_bars - 1
            trade.exit_time   = last_time
            trade.exit_price  = round(last_close, 5)
            trade.exit_reason = "EOD"
            trade.gross_pnl   = round(gross, 2)
            trade.commission  = round(comm, 2)
            trade.net_pnl     = round(net, 2)
            trade.status      = TradeStatus.CLOSED
            balance          += net
            closed_trades.append(trade)

        # --- Compute statistics ---
        result = self._compute_statistics(
            cfg           = cfg,
            closed_trades = closed_trades,
            equity_curve  = equity_curve,
            initial_balance = cfg.initial_balance,
            final_balance   = balance,
            max_dd_abs    = max_dd_abs,
            max_dd_pct    = max_dd_pct,
        )
        if verbose:
            self._print_summary(result)
        return result

    # ------------------------------------------------------------------
    # STATISTICS
    # ------------------------------------------------------------------

    def _compute_statistics(
        self,
        cfg: BacktestConfig,
        closed_trades: List[Trade],
        equity_curve:  List[EquityPoint],
        initial_balance: float,
        final_balance:   float,
        max_dd_abs: float,
        max_dd_pct: float,
    ) -> BacktestResult:

        result = BacktestResult(
            config        = cfg,
            trades        = closed_trades,
            equity_curve  = equity_curve,
            initial_balance = initial_balance,
            final_balance   = round(final_balance, 2),
        )

        result.total_return_pct = round((final_balance - initial_balance) / initial_balance * 100, 2)
        result.max_drawdown_abs = round(max_dd_abs, 2)
        result.max_drawdown_pct = round(max_dd_pct, 2)
        result.total_trades = len(closed_trades)

        if not closed_trades:
            return result

        winners = [t for t in closed_trades if t.is_winner]
        losers  = [t for t in closed_trades if not t.is_winner]

        result.winning_trades = len(winners)
        result.losing_trades  = len(losers)
        result.win_rate = round(len(winners) / len(closed_trades) * 100, 2)

        result.gross_profit = round(sum(t.net_pnl for t in winners), 2)
        result.gross_loss   = round(abs(sum(t.net_pnl for t in losers)), 2)
        result.net_profit   = round(result.gross_profit - result.gross_loss, 2)
        result.profit_factor = round(result.gross_profit / result.gross_loss, 3) if result.gross_loss > 0 else float('inf')

        result.avg_win  = round(result.gross_profit / len(winners), 2) if winners else 0.0
        result.avg_loss = round(result.gross_loss   / len(losers),  2) if losers  else 0.0

        # RR ratios
        rr_ratios = []
        for t in closed_trades:
            if t.risk_amount > 0:
                rr_ratios.append(t.net_pnl / t.risk_amount)
        result.avg_rr_ratio = round(float(np.mean(rr_ratios)), 3) if rr_ratios else 0.0

        # Consecutive win/loss streaks
        result.max_consecutive_wins   = self._max_streak([t.is_winner for t in closed_trades], True)
        result.max_consecutive_losses = self._max_streak([t.is_winner for t in closed_trades], False)

        # Expectancy
        wr = result.win_rate / 100
        result.expectancy = round(wr * result.avg_win - (1 - wr) * result.avg_loss, 2)

        # Sharpe / Sortino (daily PnL approximation)
        pnls = np.array([t.net_pnl for t in closed_trades])
        if len(pnls) >= 2:
            pnl_std = float(np.std(pnls, ddof=1))
            neg_pnls = pnls[pnls < 0]
            downside_std = float(np.std(neg_pnls, ddof=1)) if len(neg_pnls) > 1 else pnl_std
            mean_pnl = float(np.mean(pnls))
            result.sharpe_ratio  = round(mean_pnl / pnl_std   if pnl_std   > 0 else 0.0, 3)
            result.sortino_ratio = round(mean_pnl / downside_std if downside_std > 0 else 0.0, 3)

        # Calmar
        if max_dd_pct > 0:
            annual_return = result.total_return_pct  # Approximation
            result.calmar_ratio = round(annual_return / max_dd_pct, 3)

        # Recovery factor
        if max_dd_abs > 0:
            result.recovery_factor = round(result.net_profit / max_dd_abs, 3)

        # SQN (System Quality Number)
        if len(pnls) >= 2:
            pnl_std = float(np.std(pnls, ddof=1))
            mean_pnl = float(np.mean(pnls))
            sqn_raw = (mean_pnl / pnl_std) * math.sqrt(len(pnls)) if pnl_std > 0 else 0.0
            result.sqn = round(sqn_raw, 3)

        return result

    @staticmethod
    def _max_streak(outcomes: List[bool], target: bool) -> int:
        max_streak = current = 0
        for o in outcomes:
            if o == target:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    # ------------------------------------------------------------------
    # CONSOLE SUMMARY
    # ------------------------------------------------------------------

    def _print_summary(self, r: BacktestResult):
        print(f"\n{'='*60}")
        print(f"  BACKTEST RESULTS — {r.config.symbol}")
        print(f"{'='*60}")
        print(f"  Balance:        ${r.initial_balance:>10,.2f}  →  ${r.final_balance:>10,.2f}")
        print(f"  Net Profit:     ${r.net_profit:>+10,.2f}  ({r.total_return_pct:+.2f}%)")
        print(f"  Max Drawdown:   ${r.max_drawdown_abs:>10,.2f}  ({r.max_drawdown_pct:.2f}%)")
        print(f"{'─'*60}")
        print(f"  Total Trades:   {r.total_trades}")
        print(f"  Win Rate:       {r.win_rate:.1f}%  ({r.winning_trades}W / {r.losing_trades}L)")
        print(f"  Profit Factor:  {r.profit_factor:.3f}")
        print(f"  Avg Win:        ${r.avg_win:>8,.2f}  |  Avg Loss: ${r.avg_loss:>8,.2f}")
        print(f"  Avg R:R Ratio:  {r.avg_rr_ratio:.2f}")
        print(f"  Expectancy:     ${r.expectancy:>+8,.2f} / trade")
        print(f"{'─'*60}")
        print(f"  Sharpe:         {r.sharpe_ratio:.3f}")
        print(f"  Sortino:        {r.sortino_ratio:.3f}")
        print(f"  Calmar:         {r.calmar_ratio:.3f}")
        print(f"  SQN:            {r.sqn:.3f}")
        print(f"  Recovery Factor:{r.recovery_factor:.3f}")
        print(f"{'─'*60}")
        print(f"  Max Win Streak: {r.max_consecutive_wins}")
        print(f"  Max Loss Streak:{r.max_consecutive_losses}")
        print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# HTML REPORT GENERATOR
# ---------------------------------------------------------------------------

class ReportGenerator:
    """Generates a standalone HTML report from a BacktestResult."""

    @staticmethod
    def generate(
        result:              BacktestResult,
        output_path:         Optional[Path] = None,
        robustness_verdict:  Any            = None,   # Optional[RobustnessVerdict]
        multi_symbol:        Any            = None,   # Optional[MultiSymbolSummary]
        walk_forward:        Any            = None,   # Optional[WalkForwardSummary]
    ) -> Path:
        """
        Build HTML report and write to disk.

        Args:
            result:             BacktestResult to report on
            output_path:        Where to save the HTML file (default: reports/)
            robustness_verdict: Optional RobustnessVerdict from OverfitDetector (D1)
            multi_symbol:       Optional MultiSymbolSummary from MultiSymbolTester (D2)
            walk_forward:       Optional WalkForwardSummary from WalkForwardTester

        Returns:
            Path to the saved HTML file
        """
        if output_path is None:
            reports_dir = ROOT / 'reports'
            reports_dir.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = reports_dir / f"backtest_{result.config.symbol}_{ts}.html"

        r = result

        # Equity curve data for Chart.js
        eq_labels = [ep.time[:16] for ep in r.equity_curve[::max(1, len(r.equity_curve)//200)]]
        eq_values = [ep.equity  for ep in r.equity_curve[::max(1, len(r.equity_curve)//200)]]
        dd_values = [ep.drawdown_pct for ep in r.equity_curve[::max(1, len(r.equity_curve)//200)]]

        # Trade PnL distribution
        pnls = [t.net_pnl for t in r.trades]

        # Metric color helpers
        def color(val, good_positive=True):
            if good_positive:
                return "#27ae60" if val >= 0 else "#e74c3c"
            else:
                return "#e74c3c" if val >= 0 else "#27ae60"

        # Trade table rows
        trade_rows = ""
        for t in r.trades[:500]:  # Cap at 500 for HTML size
            pnl_color = "#27ae60" if t.net_pnl >= 0 else "#e74c3c"
            side_color = "#2980b9" if t.side == "BUY" else "#8e44ad"
            trade_rows += f"""
            <tr>
                <td>{t.trade_id}</td>
                <td style="color:{side_color}">{t.side}</td>
                <td>{t.entry_time[:16]}</td>
                <td>{t.entry_price:.5f}</td>
                <td>{t.exit_price:.5f if t.exit_price else '—'}</td>
                <td>{t.exit_reason or '—'}</td>
                <td>{t.lot_size:.2f}</td>
                <td style="color:{pnl_color}">${t.net_pnl:+.2f}</td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Backtest Report — {r.config.symbol}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin:0; padding:0 }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #1a1a2e; color: #e0e0e0; }}
  h1 {{ background: linear-gradient(135deg,#6a11cb,#2575fc); padding:18px 24px; font-size:1.5rem; }}
  h2 {{ color: #7ecff4; margin:24px 0 10px; font-size:1.1rem; }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px,1fr)); gap:12px; margin-bottom:20px; }}
  .card {{ background:#16213e; border-radius:8px; padding:14px; text-align:center; border:1px solid #0f3460; }}
  .card .label {{ font-size:.75rem; color:#aaa; margin-bottom:6px; text-transform:uppercase; letter-spacing:.5px; }}
  .card .value {{ font-size:1.3rem; font-weight:700; }}
  .positive {{ color:#27ae60 }}
  .negative {{ color:#e74c3c }}
  .neutral  {{ color:#f39c12 }}
  canvas {{ background:#16213e; border-radius:8px; margin-bottom:20px; }}
  table {{ width:100%; border-collapse:collapse; font-size:.82rem; }}
  th {{ background:#0f3460; padding:8px 10px; text-align:left; }}
  td {{ padding:6px 10px; border-bottom:1px solid #1a1a2e; }}
  tr:nth-child(even) {{ background:#16213e; }}
  tr:hover {{ background:#0f3460; }}
  .section {{ background:#16213e; border-radius:8px; padding:16px; margin-bottom:20px; border:1px solid #0f3460; overflow-x:auto; }}
</style>
</head>
<body>
<h1>Backtest Report &mdash; {r.config.symbol}</h1>
<div class="container">

  <h2>Performance Summary</h2>
  <div class="grid">
    <div class="card"><div class="label">Net Profit</div>
      <div class="value {'positive' if r.net_profit>=0 else 'negative'}">${r.net_profit:+,.2f}</div></div>
    <div class="card"><div class="label">Return</div>
      <div class="value {'positive' if r.total_return_pct>=0 else 'negative'}">{r.total_return_pct:+.2f}%</div></div>
    <div class="card"><div class="label">Max Drawdown</div>
      <div class="value negative">-{r.max_drawdown_pct:.2f}%</div></div>
    <div class="card"><div class="label">Win Rate</div>
      <div class="value {'positive' if r.win_rate>=50 else 'negative'}">{r.win_rate:.1f}%</div></div>
    <div class="card"><div class="label">Profit Factor</div>
      <div class="value {'positive' if r.profit_factor>=1 else 'negative'}">{r.profit_factor:.3f}</div></div>
    <div class="card"><div class="label">Total Trades</div>
      <div class="value neutral">{r.total_trades}</div></div>
    <div class="card"><div class="label">Sharpe</div>
      <div class="value {'positive' if r.sharpe_ratio>=1 else 'neutral' if r.sharpe_ratio>=0 else 'negative'}">{r.sharpe_ratio:.3f}</div></div>
    <div class="card"><div class="label">Sortino</div>
      <div class="value {'positive' if r.sortino_ratio>=1 else 'neutral' if r.sortino_ratio>=0 else 'negative'}">{r.sortino_ratio:.3f}</div></div>
    <div class="card"><div class="label">Calmar</div>
      <div class="value {'positive' if r.calmar_ratio>=0 else 'negative'}">{r.calmar_ratio:.3f}</div></div>
    <div class="card"><div class="label">SQN</div>
      <div class="value {'positive' if r.sqn>=1.6 else 'neutral' if r.sqn>=0 else 'negative'}">{r.sqn:.3f}</div></div>
    <div class="card"><div class="label">Expectancy</div>
      <div class="value {'positive' if r.expectancy>=0 else 'negative'}">${r.expectancy:+.2f}</div></div>
    <div class="card"><div class="label">Recovery Factor</div>
      <div class="value {'positive' if r.recovery_factor>=0 else 'negative'}">{r.recovery_factor:.3f}</div></div>
  </div>

  <h2>Equity Curve</h2>
  <div class="section" style="padding:10px">
    <canvas id="equityChart" height="80"></canvas>
  </div>

  <h2>Drawdown</h2>
  <div class="section" style="padding:10px">
    <canvas id="ddChart" height="40"></canvas>
  </div>

  <h2>Trade Log</h2>
  <div class="section">
    <table>
      <thead><tr>
        <th>#</th><th>Side</th><th>Entry</th><th>Entry Price</th>
        <th>Exit Price</th><th>Reason</th><th>Lots</th><th>Net PnL</th>
      </tr></thead>
      <tbody>{trade_rows}</tbody>
    </table>
  </div>

  <h2>Configuration</h2>
  <div class="section">
    <table>
      <thead><tr><th>Parameter</th><th>Value</th></tr></thead>
      <tbody>
        <tr><td>Symbol</td><td>{r.config.symbol}</td></tr>
        <tr><td>Initial Balance</td><td>${r.config.initial_balance:,.2f}</td></tr>
        <tr><td>Risk per Trade</td><td>{r.config.risk_per_trade_pct*100:.1f}%</td></tr>
        <tr><td>Min R:R Ratio</td><td>{r.config.min_rr_ratio}</td></tr>
        <tr><td>ATR SL Multiplier</td><td>{r.config.atr_sl_multiplier}×</td></tr>
        <tr><td>Spread</td><td>{r.config.spread_pips} pips</td></tr>
        <tr><td>Slippage</td><td>{r.config.slippage_pips} pips</td></tr>
        <tr><td>Commission</td><td>${r.config.commission_per_lot}/lot</td></tr>
        <tr><td>Min Confidence</td><td>{r.config.min_signal_confidence*100:.0f}%</td></tr>
        <tr><td>Require ADX above</td><td>{r.config.require_adx_above}</td></tr>
      </tbody>
    </table>
  </div>

{ReportGenerator._robustness_section(robustness_verdict, multi_symbol, walk_forward)}
</div>

<script>
const labels = {json.dumps(eq_labels)};
const equity = {json.dumps(eq_values)};
const dd     = {json.dumps(dd_values)};

new Chart(document.getElementById('equityChart'), {{
  type: 'line',
  data: {{ labels, datasets: [{{
    label: 'Equity ($)',
    data: equity,
    borderColor: '#2575fc',
    backgroundColor: 'rgba(37,117,252,0.1)',
    borderWidth: 1.5,
    pointRadius: 0,
    fill: true,
    tension: 0.1
  }}]}},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ labels: {{ color:'#ccc' }} }} }},
    scales: {{
      x: {{ ticks: {{ color:'#888', maxTicksLimit:12 }}, grid: {{ color:'#333' }} }},
      y: {{ ticks: {{ color:'#888' }}, grid: {{ color:'#333' }} }}
    }}
  }}
}});

new Chart(document.getElementById('ddChart'), {{
  type: 'line',
  data: {{ labels, datasets: [{{
    label: 'Drawdown (%)',
    data: dd.map(v => -v),
    borderColor: '#e74c3c',
    backgroundColor: 'rgba(231,76,60,0.15)',
    borderWidth: 1.5,
    pointRadius: 0,
    fill: true,
    tension: 0.1
  }}]}},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ labels: {{ color:'#ccc' }} }} }},
    scales: {{
      x: {{ ticks: {{ color:'#888', maxTicksLimit:12 }}, grid: {{ color:'#333' }} }},
      y: {{ ticks: {{ color:'#888', callback: v => v+'%' }}, grid: {{ color:'#333' }} }}
    }}
  }}
}});
</script>
</body>
</html>"""

        output_path.write_text(html, encoding='utf-8')
        print(f"HTML report saved: {output_path}")
        return output_path

    # ------------------------------------------------------------------
    # D3 — ROBUSTNESS SECTION HTML
    # ------------------------------------------------------------------

    @staticmethod
    def _robustness_section(
        rv:  Any = None,   # RobustnessVerdict | None
        ms:  Any = None,   # MultiSymbolSummary | None
        wf:  Any = None,   # WalkForwardSummary | None
    ) -> str:
        """Build the optional Robustez HTML section."""
        parts: List[str] = []

        # ── D1: IS vs OOS verdict ──────────────────────────────────────
        if rv is not None:
            badge_color = getattr(rv, 'color', '#aaa')
            reasons_html = "".join(
                f"<li>{r}</li>" for r in (rv.reasons or [])
            )
            parts.append(f"""
  <h2>Robustez — IS vs OOS (Anti-Overfitting)</h2>
  <div class="section">
    <div style="display:flex;align-items:center;gap:16px;margin-bottom:14px">
      <span style="background:{badge_color};color:#fff;padding:6px 18px;border-radius:20px;
                   font-weight:700;font-size:1rem;letter-spacing:1px">{rv.verdict}</span>
      <span style="color:#aaa;font-size:.85rem">Veredicto basado en comparación In-Sample vs Out-of-Sample</span>
    </div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:14px">
      <div class="card">
        <div class="label">IS Return</div>
        <div class="value {'positive' if rv.is_return >= 0 else 'negative'}">{rv.is_return:+.2f}%</div>
      </div>
      <div class="card">
        <div class="label">OOS Return</div>
        <div class="value {'positive' if rv.oos_return >= 0 else 'negative'}">{rv.oos_return:+.2f}%</div>
      </div>
      <div class="card">
        <div class="label">Efficiency Ratio</div>
        <div class="value {'positive' if rv.efficiency_ratio >= 0.6 else 'neutral' if rv.efficiency_ratio >= 0.3 else 'negative'}">{rv.efficiency_ratio:.3f}</div>
      </div>
      <div class="card">
        <div class="label">IS Sharpe</div>
        <div class="value {'positive' if rv.is_sharpe >= 0 else 'negative'}">{rv.is_sharpe:.3f}</div>
      </div>
      <div class="card">
        <div class="label">OOS Sharpe</div>
        <div class="value {'positive' if rv.oos_sharpe >= 0 else 'negative'}">{rv.oos_sharpe:.3f}</div>
      </div>
      <div class="card">
        <div class="label">Sharpe OOS/IS</div>
        <div class="value {'positive' if rv.sharpe_ratio_oos_vs_is >= 0.5 else 'neutral' if rv.sharpe_ratio_oos_vs_is >= 0.3 else 'negative'}">{rv.sharpe_ratio_oos_vs_is:.3f}</div>
      </div>
      <div class="card">
        <div class="label">IS Trades</div>
        <div class="value neutral">{rv.is_trades}</div>
      </div>
      <div class="card">
        <div class="label">OOS Trades</div>
        <div class="value neutral">{rv.oos_trades}</div>
      </div>
    </div>
    <div style="font-size:.82rem;color:#bbb">
      <strong style="color:#7ecff4">Diagnóstico:</strong>
      <ul style="margin-top:6px;padding-left:18px;line-height:1.8">{reasons_html}</ul>
    </div>
    <div style="margin-top:10px;font-size:.75rem;color:#666">
      Umbrales: Efficiency ≥ 0.60 + Sharpe OOS/IS ≥ 0.50 → ROBUST &nbsp;|&nbsp;
      Efficiency ≥ 0.30 o Sharpe ≥ 0.30 → WARNING &nbsp;|&nbsp; resto → OVERFIT
    </div>
  </div>""")

        # ── D2: Multi-symbol summary ──────────────────────────────────
        if ms is not None:
            badge_color = getattr(ms, 'color', '#aaa')
            rows_html = ""
            for msr in (ms.results or []):
                bt = msr.result
                status_color = "#27ae60" if msr.passed else "#e74c3c"
                status_text  = "PASS" if msr.passed else "FAIL"
                rows_html += f"""
              <tr>
                <td>{msr.symbol}</td>
                <td style="color:{status_color};font-weight:700">{status_text}</td>
                <td class="{'positive' if bt.total_return_pct >= 0 else 'negative'}">{bt.total_return_pct:+.2f}%</td>
                <td class="negative">-{bt.max_drawdown_pct:.2f}%</td>
                <td>{bt.win_rate:.1f}%</td>
                <td>{bt.profit_factor:.3f}</td>
                <td>{bt.total_trades}</td>
                <td class="{'positive' if bt.sharpe_ratio >= 0 else 'negative'}">{bt.sharpe_ratio:.3f}</td>
              </tr>"""
            parts.append(f"""
  <h2>Robustez — Multi-Instrumento</h2>
  <div class="section">
    <div style="display:flex;align-items:center;gap:16px;margin-bottom:14px">
      <span style="background:{badge_color};color:#fff;padding:6px 18px;border-radius:20px;
                   font-weight:700;font-size:1rem;letter-spacing:1px">{ms.verdict}</span>
      <span style="color:#aaa;font-size:.85rem">
        {ms.n_passed}/{ms.n_total} símbolos superaron el filtro ({ms.pass_rate:.1f}%)
      </span>
    </div>
    <table>
      <thead><tr>
        <th>Símbolo</th><th>Estado</th><th>Retorno</th><th>Max DD</th>
        <th>Win Rate</th><th>PF</th><th>Trades</th><th>Sharpe</th>
      </tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
    <div style="margin-top:10px;font-size:.75rem;color:#666">
      Umbrales: ≥70% pass → ROBUST &nbsp;|&nbsp; ≥50% pass → WARNING &nbsp;|&nbsp; &lt;50% → SYMBOL_SPECIFIC
    </div>
  </div>""")

        # ── Walk-Forward summary ───────────────────────────────────────
        if wf is not None:
            eff = wf.efficiency_ratio
            eff_color = "#27ae60" if eff >= 0.5 else "#f39c12" if eff >= 0.3 else "#e74c3c"
            wf_rows = ""
            for p in (wf.periods or []):
                wf_rows += f"""
              <tr>
                <td>P{p.period_id}</td>
                <td class="{'positive' if p.is_result.total_return_pct >= 0 else 'negative'}">{p.is_result.total_return_pct:+.2f}%</td>
                <td class="{'positive' if p.oos_result.total_return_pct >= 0 else 'negative'}">{p.oos_result.total_return_pct:+.2f}%</td>
                <td>{p.oos_result.win_rate:.1f}%</td>
                <td>{p.oos_result.profit_factor:.3f}</td>
                <td>{p.oos_result.total_trades}</td>
                <td style="font-size:.72rem;color:#aaa">{str(p.best_params)[:60]}</td>
              </tr>"""
            parts.append(f"""
  <h2>Robustez — Walk-Forward</h2>
  <div class="section">
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:14px">
      <div class="card">
        <div class="label">OOS Combinado</div>
        <div class="value {'positive' if wf.combined_oos_return >= 0 else 'negative'}">{wf.combined_oos_return:+.2f}%</div>
      </div>
      <div class="card">
        <div class="label">Efficiency Ratio</div>
        <div class="value" style="color:{eff_color}">{eff:.3f}</div>
      </div>
      <div class="card">
        <div class="label">OOS Trades</div>
        <div class="value neutral">{wf.combined_oos_trades}</div>
      </div>
      <div class="card">
        <div class="label">Avg OOS Win Rate</div>
        <div class="value {'positive' if wf.avg_oos_win_rate >= 50 else 'negative'}">{wf.avg_oos_win_rate:.1f}%</div>
      </div>
      <div class="card">
        <div class="label">Avg OOS PF</div>
        <div class="value {'positive' if wf.avg_oos_profit_factor >= 1 else 'negative'}">{wf.avg_oos_profit_factor:.3f}</div>
      </div>
    </div>
    <table>
      <thead><tr>
        <th>Periodo</th><th>IS Return</th><th>OOS Return</th>
        <th>OOS WR</th><th>OOS PF</th><th>OOS Trades</th><th>Params IS</th>
      </tr></thead>
      <tbody>{wf_rows}</tbody>
    </table>
    <div style="margin-top:10px;font-size:.75rem;color:#666">
      Efficiency &gt;0.5 = robusto &nbsp;|&nbsp; &lt;0.3 = probable overfitting
    </div>
  </div>""")

        if not parts:
            return ""
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# LEGACY FUNCTION (kept for compatibility)
# ---------------------------------------------------------------------------

def run_backtest(data, strategy) -> dict:
    """Legacy placeholder — use BacktestEngine for full functionality."""
    return {
        'trades': 0,
        'pnl': 0,
        'max_drawdown': 0,
        'notes': 'Use BacktestEngine for full backtesting functionality.'
    }


# ---------------------------------------------------------------------------
# STANDALONE TEST
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.WARNING)

    sys.path.insert(0, str(ROOT))
    from data.market_data import MarketDataProvider, DataSource, Timeframe

    print("Generating mock data...")
    provider = MarketDataProvider(primary_source=DataSource.MOCK)
    ohlcv    = provider.get_ohlcv('EURUSD', Timeframe.H1, bars=1000)

    if not ohlcv or len(ohlcv) < 100:
        print("ERROR: Not enough mock data")
        sys.exit(1)

    df = ohlcv_to_dataframe(ohlcv)
    print(f"Loaded {len(df)} bars")

    config = BacktestConfig(
        symbol               = 'EURUSD',
        initial_balance      = 10_000.0,
        risk_per_trade_pct   = 0.01,
        min_rr_ratio         = 1.5,
        spread_pips          = 1.0,
        slippage_pips        = 0.3,
        commission_per_lot   = 7.0,
        min_signal_confidence= 0.55,
        require_adx_above    = 18.0,
    )

    engine = BacktestEngine(config)
    result = engine.run(df, verbose=True)

    # Generate HTML report
    report_path = ReportGenerator.generate(result)
    print(f"\nOpen the report in your browser:\n  {report_path}")
