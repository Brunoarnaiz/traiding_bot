"""
MA Crossover Strategy  (B1 — de la Guía del Buen Trader Algorítmico)

Lógica:
  1. EMA rápida (default EMA9) cruza a la EMA lenta (default EMA21)
  2. Filtro macro: precio > SMA200 → solo LONGs permitidos; < SMA200 → solo SHORTs
  3. Confianza aumenta cuanto más reciente es el cruce y cuánto más fuerte el ADX
  4. Estrategia simétrica: mismo patrón en espejo para shorts

Señales:
  STRONG_BUY  — cruce alcista en esta misma barra, filtro SMA200 OK
  BUY         — fast > slow (tendencia alcista activa ≤ N barras), SMA200 OK
  STRONG_SELL — cruce bajista en esta misma barra, filtro SMA200 OK
  SELL        — fast < slow (tendencia bajista activa ≤ N barras), SMA200 OK
  NEUTRAL     — sin señal o filtro SMA200 bloqueado
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)

try:
    from ta.trend import EMAIndicator, SMAIndicator, ADXIndicator
    from ta.volatility import AverageTrueRange
    TA_AVAILABLE = True
except ImportError:
    TA_AVAILABLE = False

from strategies.technical_analysis import Signal


@dataclass
class MACrossoverConfig:
    """Configuration for the MA Crossover strategy."""
    fast_period:        int   = 9       # Fast EMA period
    slow_period:        int   = 21      # Slow EMA period
    sma200_period:      int   = 200     # Trend filter SMA period
    use_sma200_filter:  bool  = True    # Block trades against macro trend
    max_bars_since_cross: int = 5       # Accept signal up to N bars after crossover
    adx_min:            float = 20.0    # Minimum ADX to trade (0 = disabled)
    atr_sl_multiplier:  float = 1.5     # SL = N × ATR
    rr_ratio:           float = 2.0     # Risk:Reward ratio
    min_confidence:     float = 0.50


@dataclass
class MACrossoverSignal:
    """Output from MA crossover analysis."""
    signal:      Signal
    confidence:  float
    reason:      str
    fast_ema:    Optional[float] = None
    slow_ema:    Optional[float] = None
    sma200:      Optional[float] = None
    bars_since_cross: Optional[int] = None
    entry_price: Optional[float] = None
    stop_loss:   Optional[float] = None
    take_profit: Optional[float] = None


class MACrossoverStrategy:
    """
    Moving Average Crossover strategy with SMA200 macro-trend filter.

    Inspired by the guide's 'Cruce de Medias' strategy:
    uses a fast and a slow EMA; only trades in the direction of the
    macro trend (price vs SMA200).
    """

    def __init__(self, config: MACrossoverConfig = None):
        self.config = config or MACrossoverConfig()

    def analyze(self, df: pd.DataFrame) -> MACrossoverSignal:
        """
        Analyze for MA crossover opportunities.

        Args:
            df: OHLCV DataFrame indexed by timestamp (min 210 bars recommended)

        Returns:
            MACrossoverSignal with signal, confidence, and trade parameters
        """
        if not TA_AVAILABLE:
            return MACrossoverSignal(Signal.NEUTRAL, 0.0, "ta library not available")

        cfg = self.config
        n   = len(df)
        min_bars = max(cfg.slow_period, cfg.sma200_period if cfg.use_sma200_filter else 0) + 10

        if n < min_bars:
            return MACrossoverSignal(Signal.NEUTRAL, 0.0, "Insufficient data")

        close = df['close']
        high  = df['high']
        low   = df['low']
        current_price = float(close.iloc[-1])

        # --- Compute EMAs and SMA200 ---
        fast_ema = EMAIndicator(close=close, window=cfg.fast_period).ema_indicator()
        slow_ema = EMAIndicator(close=close, window=cfg.slow_period).ema_indicator()

        fast_now  = float(fast_ema.iloc[-1])
        slow_now  = float(slow_ema.iloc[-1])

        sma200 = None
        if cfg.use_sma200_filter and n >= cfg.sma200_period:
            sma200 = float(SMAIndicator(close=close, window=cfg.sma200_period)
                           .sma_indicator().iloc[-1])

        # --- ADX ---
        adx_val = None
        if cfg.adx_min > 0 and n >= 28:
            adx_val = float(ADXIndicator(high=high, low=low, close=close, window=14)
                            .adx().iloc[-1])

        # --- ATR for SL/TP sizing ---
        atr = None
        if n >= 15:
            atr = float(AverageTrueRange(high=high, low=low, close=close, window=14)
                        .average_true_range().iloc[-1])

        # --- ADX filter ---
        if cfg.adx_min > 0 and adx_val is not None and adx_val < cfg.adx_min:
            return MACrossoverSignal(
                Signal.NEUTRAL, 0.0,
                f"ADX={adx_val:.1f} below threshold {cfg.adx_min}",
                fast_ema=round(fast_now, 5), slow_ema=round(slow_now, 5), sma200=sma200,
            )

        # --- Detect crossover: find how many bars ago fast crossed slow ---
        lookback = min(cfg.max_bars_since_cross + 2, n - 1)
        fast_arr = fast_ema.values[-lookback:]
        slow_arr = slow_ema.values[-lookback:]

        # Difference series: positive = fast above slow
        diff = fast_arr - slow_arr
        bars_since_bullish_cross = None
        bars_since_bearish_cross = None

        for i in range(len(diff) - 1, 0, -1):
            if diff[i] > 0 and diff[i - 1] <= 0:
                bars_since_bullish_cross = len(diff) - 1 - i
                break
        for i in range(len(diff) - 1, 0, -1):
            if diff[i] < 0 and diff[i - 1] >= 0:
                bars_since_bearish_cross = len(diff) - 1 - i
                break

        # Current state
        fast_above_slow = fast_now > slow_now
        fast_below_slow = fast_now < slow_now

        # --- SMA200 macro filter ---
        macro_bullish = (sma200 is None) or (current_price > sma200)
        macro_bearish = (sma200 is None) or (current_price < sma200)

        # --- Signal logic ---
        bull_score = 0.0
        bear_score = 0.0
        reason_parts = []

        # Crossover bonus (more recent = higher score)
        if fast_above_slow and bars_since_bullish_cross is not None:
            age = bars_since_bullish_cross
            if age <= cfg.max_bars_since_cross:
                cross_score = max(0.40 - age * 0.06, 0.10)
                bull_score += cross_score
                reason_parts.append(f"Bullish EMA cross {age} bars ago")
            else:
                bull_score += 0.15
                reason_parts.append(f"EMA9 > EMA21 (trend active)")
        elif fast_below_slow and bars_since_bearish_cross is not None:
            age = bars_since_bearish_cross
            if age <= cfg.max_bars_since_cross:
                cross_score = max(0.40 - age * 0.06, 0.10)
                bear_score += cross_score
                reason_parts.append(f"Bearish EMA cross {age} bars ago")
            else:
                bear_score += 0.15
                reason_parts.append(f"EMA9 < EMA21 (trend active)")

        # EMA separation (wider gap = stronger trend)
        ema_gap_pct = abs(fast_now - slow_now) / slow_now if slow_now > 0 else 0
        gap_score = min(ema_gap_pct * 500, 0.20)  # up to 0.20 for 0.04% gap
        if fast_above_slow:
            bull_score += gap_score
        elif fast_below_slow:
            bear_score += gap_score

        # ADX strength bonus
        if adx_val is not None:
            adx_bonus = min((adx_val - cfg.adx_min) / 30.0, 0.20) if adx_val > cfg.adx_min else 0.0
            if fast_above_slow:
                bull_score += adx_bonus
            elif fast_below_slow:
                bear_score += adx_bonus
            reason_parts.append(f"ADX={adx_val:.1f}")

        # SMA200 confirmation bonus (price on same side as trade direction)
        if fast_above_slow and macro_bullish and sma200 is not None:
            bull_score += 0.15
            reason_parts.append(f"Price > SMA200 ({sma200:.5f})")
        elif fast_below_slow and macro_bearish and sma200 is not None:
            bear_score += 0.15
            reason_parts.append(f"Price < SMA200 ({sma200:.5f})")

        # --- Apply SMA200 filter (block counter-trend trades) ---
        if fast_above_slow and cfg.use_sma200_filter and not macro_bullish:
            return MACrossoverSignal(
                Signal.NEUTRAL, bull_score,
                f"Bullish cross blocked: price {current_price:.5f} < SMA200 {sma200:.5f}",
                fast_ema=round(fast_now, 5), slow_ema=round(slow_now, 5), sma200=sma200,
            )
        if fast_below_slow and cfg.use_sma200_filter and not macro_bearish:
            return MACrossoverSignal(
                Signal.NEUTRAL, bear_score,
                f"Bearish cross blocked: price {current_price:.5f} > SMA200 {sma200:.5f}",
                fast_ema=round(fast_now, 5), slow_ema=round(slow_now, 5), sma200=sma200,
            )

        # --- Build output ---
        sl_dist = (atr * cfg.atr_sl_multiplier) if atr else (current_price * 0.0015)

        if bull_score >= bear_score and bull_score >= cfg.min_confidence:
            confidence = min(bull_score, 1.0)
            signal     = Signal.STRONG_BUY if confidence >= 0.65 else Signal.BUY
            sl         = round(current_price - sl_dist, 5)
            tp         = round(current_price + sl_dist * cfg.rr_ratio, 5)
            bars_cross = bars_since_bullish_cross

        elif bear_score > bull_score and bear_score >= cfg.min_confidence:
            confidence = min(bear_score, 1.0)
            signal     = Signal.STRONG_SELL if confidence >= 0.65 else Signal.SELL
            sl         = round(current_price + sl_dist, 5)
            tp         = round(current_price - sl_dist * cfg.rr_ratio, 5)
            bars_cross = bars_since_bearish_cross

        else:
            return MACrossoverSignal(
                Signal.NEUTRAL,
                round(max(bull_score, bear_score), 3),
                f"No MA crossover signal (bull={bull_score:.2f}, bear={bear_score:.2f})",
                fast_ema=round(fast_now, 5), slow_ema=round(slow_now, 5), sma200=sma200,
            )

        return MACrossoverSignal(
            signal          = signal,
            confidence      = round(confidence, 3),
            reason          = " | ".join(reason_parts),
            fast_ema        = round(fast_now, 5),
            slow_ema        = round(slow_now, 5),
            sma200          = round(sma200, 5) if sma200 else None,
            bars_since_cross= bars_cross,
            entry_price     = round(current_price, 5),
            stop_loss       = sl,
            take_profit     = tp,
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
    ohlcv    = provider.get_ohlcv('EURUSD', Timeframe.H1, bars=500)
    df = ohlcv_to_dataframe(ohlcv)

    strat  = MACrossoverStrategy()
    result = strat.analyze(df)

    print("MA Crossover Strategy Test")
    print("=" * 50)
    print(f"Signal:          {result.signal.value}")
    print(f"Confidence:      {result.confidence*100:.1f}%")
    print(f"Reason:          {result.reason}")
    print(f"Fast EMA:        {result.fast_ema}")
    print(f"Slow EMA:        {result.slow_ema}")
    print(f"SMA200:          {result.sma200}")
    print(f"Bars since cross:{result.bars_since_cross}")
    if result.stop_loss:
        print(f"SL:              {result.stop_loss:.5f}")
        print(f"TP:              {result.take_profit:.5f}")
