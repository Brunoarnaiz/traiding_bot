"""
Mean Reversion Strategy
Trades pullbacks to the mean in ranging/high-volatility markets.

Logic:
  1. Confirm ranging market (ADX < threshold, low trend strength)
  2. Price deviates significantly from mean (Z-score or BB %B)
  3. Momentum shows exhaustion (RSI/Stoch oversold-overbought)
  4. Enter toward mean with tight SL beyond recent extreme
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)

try:
    from ta.volatility import BollingerBands, AverageTrueRange
    from ta.momentum import RSIIndicator, StochasticOscillator
    from ta.trend import ADXIndicator, EMAIndicator
    TA_AVAILABLE = True
except ImportError:
    TA_AVAILABLE = False

from strategies.technical_analysis import Signal


@dataclass
class MeanReversionConfig:
    """Configuration for the mean reversion strategy."""
    max_adx_threshold:     float = 28.0    # Only trade when market is ranging (ADX < this)
    zscore_entry:          float = 2.0     # Enter when |Z-score| > this (2σ from mean)
    zscore_lookback:       int   = 20      # Lookback for Z-score calculation
    rsi_oversold:          float = 35.0
    rsi_overbought:        float = 65.0
    stoch_oversold:        float = 25.0
    stoch_overbought:      float = 75.0
    bb_extreme_pct:        float = 0.10    # %B below this = oversold; above (1-this) = overbought
    atr_sl_multiplier:     float = 1.5     # SL = N × ATR beyond the extreme
    rr_ratio:              float = 1.5     # Risk:Reward ratio (mean reversion usually tighter)
    min_confidence:        float = 0.55
    # Mean target
    mean_window:           int   = 20      # EMA window for the "mean"


@dataclass
class MeanReversionSignal:
    """Output from mean reversion analysis."""
    signal:      Signal
    confidence:  float
    reason:      str
    zscore:      Optional[float] = None
    mean_price:  Optional[float] = None
    entry_price: Optional[float] = None
    stop_loss:   Optional[float] = None
    take_profit: Optional[float] = None


class MeanReversionStrategy:
    """
    Mean reversion strategy suitable for ranging markets.

    Uses Z-score, Bollinger %B, RSI, and Stochastic for signal generation.
    Includes an ADX filter to avoid trending environments.
    """

    def __init__(self, config: MeanReversionConfig = None):
        self.config = config or MeanReversionConfig()

    def analyze(self, df: pd.DataFrame) -> MeanReversionSignal:
        """
        Analyze for mean reversion opportunities.

        Args:
            df: OHLCV DataFrame indexed by timestamp

        Returns:
            MeanReversionSignal with signal, confidence, and trade parameters
        """
        if not TA_AVAILABLE:
            return MeanReversionSignal(Signal.NEUTRAL, 0.0, "ta library not available")

        cfg = self.config
        n   = len(df)
        lb  = max(cfg.zscore_lookback, cfg.mean_window, 20)

        if n < lb + 10:
            return MeanReversionSignal(Signal.NEUTRAL, 0.0, "Insufficient data")

        close  = df['close']
        high   = df['high']
        low    = df['low']

        current_price = float(close.iloc[-1])

        # --- ADX filter: only trade in ranging markets ---
        if n >= 28:
            adx_obj = ADXIndicator(high=high, low=low, close=close, window=14)
            adx     = float(adx_obj.adx().iloc[-1])
            if adx >= cfg.max_adx_threshold:
                return MeanReversionSignal(Signal.NEUTRAL, 0.0,
                                           f"Market trending (ADX={adx:.1f} ≥ {cfg.max_adx_threshold})")
        else:
            adx = None

        # --- Z-score ---
        window_close = close.iloc[-cfg.zscore_lookback:]
        mean_val = float(window_close.mean())
        std_val  = float(window_close.std())
        zscore   = (current_price - mean_val) / std_val if std_val > 0 else 0.0

        # --- EMA (mean target) ---
        ema_mean = float(EMAIndicator(close=close, window=cfg.mean_window).ema_indicator().iloc[-1])

        # --- Bollinger %B ---
        bb = BollingerBands(close=close, window=20, window_dev=2)
        bb_pct = float(bb.bollinger_pband().iloc[-1])
        bb_upper = float(bb.bollinger_hband().iloc[-1])
        bb_lower = float(bb.bollinger_lband().iloc[-1])

        # --- RSI ---
        rsi = None
        if n >= 15:
            rsi = float(RSIIndicator(close=close, window=14).rsi().iloc[-1])

        # --- Stochastic ---
        stoch_k = stoch_d = None
        if n >= 17:
            stoch   = StochasticOscillator(high=high, low=low, close=close, window=14, smooth_window=3)
            stoch_k = float(stoch.stoch().iloc[-1])
            stoch_d = float(stoch.stoch_signal().iloc[-1])

        # --- ATR for SL ---
        atr = None
        if n >= 15:
            atr = float(AverageTrueRange(high=high, low=low, close=close, window=14)
                        .average_true_range().iloc[-1])

        # --- Signal logic ---
        bull_score = 0.0   # Evidence for long (price too low → revert up)
        bear_score = 0.0   # Evidence for short (price too high → revert down)
        reasons_bull = []
        reasons_bear = []

        # Z-score
        if zscore <= -cfg.zscore_entry:
            bull_score += 0.35
            reasons_bull.append(f"Z-score={zscore:.2f} (oversold)")
        elif zscore >= cfg.zscore_entry:
            bear_score += 0.35
            reasons_bear.append(f"Z-score={zscore:.2f} (overbought)")

        # Bollinger %B
        if bb_pct <= cfg.bb_extreme_pct:
            bull_score += 0.25
            reasons_bull.append(f"BB %B={bb_pct:.2f} (at lower band)")
        elif bb_pct >= (1 - cfg.bb_extreme_pct):
            bear_score += 0.25
            reasons_bear.append(f"BB %B={bb_pct:.2f} (at upper band)")

        # RSI
        if rsi is not None:
            if rsi <= cfg.rsi_oversold:
                bull_score += 0.20
                reasons_bull.append(f"RSI={rsi:.1f} oversold")
            elif rsi >= cfg.rsi_overbought:
                bear_score += 0.20
                reasons_bear.append(f"RSI={rsi:.1f} overbought")

        # Stochastic
        if stoch_k is not None:
            if stoch_k <= cfg.stoch_oversold and (stoch_d is None or stoch_k >= stoch_d):
                bull_score += 0.15
                reasons_bull.append(f"Stoch={stoch_k:.1f} oversold+cross")
            elif stoch_k >= cfg.stoch_overbought and (stoch_d is None or stoch_k <= stoch_d):
                bear_score += 0.15
                reasons_bear.append(f"Stoch={stoch_k:.1f} overbought+cross")

        # Determine direction
        if bull_score >= bear_score and bull_score >= cfg.min_confidence:
            confidence = min(bull_score, 1.0)
            signal = Signal.STRONG_BUY if confidence >= 0.70 else Signal.BUY
            reason = "; ".join(reasons_bull)

            # SL: below recent low by buffer
            recent_low = float(low.tail(5).min())
            sl_buffer  = (atr * cfg.atr_sl_multiplier) if atr else (current_price * 0.002)
            sl = round(recent_low - sl_buffer, 5)
            tp = round(ema_mean + (ema_mean - sl) * 0.3, 5)   # TP near mean (conservative)
            tp = max(tp, round(current_price + (current_price - sl) * cfg.rr_ratio, 5))

        elif bear_score > bull_score and bear_score >= cfg.min_confidence:
            confidence = min(bear_score, 1.0)
            signal = Signal.STRONG_SELL if confidence >= 0.70 else Signal.SELL
            reason = "; ".join(reasons_bear)

            recent_high = float(high.tail(5).max())
            sl_buffer   = (atr * cfg.atr_sl_multiplier) if atr else (current_price * 0.002)
            sl = round(recent_high + sl_buffer, 5)
            tp = round(ema_mean - (sl - ema_mean) * 0.3, 5)
            tp = min(tp, round(current_price - (sl - current_price) * cfg.rr_ratio, 5))

        else:
            max_score = max(bull_score, bear_score)
            return MeanReversionSignal(
                signal      = Signal.NEUTRAL,
                confidence  = round(max_score, 3),
                reason      = f"No reversion setup (bull={bull_score:.2f}, bear={bear_score:.2f})",
                zscore      = round(zscore, 3),
                mean_price  = round(ema_mean, 5),
            )

        return MeanReversionSignal(
            signal      = signal,
            confidence  = round(confidence, 3),
            reason      = reason,
            zscore      = round(zscore, 3),
            mean_price  = round(ema_mean, 5),
            entry_price = round(current_price, 5),
            stop_loss   = sl,
            take_profit = tp,
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

    strat  = MeanReversionStrategy()
    result = strat.analyze(df)

    print("Mean Reversion Strategy Test")
    print("=" * 50)
    print(f"Signal:     {result.signal.value}")
    print(f"Confidence: {result.confidence*100:.1f}%")
    print(f"Reason:     {result.reason}")
    print(f"Z-score:    {result.zscore}")
    print(f"Mean:       {result.mean_price}")
    if result.stop_loss:
        print(f"SL:         {result.stop_loss:.5f}")
        print(f"TP:         {result.take_profit:.5f}")
