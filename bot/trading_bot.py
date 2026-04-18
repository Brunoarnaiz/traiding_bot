"""
Professional Trading Bot — Main Runner
Uses StrategySelector to aggregate signals from:
  - TechnicalAnalysis (multi-indicator weighted scoring)
  - BreakoutStrategy  (BB squeeze + ATR expansion + volume)
  - MeanReversionStrategy (Z-score + RSI + Stoch in ranging markets)
"""
import time
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional
import logging
from dataclasses import dataclass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.market_data import MarketDataProvider, DataSource, Timeframe
from strategies.technical_analysis import ohlcv_to_dataframe, Signal
from strategies.strategy_selector import StrategySelector, AggregatedSignal
from risk.risk_manager import RiskManager, RiskLimits, RiskLevel, AccountState
from bot.mt5_file_bridge import MT5Bridge
from utils.position_tracker import PositionTracker, Position

logger = logging.getLogger(__name__)

INITIAL_BALANCE = 10_000.0   # Default demo balance


@dataclass
class BotConfig:
    """Bot configuration"""
    symbol:                 str       = "EURUSD"
    timeframe:              Timeframe = Timeframe.M15
    check_interval_seconds: int       = 300
    risk_level:             RiskLevel = RiskLevel.MODERATE
    max_open_positions:     int       = 4     # Maximum simultaneous open trades
    max_trades_per_day:     int       = 10
    demo_mode:              bool      = True  # SAFE: always start in demo mode
    min_signal_confidence:  float     = 0.55
    # Phase A — Exit management
    trailing_stop_pips:     float     = 0.0   # A1: 0 = disabled. Pips behind price for trailing SL
    breakeven_trigger_pips: float     = 0.0   # A3: 0 = disabled. Pips profit to move SL to entry
    trailing_ma_period:     int       = 0     # A2: 0 = disabled. EMA period for MA-based trailing SL
    # Phase E — Risk rules
    daily_loss_limit_pct:   float     = 0.05  # E2: Stop bot for today if daily loss exceeds this %


class TradingBot:
    """
    Professional trading bot driven by StrategySelector.

    The selector runs three strategies in parallel and weights their
    signals according to the detected market regime:
      - Trending  → TechnicalAnalysis dominates
      - Ranging   → MeanReversion dominates
      - Breakout  → BreakoutStrategy dominates

    AccountState is refreshed before every trade evaluation so the
    open-position gate always reflects the real current state.
    """

    def __init__(self, config: BotConfig):
        self.config = config
        self.running = False

        # Core components
        self.bridge           = MT5Bridge()
        self.data_provider    = MarketDataProvider(
            primary_source=DataSource.MT5_TERMINAL,
            bridge=self.bridge,
        )
        self.selector         = StrategySelector()
        self.position_tracker = PositionTracker(ROOT / 'data' / 'positions.json')

        # Risk manager — override limits from BotConfig
        limits = RiskLimits.from_risk_level(config.risk_level)
        limits.max_open_positions     = config.max_open_positions
        limits.max_consecutive_losses = 20                       # Demo: no paramos por rachas
        limits.daily_loss_limit_pct   = config.daily_loss_limit_pct  # E2: from config
        self.risk_manager = RiskManager(limits)

        # Runtime state
        self.trades_today:     int              = 0
        self.last_signal:      Signal           = Signal.NEUTRAL
        self.last_check_time:  Optional[datetime] = None

        logger.info(f"TradingBot initialised: {config.symbol} {config.timeframe.value}")
        logger.info(f"Risk: {config.risk_level.value} | Max positions: {config.max_open_positions}"
                    f" | Demo: {config.demo_mode}")

    # ------------------------------------------------------------------
    # LIFECYCLE
    # ------------------------------------------------------------------

    def start(self):
        """Start the bot. Blocks until stopped."""
        logger.info("=" * 60)
        logger.info("Trading Bot Starting...")
        logger.info("=" * 60)

        if not self.bridge.check_connection():
            logger.error("MT5 Bridge not responding — is NixBridge_v2 loaded?")
            return

        logger.info("MT5 Bridge connected (PING OK)")

        # Initial account state
        self._refresh_account_state()

        self.running = True
        try:
            self._run_loop()
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as e:
            logger.error(f"Bot crashed: {e}", exc_info=True)
        finally:
            self.stop()

    def stop(self):
        self.running = False
        logger.info("Bot stopped")

    def _run_loop(self):
        # If positions are already open on startup, wait one full interval
        # before the first check — prevents opening a duplicate trade on every restart
        open_on_start = self.position_tracker.get_open_positions()
        if open_on_start:
            logger.info(
                f"Found {len(open_on_start)} open position(s) on startup — "
                f"waiting {self.config.check_interval_seconds}s before first check"
            )
            time.sleep(self.config.check_interval_seconds)

        while self.running:
            try:
                self.check_market()
                time.sleep(self.config.check_interval_seconds)
            except Exception as e:
                logger.error(f"Loop error: {e}", exc_info=True)
                time.sleep(60)

    # ------------------------------------------------------------------
    # ACCOUNT STATE — always fresh before trading decisions
    # ------------------------------------------------------------------

    def _refresh_account_state(self):
        """
        Rebuild AccountState from current position tracker + MT5 (live mode).

        Called before every trade evaluation to ensure open_positions,
        daily_pnl, and consecutive_losses are accurate.
        In live mode: reconciles tracker with actual MT5 positions via bridge.
        """
        if not self.config.demo_mode:
            self._sync_live_positions()

        open_positions    = self.position_tracker.get_open_positions()
        closed_positions  = self.position_tracker.get_closed_positions()
        daily_pnl         = self.position_tracker.get_daily_pnl()

        # Consecutive losses streak (most recent first)
        consecutive_losses = 0
        for pos in reversed(closed_positions):
            if pos.pnl is not None and pos.pnl < 0:
                consecutive_losses += 1
            else:
                break

        today = datetime.now().date()
        trades_today = sum(
            1 for p in closed_positions
            if p.exit_time and datetime.fromisoformat(p.exit_time).date() == today
        )

        self.trades_today = trades_today

        self.risk_manager.set_account_state(AccountState(
            balance            = INITIAL_BALANCE,
            equity             = INITIAL_BALANCE + daily_pnl,
            open_positions     = len(open_positions),
            daily_pnl          = daily_pnl,
            consecutive_losses = consecutive_losses,
            trades_today       = trades_today,
        ))

        logger.info(
            f"Account state: open={len(open_positions)}/{self.config.max_open_positions}"
            f" | daily_pnl=${daily_pnl:.2f}"
            f" | loss_streak={consecutive_losses}"
        )

    def _sync_live_positions(self):
        """
        In live mode: two-way reconciliation between tracker and MT5.
        1. Positions MT5 closed (SL/TP hit)  → mark closed in tracker.
        2. Positions open in MT5 but missing from tracker → add them.
           (Happens when a previous bot run failed to record the order.)
        """
        try:
            mt5_positions = self.bridge.get_positions()
            mt5_by_ticket = {str(p['ticket']): p for p in mt5_positions}

            # 1. Close tracker positions that MT5 no longer has
            for pos in self.position_tracker.get_open_positions():
                ticket = pos.position_id.split('_')[-1]
                if ticket not in mt5_by_ticket:
                    logger.info(f"Position {pos.position_id} closed by MT5, updating tracker")
                    self.position_tracker.close_position(pos.position_id, 0.0, 0.0)

            # 2. Add MT5 positions missing from tracker
            tracked_tickets = {
                pos.position_id.split('_')[-1]
                for pos in self.position_tracker.get_open_positions()
            }
            for ticket_str, p in mt5_by_ticket.items():
                if ticket_str not in tracked_tickets:
                    logger.info(f"Recovering untracked MT5 position #{ticket_str} into tracker")
                    from utils.position_tracker import Position
                    pos = Position(
                        position_id      = f"LIVE_RECOVERED_{ticket_str}",
                        symbol           = p['symbol'],
                        side             = p['side'],
                        entry_price      = p['open_price'],
                        lot_size         = p['lot'],
                        stop_loss        = p['sl'],
                        take_profit      = p['tp'],
                        entry_time       = datetime.now().isoformat(),
                        risk_amount      = 0.0,
                        potential_profit = 0.0,
                    )
                    self.position_tracker.add_position(pos)
        except Exception as e:
            logger.warning(f"Live sync failed (non-critical): {e}")

    # ------------------------------------------------------------------
    # MARKET CHECK
    # ------------------------------------------------------------------

    def check_market(self):
        """Fetch data, run strategy selector, execute if conditions met."""
        now = datetime.now()
        logger.info(f"\n{'='*60}")
        logger.info(f"Market Check: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'='*60}")

        # Refresh state BEFORE evaluating signals
        self._refresh_account_state()

        # Fetch data
        ohlcv = self.data_provider.get_ohlcv(
            self.config.symbol, self.config.timeframe, bars=300
        )
        if not ohlcv or len(ohlcv) < 60:
            logger.warning("Insufficient market data")
            return

        logger.info(f"Received {len(ohlcv)} bars")
        df = ohlcv_to_dataframe(ohlcv)

        # Phase A — manage exits on open positions BEFORE evaluating new entries
        price_tick = self.bridge.get_price(self.config.symbol)
        if price_tick:
            mid_price = (price_tick.get('bid', 0) + price_tick.get('ask', 0)) / 2
            if mid_price > 0:
                self._manage_open_positions(mid_price, df)

        # Run strategy selector
        agg: AggregatedSignal = self.selector.select(df)

        # Log market state
        price = agg.current_price or 0.0
        logger.info(
            f"\nMarket State:"
            f"\n  Price:  {price:.5f}"
            f"\n  RSI:    {f'{agg.rsi:.2f}' if agg.rsi else 'N/A'}"
            f"\n  ADX:    {f'{agg.adx:.2f}' if agg.adx else 'N/A'}"
            f"\n  ATR:    {f'{agg.atr:.5f}' if agg.atr else 'N/A'}"
            f"\n  Regime: {agg.regime.value}"
        )
        logger.info(
            f"\nStrategy Breakdown:"
            f"\n  TechnicalAnalysis: {agg.ta_signal.value if agg.ta_signal else 'N/A'}"
            f" ({(agg.ta_confidence or 0)*100:.0f}%)"
            f"\n  BreakoutStrategy:  {agg.bo_signal.value if agg.bo_signal else 'N/A'}"
            f" ({(agg.bo_confidence or 0)*100:.0f}%)"
            f"\n  MeanReversion:     {agg.mr_signal.value if agg.mr_signal else 'N/A'}"
            f" ({(agg.mr_confidence or 0)*100:.0f}%)"
            f"\n  MACrossover (B1):  {agg.mac_signal.value if agg.mac_signal else 'N/A'}"
            f" ({(agg.mac_confidence or 0)*100:.0f}%)"
            f"\n  Momentum  (B2):    {agg.mom_signal.value if agg.mom_signal else 'N/A'}"
            f" ({(agg.mom_confidence or 0)*100:.0f}%)"
            f"\n  GuideStrat(B3):    {agg.gs_signal.value if agg.gs_signal else 'N/A'}"
            f" ({(agg.gs_confidence or 0)*100:.0f}%)"
            f"\n  Active Strategy:   {agg.active_strategy}"
        )
        logger.info(
            f"\nFinal Signal: {agg.signal.value}"
            f" (confidence: {agg.confidence*100:.1f}%)"
            f"\n  Reason: {agg.reason}"
        )

        # Execute
        if agg.signal in (Signal.STRONG_BUY, Signal.BUY):
            self._execute_trade(agg, "BUY")
        elif agg.signal in (Signal.STRONG_SELL, Signal.SELL):
            self._execute_trade(agg, "SELL")
        else:
            logger.info("  -> No action (neutral signal)")

        self.last_check_time = now
        self.last_signal = agg.signal

    # ------------------------------------------------------------------
    # PHASE A — EXIT MANAGEMENT (Trailing Stop, Breakeven, MA Trail)
    # ------------------------------------------------------------------

    def _manage_open_positions(self, current_price: float, df=None):
        """
        Called on every check_market() cycle BEFORE evaluating new entries.

        Applies, in order:
          A3 — Breakeven: move SL to entry once profit target is reached
          A1 — Trailing Stop: SL follows price, only moves in our favour
          A2 — MA Trailing: SL = EMA level (closes when price crosses EMA)

        In demo mode: updates the position tracker (no MT5 call).
        In live mode: also sends MODIFY command to MT5 via bridge.
        """
        pip = 0.0001
        open_positions = self.position_tracker.get_open_positions()
        if not open_positions:
            return

        # Compute EMA for MA trailing if configured (A2)
        current_ema = None
        if self.config.trailing_ma_period > 0 and df is not None:
            ema_series = df['close'].ewm(
                span=self.config.trailing_ma_period, adjust=False
            ).mean()
            current_ema = float(ema_series.iloc[-1])

        for pos in open_positions:
            original_sl = pos.stop_loss
            new_sl = pos.stop_loss

            # A3 — Breakeven
            if self.config.breakeven_trigger_pips > 0 and not pos.breakeven_activated:
                if pos.side == "BUY":
                    profit_pips = (current_price - pos.entry_price) / pip
                else:
                    profit_pips = (pos.entry_price - current_price) / pip

                if profit_pips >= self.config.breakeven_trigger_pips:
                    new_sl = pos.entry_price
                    pos.breakeven_activated = True
                    logger.info(
                        f"  BREAKEVEN activated for {pos.position_id}: "
                        f"SL moved to entry {pos.entry_price:.5f} "
                        f"(profit was {profit_pips:.1f} pips)"
                    )

            # A1 — Trailing Stop (applied after breakeven, takes higher value for BUY)
            if self.config.trailing_stop_pips > 0:
                trail_dist = self.config.trailing_stop_pips * pip
                if pos.side == "BUY":
                    candidate = current_price - trail_dist
                    new_sl = max(new_sl, candidate)
                else:
                    candidate = current_price + trail_dist
                    new_sl = min(new_sl, candidate)

            # A2 — MA Trailing
            if current_ema is not None:
                if pos.side == "BUY":
                    new_sl = max(new_sl, round(current_ema, 5))
                else:
                    new_sl = min(new_sl, round(current_ema, 5))

            # Only update if SL improved
            sl_moved = abs(new_sl - original_sl) > pip * 0.1
            if sl_moved:
                pos.stop_loss = round(new_sl, 5)
                logger.info(
                    f"  SL updated for {pos.position_id} ({pos.side}): "
                    f"{original_sl:.5f} → {new_sl:.5f}"
                )

                # Live mode: send MODIFY to MT5
                if not self.config.demo_mode:
                    ticket_str = pos.position_id.split('_')[-1]
                    try:
                        ticket = int(ticket_str)
                        result = self.bridge.modify_sl(ticket, new_sl, pos.take_profit)
                        if not result.get('success'):
                            logger.warning(
                                f"  MODIFY failed for ticket {ticket}: {result.get('error')}"
                            )
                    except (ValueError, AttributeError) as e:
                        logger.warning(f"  Could not send MODIFY (no ticket): {e}")

            # Demo mode: check if SL/TP hit at current price
            if self.config.demo_mode:
                hit = False
                exit_price = current_price
                exit_reason = ""

                if pos.side == "BUY":
                    if current_price <= pos.stop_loss:
                        hit = True
                        exit_price = pos.stop_loss
                        exit_reason = "TRAILING_SL" if (
                            pos.breakeven_activated
                            or self.config.trailing_stop_pips > 0
                            or self.config.trailing_ma_period > 0
                        ) else "SL"
                    elif current_price >= pos.take_profit:
                        hit = True
                        exit_price = pos.take_profit
                        exit_reason = "TP"
                else:
                    if current_price >= pos.stop_loss:
                        hit = True
                        exit_price = pos.stop_loss
                        exit_reason = "TRAILING_SL" if (
                            pos.breakeven_activated
                            or self.config.trailing_stop_pips > 0
                            or self.config.trailing_ma_period > 0
                        ) else "SL"
                    elif current_price <= pos.take_profit:
                        hit = True
                        exit_price = pos.take_profit
                        exit_reason = "TP"

                if hit:
                    pnl_pips = (
                        (exit_price - pos.entry_price) / pip
                        if pos.side == "BUY"
                        else (pos.entry_price - exit_price) / pip
                    )
                    pnl = pnl_pips * 10.0 * pos.lot_size  # $10/pip/lot
                    self.position_tracker.close_position(pos.position_id, exit_price, pnl)
                    logger.info(
                        f"  DEMO CLOSED {pos.position_id} [{exit_reason}] "
                        f"@ {exit_price:.5f}  PnL: ${pnl:.2f}"
                    )
                else:
                    # Persist updated SL / breakeven_activated flag
                    self.position_tracker.save()

    # ------------------------------------------------------------------
    # TRADE EXECUTION
    # ------------------------------------------------------------------

    def _execute_trade(self, agg: AggregatedSignal, side: str):
        """Evaluate all gates and open a trade if approved."""
        logger.info(f"\nEvaluating {side} opportunity...")

        # 1. Confidence gate - USE CONFIG VALUE NOT HARDCODED
        is_strong = agg.signal in (Signal.STRONG_BUY, Signal.STRONG_SELL)
        min_conf  = self.config.min_signal_confidence  # Use config value!
        if agg.confidence < min_conf:
            logger.info(f"  Skipped: confidence {agg.confidence*100:.1f}% < {min_conf*100:.0f}%")
            return

        # 2. Price sanity
        if not agg.current_price or agg.current_price == 0.0:
            logger.warning("  No valid price from MT5 — skipping trade")
            return

        # 3. Risk manager gate (checks open_positions, daily_pnl, streak)
        can_trade, reason = self.risk_manager.can_open_trade()
        if not can_trade:
            logger.info(f"  Skipped by risk manager: {reason}")
            return

        # 4. Build position — prefer strategy SL/TP, fall back to ATR if E1/E3 rejects it
        #    This ensures a good signal from any of the 6 strategies is never lost
        #    just because the strategy-computed SL/TP fails the R:R gate.
        #
        #    Spread adjustment: strategies compute SL/TP from the last bar close.
        #    In live mode the actual entry is ask = close + spread, so we shift
        #    the strategy SL/TP by the spread delta to keep distances consistent.
        spread_pip = 0.0001  # 1 pip spread estimate; MT5 bid/ask is already reflected in bridge
        sl_override = agg.stop_loss
        tp_override = agg.take_profit
        if sl_override and tp_override and not self.config.demo_mode:
            spread_offset = spread_pip  # BUY entry is higher → SL and TP shift up
            if side == "BUY":
                sl_override = round(sl_override + spread_offset, 5)
                tp_override = round(tp_override + spread_offset, 5)
            else:
                sl_override = round(sl_override - spread_offset, 5)
                tp_override = round(tp_override - spread_offset, 5)

        has_strategy_sl_tp = bool(sl_override and tp_override)

        position = self.risk_manager.create_trade_position(
            symbol               = self.config.symbol,
            side                 = side,
            entry_price          = agg.current_price,
            atr                  = agg.atr,
            stop_loss_override   = sl_override if has_strategy_sl_tp else None,
            take_profit_override = tp_override if has_strategy_sl_tp else None,
        )

        # Phase G: if strategy SL/TP was rejected (E1 or E3), retry with ATR-based params
        if position is None and has_strategy_sl_tp:
            logger.info(
                f"  Strategy SL/TP rejected — retrying with ATR-based params "
                f"(strategy: {agg.active_strategy})"
            )
            position = self.risk_manager.create_trade_position(
                symbol      = self.config.symbol,
                side        = side,
                entry_price = agg.current_price,
                atr         = agg.atr,
            )

        if position is None:
            logger.warning("  Skipped: risk manager could not build position")
            return

        self._open_position(position, agg)

    def _open_position(self, position, agg: AggregatedSignal):
        """Send the order (demo or live) and persist it."""
        side = position.side

        if self.config.demo_mode:
            logger.info(
                f"\nDEMO  {side} {position.lot_size} lots {position.symbol}"
                f" @ {position.entry_price:.5f}"
                f"\n  SL: {position.stop_loss:.5f} | TP: {position.take_profit:.5f}"
                f"\n  Risk: ${position.risk_amount:.2f} | Potential: ${position.potential_profit:.2f}"
                f"\n  Strategy: {agg.active_strategy} | Regime: {agg.regime.value}"
            )
            self._track_position(position, mt5_ticket=None)

        else:
            logger.info(f"\nLIVE  {side} {position.lot_size} lots {position.symbol}...")
            result = self.bridge.send_market_order(
                symbol      = position.symbol,
                side        = position.side,
                lot         = position.lot_size,
                stop_loss   = position.stop_loss,
                take_profit = position.take_profit,
            )
            if result['success']:
                ticket = result.get('ticket')
                logger.info(f"  Order executed — ticket: {ticket}"
                            f" price: {result.get('price')}")
                self.trades_today += 1
                self._track_position(position, mt5_ticket=ticket)
            else:
                logger.error(f"  Order failed: {result['error']}")

    def _track_position(self, position, mt5_ticket: Optional[int]):
        """Save position to tracker. In live mode, embeds MT5 ticket in position_id."""
        if mt5_ticket:
            position_id = f"LIVE_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{mt5_ticket}"
        else:
            position_id = self.position_tracker.generate_position_id()

        pos = Position(
            position_id      = position_id,
            symbol           = position.symbol,
            side             = position.side,
            entry_price      = position.entry_price,
            lot_size         = position.lot_size,
            stop_loss        = position.stop_loss,
            take_profit      = position.take_profit,
            entry_time       = datetime.now().isoformat(),
            risk_amount      = position.risk_amount,
            potential_profit = position.potential_profit,
        )
        self.position_tracker.add_position(pos)
        logger.info(f"  Tracked: {pos.position_id}")


# ------------------------------------------------------------------
# ENTRY POINT
# ------------------------------------------------------------------

def main():
    log_dir  = ROOT / 'logs'
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f'bot_{datetime.now().strftime("%Y%m%d")}.log'

    logging.basicConfig(
        level    = logging.INFO,
        format   = '%(asctime)s %(levelname)-8s %(message)s',
        handlers = [
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ]
    )

    config = BotConfig(
        symbol                 = "EURUSD",
        timeframe              = Timeframe.M15,
        check_interval_seconds = 300,
        risk_level             = RiskLevel.MODERATE,
        max_open_positions     = 4,
        min_signal_confidence  = 0.01,
        demo_mode              = False,
        # Phase A — exit management
        trailing_stop_pips     = 15.0,   # A1: trail SL 15 pips behind price
        breakeven_trigger_pips = 10.0,   # A3: move SL to entry after 10 pips profit
        trailing_ma_period     = 0,      # A2: disabled by default (set e.g. 21 to enable)
        # Phase E — risk rules
        daily_loss_limit_pct   = 0.05,   # E2: stop trading today after 5% daily loss
    )

    TradingBot(config).start()


if __name__ == '__main__':
    main()
