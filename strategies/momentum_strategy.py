"""
Momentum / Trend Following Strategy  (B2 — de la Guía del Buen Trader Algorítmico)

Principio clave de la guía:
  RSI alto NO significa sobrecompra → significa MOMENTUM fuerte hacia arriba.
  Un RSI > 60 en tendencia alcista confirma que hay fuerza compradora, no agotamiento.

Lógica LONG:
  1. ADX > threshold (hay tendencia, no rango)
  2. RSI > rsi_bull_threshold (momentum alcista, no sobrecompra)
  3. Precio > EMA rápida > EMA lenta (alineación de medias)
  4. Precio > EMA50 (tendencia de fondo bullish)

Lógica SHORT (simétrica):
  1. ADX > threshold
  2. RSI < rsi_bear_threshold (momentum bajista)
  3. Precio < EMA rápida < EMA lenta
  4. Precio < EMA50

Salida: trailing stop recomendado (dejar correr el momentum).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)

try:
    from ta.trend import EMAIndicator, SMAIndicator, ADXIndicator, MACD
    from ta.volatility import AverageTrueRange
    from ta.momentum import RSIIndicator
    TA_AVAILABLE = True
except ImportError:
    TA_AVAILABLE = False

from strategies.technical_analysis import Signal


@dataclass
class MomentumConfig:
    """Configuration for the Momentum/Trend-Following strategy."""
    ema_fast:             int   = 9       # Fast EMA
    ema_slow:             int   = 21      # Slow EMA
    ema_filter:           int   = 50      # Trend filter EMA
    adx_min:              float = 25.0    # Minimum ADX (trend strength gate)
    rsi_bull_threshold:   float = 55.0    # RSI > this = bullish momentum
    rsi_bear_threshold:   float = 45.0    # RSI < this = bearish momentum
    use_macd_confirm:     bool  = True    # Use MACD histogram as confirmation
    atr_sl_multiplier:    float = 1.5     # SL = N × ATR (trailing recommended via BotConfig)
    rr_ratio:             float = 3.0     # TP = SL × ratio (give momentum room)
    min_confidence:       float = 0.50


@dataclass
class MomentumSignal:
    """Output from momentum analysis."""
    signal:      Signal
    confidence:  float
    reason:      str
    rsi:         Optional[float] = None
    adx:         Optional[float] = None
    ema_fast:    Optional[float] = None
    ema_slow:    Optional[float] = None
    ema_filter:  Optional[float] = None
    entry_price: Optional[float] = None
    stop_loss:   Optional[float] = None
    take_profit: Optional[float] = None


class MomentumStrategy:
    """
    Momentum / Trend-Following strategy.

    Key insight from the guide: treats RSI as a momentum indicator,
    not an overbought/oversold oscillator. High RSI in an uptrend = strength.

    Recommended use with Phase A trailing stops (BotConfig.trailing_stop_pips)
    so the position can follow the trend until it reverses.
    """

    def __init__(self, config: MomentumConfig = None):
        self.config = config or MomentumConfig()

    def analyze(self, df: pd.DataFrame) -> MomentumSignal:
        """
        Analyze for momentum/trend-following opportunities.

        Args:
            df: OHLCV DataFrame indexed by timestamp

        Returns:
            MomentumSignal with signal, confidence, and trade parameters
        """
        if not TA_AVAILABLE:
            return MomentumSignal(Signal.NEUTRAL, 0.0, "ta library not available")

        cfg = self.config
        n   = len(df)
        min_bars = max(cfg.ema_filter, 26 if cfg.use_macd_confirm else 0) + 10

        if n < min_bars:
            return MomentumSignal(Signal.NEUTRAL, 0.0, "Insufficient data")

        close = df['close']
        high  = df['high']
        low   = df['low']
        current_price = float(close.iloc[-1])

        # --- Indicators ---
        ema_fast_val  = float(EMAIndicator(close=close, window=cfg.ema_fast).ema_indicator().iloc[-1])
        ema_slow_val  = float(EMAIndicator(close=close, window=cfg.ema_slow).ema_indicator().iloc[-1])
        ema_filt_val  = float(EMAIndicator(close=close, window=cfg.ema_filter).ema_indicator().iloc[-1])

        adx_obj = ADXIndicator(high=high, low=low, close=close, window=14)
        adx_val = float(adx_obj.adx().iloc[-1])

        rsi_val = float(RSIIndicator(close=close, window=14).rsi().iloc[-1])

        atr = float(AverageTrueRange(high=high, low=low, close=close, window=14)
                    .average_true_range().iloc[-1])

        macd_hist = None
        if cfg.use_macd_confirm and n >= 26:
            macd_obj  = MACD(close=close)
            macd_hist = float(macd_obj.macd_diff().iloc[-1])

        # --- ADX gate: only trade when there IS a trend ---
        if adx_val < cfg.adx_min:
            return MomentumSignal(
                Signal.NEUTRAL, 0.0,
                f"No trend (ADX={adx_val:.1f} < {cfg.adx_min})",
                rsi=round(rsi_val, 1), adx=round(adx_val, 1),
            )

        # --- Score accumulation ---
        bull_score = 0.0
        bear_score = 0.0
        bull_reasons = []
        bear_reasons = []

        # Core RSI momentum condition (guide's key insight)
        if rsi_val >= cfg.rsi_bull_threshold:
            rsi_bonus = min((rsi_val - cfg.rsi_bull_threshold) / 30.0, 0.35) + 0.25
            bull_score += rsi_bonus
            bull_reasons.append(f"RSI={rsi_val:.1f} (bullish momentum)")
        elif rsi_val <= cfg.rsi_bear_threshold:
            rsi_bonus = min((cfg.rsi_bear_threshold - rsi_val) / 30.0, 0.35) + 0.25
            bear_score += rsi_bonus
            bear_reasons.append(f"RSI={rsi_val:.1f} (bearish momentum)")
        else:
            return MomentumSignal(
                Signal.NEUTRAL, 0.0,
                f"RSI={rsi_val:.1f} in neutral zone [{cfg.rsi_bear_threshold}–{cfg.rsi_bull_threshold}]",
                rsi=round(rsi_val, 1), adx=round(adx_val, 1),
            )

        # EMA alignment: price > fast > slow (bullish stack) or inverse
        ema_bull_aligned = current_price > ema_fast_val > ema_slow_val
        ema_bear_aligned = current_price < ema_fast_val < ema_slow_val

        if ema_bull_aligned:
            bull_score += 0.20
            bull_reasons.append(f"EMA stack bullish ({ema_fast_val:.5f} > {ema_slow_val:.5f})")
        elif ema_bear_aligned:
            bear_score += 0.20
            bear_reasons.append(f"EMA stack bearish ({ema_fast_val:.5f} < {ema_slow_val:.5f})")

        # Trend filter EMA (EMA50)
        if current_price > ema_filt_val:
            bull_score += 0.15
            bull_reasons.append(f"Price > EMA{cfg.ema_filter} ({ema_filt_val:.5f})")
        elif current_price < ema_filt_val:
            bear_score += 0.15
            bear_reasons.append(f"Price < EMA{cfg.ema_filter} ({ema_filt_val:.5f})")

        # ADX strength bonus (stronger trend = higher confidence)
        adx_bonus = min((adx_val - cfg.adx_min) / 25.0, 0.15)
        bull_score += adx_bonus
        bear_score += adx_bonus

        # MACD histogram confirmation
        if macd_hist is not None:
            if macd_hist > 0:
                bull_score += 0.10
                bull_reasons.append(f"MACD hist positive ({macd_hist:.5f})")
            elif macd_hist < 0:
                bear_score += 0.10
                bear_reasons.append(f"MACD hist negative ({macd_hist:.5f})")

        # --- Output ---
        sl_dist = atr * cfg.atr_sl_multiplier

        if bull_score >= bear_score and bull_score >= cfg.min_confidence:
            confidence = min(bull_score, 1.0)
            signal     = Signal.STRONG_BUY if confidence >= 0.70 else Signal.BUY
            sl         = round(current_price - sl_dist, 5)
            tp         = round(current_price + sl_dist * cfg.rr_ratio, 5)
            reason     = f"ADX={adx_val:.1f} | " + " | ".join(bull_reasons)

        elif bear_score > bull_score and bear_score >= cfg.min_confidence:
            confidence = min(bear_score, 1.0)
            signal     = Signal.STRONG_SELL if confidence >= 0.70 else Signal.SELL
            sl         = round(current_price + sl_dist, 5)
            tp         = round(current_price - sl_dist * cfg.rr_ratio, 5)
            reason     = f"ADX={adx_val:.1f} | " + " | ".join(bear_reasons)

        else:
            return MomentumSignal(
                Signal.NEUTRAL,
                round(max(bull_score, bear_score), 3),
                f"Weak momentum (bull={bull_score:.2f}, bear={bear_score:.2f})",
                rsi=round(rsi_val, 1), adx=round(adx_val, 1),
                ema_fast=round(ema_fast_val, 5), ema_slow=round(ema_slow_val, 5),
                ema_filter=round(ema_filt_val, 5),
            )

        return MomentumSignal(
            signal      = signal,
            confidence  = round(confidence, 3),
            reason      = reason,
            rsi         = round(rsi_val, 1),
            adx         = round(adx_val, 1),
            ema_fast    = round(ema_fast_val, 5),
            ema_slow    = round(ema_slow_val, 5),
            ema_filter  = round(ema_filt_val, 5),
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
    ohlcv    = provider.get_ohlcv('EURUSD', Timeframe.H1, bars=500)
    df = ohlcv_to_dataframe(ohlcv)

    strat  = MomentumStrategy()
    result = strat.analyze(df)

    print("Momentum Strategy Test")
    print("=" * 50)
    print(f"Signal:     {result.signal.value}")
    print(f"Confidence: {result.confidence*100:.1f}%")
    print(f"Reason:     {result.reason}")
    print(f"RSI:        {result.rsi}  |  ADX: {result.adx}")
    print(f"EMA{strat.config.ema_fast}: {result.ema_fast}  EMA{strat.config.ema_slow}: {result.ema_slow}")
    print(f"EMA{strat.config.ema_filter}: {result.ema_filter}")
    if result.stop_loss:
        print(f"SL:         {result.stop_loss:.5f}  |  TP: {result.take_profit:.5f}")
