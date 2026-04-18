"""
Breakout Strategy
Detects consolidation ranges and trades breakouts with volume confirmation.

Logic:
  1. Identify consolidation range (N bars of compressed price action)
  2. Breakout confirmed when:
     - Price closes outside range high/low
     - ATR expansion (current ATR > avg ATR)
     - Volume spike (if available)
  3. SL inside the range; TP = SL distance × RR
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)

try:
    from ta.volatility import AverageTrueRange, BollingerBands
    from ta.volume import OnBalanceVolumeIndicator
    TA_AVAILABLE = True
except ImportError:
    TA_AVAILABLE = False

from strategies.technical_analysis import Signal


@dataclass
class BreakoutConfig:
    """Configuration for the breakout strategy."""
    consolidation_bars:   int   = 20     # Bars to define the range
    min_consolidation_pct: float = 0.003  # Min range height as % of price (noise filter)
    max_consolidation_pct: float = 0.025  # Max range — wider = not a consolidation
    atr_expansion_factor: float = 1.3    # Current ATR must be > factor × avg ATR
    volume_spike_factor:  float = 1.5    # Volume must be > factor × avg volume (0 = disabled)
    bb_squeeze_threshold: float = 0.6    # BB width below this → squeeze
    rr_ratio:             float = 2.0    # Risk:Reward ratio
    min_confidence:       float = 0.55


@dataclass
class BreakoutSignal:
    """Output from breakout strategy analysis."""
    signal:      Signal
    confidence:  float
    reason:      str
    range_high:  Optional[float] = None
    range_low:   Optional[float] = None
    entry_price: Optional[float] = None
    stop_loss:   Optional[float] = None
    take_profit: Optional[float] = None


class BreakoutStrategy:
    """
    Breakout strategy with BB squeeze detection and volume confirmation.
    """

    def __init__(self, config: BreakoutConfig = None):
        self.config = config or BreakoutConfig()

    def analyze(self, df: pd.DataFrame) -> BreakoutSignal:
        """
        Analyze for breakout opportunities.

        Args:
            df: OHLCV DataFrame indexed by timestamp

        Returns:
            BreakoutSignal with signal, confidence, and trade parameters
        """
        if not TA_AVAILABLE:
            return BreakoutSignal(Signal.NEUTRAL, 0.0, "ta library not available")

        n = len(df)
        cfg = self.config
        lb  = cfg.consolidation_bars

        if n < lb + 10:
            return BreakoutSignal(Signal.NEUTRAL, 0.0, "Insufficient data")

        close  = df['close']
        high   = df['high']
        low    = df['low']
        vol    = df['volume'] if 'volume' in df.columns else pd.Series(np.zeros(n), index=df.index)

        current_price = float(close.iloc[-1])
        current_bar   = df.iloc[-1]

        # --- Consolidation range (excluding last bar) ---
        range_window_high = df['high'].iloc[-(lb+1):-1]
        range_window_low  = df['low'].iloc[-(lb+1):-1]
        range_high = float(range_window_high.max())
        range_low  = float(range_window_low.min())
        range_height = range_high - range_low
        range_pct    = range_height / current_price

        # Filter: range must be in sweet spot (not too tight, not too wide)
        if range_pct < cfg.min_consolidation_pct:
            return BreakoutSignal(Signal.NEUTRAL, 0.0,
                                  f"Range too tight ({range_pct*100:.3f}%)")
        if range_pct > cfg.max_consolidation_pct:
            return BreakoutSignal(Signal.NEUTRAL, 0.0,
                                  f"Range too wide ({range_pct*100:.3f}%)")

        # --- ATR expansion ---
        atr_obj  = AverageTrueRange(high=high, low=low, close=close, window=14)
        atr_vals = atr_obj.average_true_range()
        current_atr = float(atr_vals.iloc[-1])
        avg_atr     = float(atr_vals.iloc[-(lb+1):-1].mean())
        atr_expanded = current_atr > avg_atr * cfg.atr_expansion_factor

        # --- Bollinger Band squeeze check ---
        bb = BollingerBands(close=close, window=20, window_dev=2)
        bb_width = float(bb.bollinger_wband().iloc[-1])
        bb_squeeze_detected = bb_width < cfg.bb_squeeze_threshold

        # --- Volume spike ---
        avg_vol = float(vol.iloc[-(lb+1):-1].mean()) if vol.sum() > 0 else 0
        current_vol = float(vol.iloc[-1]) if vol.sum() > 0 else 0
        vol_spike = (cfg.volume_spike_factor <= 0 or avg_vol == 0 or
                     current_vol > avg_vol * cfg.volume_spike_factor)

        # --- Breakout detection ---
        breakout_up   = float(close.iloc[-1]) > range_high
        breakout_down = float(close.iloc[-1]) < range_low

        if not (breakout_up or breakout_down):
            # Check for near-breakout (within 0.1% of range boundary)
            near_high = (range_high - current_price) / current_price < 0.001
            near_low  = (current_price - range_low)  / current_price < 0.001
            if near_high or near_low:
                return BreakoutSignal(Signal.NEUTRAL, 0.3,
                                      f"Near breakout zone [{range_low:.5f}–{range_high:.5f}]",
                                      range_high=range_high, range_low=range_low)
            return BreakoutSignal(Signal.NEUTRAL, 0.0,
                                  f"Inside range [{range_low:.5f}–{range_high:.5f}]",
                                  range_high=range_high, range_low=range_low)

        # --- Confidence scoring ---
        confidence_factors = []

        # ATR expansion adds confidence
        if atr_expanded:
            confidence_factors.append(0.30)
        else:
            confidence_factors.append(0.10)

        # BB squeeze → high-quality breakout
        if bb_squeeze_detected:
            confidence_factors.append(0.25)

        # Volume confirmation
        if vol_spike:
            confidence_factors.append(0.25)
        else:
            confidence_factors.append(0.10)

        # Breakout magnitude: further from range = more confidence
        if breakout_up:
            extra_pct = (current_price - range_high) / range_height
        else:
            extra_pct = (range_low - current_price) / range_height
        magnitude_score = min(extra_pct * 0.5, 0.20)
        confidence_factors.append(magnitude_score)

        confidence = min(sum(confidence_factors), 1.0)

        # --- Build trade params ---
        sl_buffer  = current_atr * 0.5
        tp_rr      = cfg.rr_ratio

        if breakout_up:
            sl    = range_low - sl_buffer        # SL below range low
            tp    = current_price + (current_price - sl) * tp_rr
            signal = Signal.STRONG_BUY if confidence >= 0.70 else Signal.BUY
            reason = (f"Breakout UP above {range_high:.5f}"
                      + (" | ATR expanded" if atr_expanded else "")
                      + (" | BB squeeze" if bb_squeeze_detected else "")
                      + (" | Vol spike" if vol_spike else ""))
        else:
            sl    = range_high + sl_buffer       # SL above range high
            tp    = current_price - (sl - current_price) * tp_rr
            signal = Signal.STRONG_SELL if confidence >= 0.70 else Signal.SELL
            reason = (f"Breakout DOWN below {range_low:.5f}"
                      + (" | ATR expanded" if atr_expanded else "")
                      + (" | BB squeeze" if bb_squeeze_detected else "")
                      + (" | Vol spike" if vol_spike else ""))

        if confidence < cfg.min_confidence:
            return BreakoutSignal(Signal.NEUTRAL, confidence,
                                  f"Breakout detected but confidence too low ({confidence*100:.1f}%)",
                                  range_high=range_high, range_low=range_low)

        return BreakoutSignal(
            signal      = signal,
            confidence  = round(confidence, 3),
            reason      = reason,
            range_high  = range_high,
            range_low   = range_low,
            entry_price = round(current_price, 5),
            stop_loss   = round(sl, 5),
            take_profit = round(tp, 5)
        )


# ---------------------------------------------------------------------------
# STANDALONE TEST
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

    import logging
    logging.basicConfig(level=logging.INFO)

    from data.market_data import MarketDataProvider, DataSource, Timeframe
    from strategies.technical_analysis import ohlcv_to_dataframe

    provider = MarketDataProvider(primary_source=DataSource.MOCK)
    ohlcv    = provider.get_ohlcv('EURUSD', Timeframe.H1, bars=300)
    df = ohlcv_to_dataframe(ohlcv)

    strat  = BreakoutStrategy()
    result = strat.analyze(df)

    print("Breakout Strategy Test")
    print("=" * 50)
    print(f"Signal:     {result.signal.value}")
    print(f"Confidence: {result.confidence*100:.1f}%")
    print(f"Reason:     {result.reason}")
    if result.range_high:
        print(f"Range:      [{result.range_low:.5f} – {result.range_high:.5f}]")
    if result.stop_loss:
        print(f"SL:         {result.stop_loss:.5f}")
        print(f"TP:         {result.take_profit:.5f}")
