"""
Guide Strategy — RSI + StochRSI + SMA200  (B3 — de la Guía del Buen Trader Algorítmico)

Este es el ejemplo de estrategia de la guía (Pieza 02, ejercicio práctico):

  LONG:  RSI(14) < 30  AND  StochRSI(20) < 20  AND  precio > SMA200
  SHORT: RSI(14) > 70  AND  StochRSI(20) > 80  AND  precio < SMA200

  SL: 0.5% del precio de entrada  (ratio mínimo 1:3)
  TP: 1.5% del precio de entrada

Filosofía:
  - Buscamos pullbacks a zona oversold/overbought DENTRO de la tendencia macro
  - SMA200 actúa como filtro de dirección (solo longs en uptrend, solo shorts en downtrend)
  - Estrategia simétrica: mismo patrón mirrored para cada dirección

El StochRSI confirma que el RSI también está en zona extrema en términos de momentum,
lo que reduce las señales falsas de RSI solo.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)

try:
    from ta.trend import SMAIndicator, ADXIndicator
    from ta.volatility import AverageTrueRange
    from ta.momentum import RSIIndicator, StochRSIIndicator
    TA_AVAILABLE = True
except ImportError:
    TA_AVAILABLE = False

from strategies.technical_analysis import Signal


@dataclass
class GuideStrategyConfig:
    """Configuration for the RSI+StochRSI+SMA200 guide strategy."""
    rsi_period:          int   = 14     # RSI period
    rsi_oversold:        float = 30.0   # RSI below this → oversold (BUY setup)
    rsi_overbought:      float = 70.0   # RSI above this → overbought (SELL setup)
    stochrsi_period:     int   = 14     # StochRSI period
    stochrsi_oversold:   float = 20.0   # StochRSI below this → confirms BUY
    stochrsi_overbought: float = 80.0   # StochRSI above this → confirms SELL
    sma200_period:       int   = 200    # Macro trend filter
    sl_pct:              float = 0.005  # 0.5% stop loss (as per guide)
    tp_pct:              float = 0.015  # 1.5% take profit → 1:3 ratio (as per guide)
    use_adx_filter:      bool  = False  # Optional: require trending market
    adx_max:             float = 30.0   # If use_adx_filter: only trade when ADX < this
    min_confidence:      float = 0.55


@dataclass
class GuideStrategySignal:
    """Output from guide strategy analysis."""
    signal:       Signal
    confidence:   float
    reason:       str
    rsi:          Optional[float] = None
    stochrsi_k:   Optional[float] = None
    sma200:       Optional[float] = None
    entry_price:  Optional[float] = None
    stop_loss:    Optional[float] = None
    take_profit:  Optional[float] = None


class GuideStrategy:
    """
    RSI + StochRSI + SMA200 strategy from the guide's practical exercise.

    Looks for oversold/overbought pullbacks within the macro trend.
    The SMA200 filter ensures we only fade extremes in the direction
    of the dominant trend — avoiding the classic mean-reversion trap.
    """

    def __init__(self, config: GuideStrategyConfig = None):
        self.config = config or GuideStrategyConfig()

    def analyze(self, df: pd.DataFrame) -> GuideStrategySignal:
        """
        Analyze for RSI+StochRSI+SMA200 opportunities.

        Args:
            df: OHLCV DataFrame indexed by timestamp (min 210 bars for SMA200)

        Returns:
            GuideStrategySignal with signal, confidence, and trade parameters
        """
        if not TA_AVAILABLE:
            return GuideStrategySignal(Signal.NEUTRAL, 0.0, "ta library not available")

        cfg = self.config
        n   = len(df)
        min_bars = cfg.sma200_period + 5

        if n < min_bars:
            return GuideStrategySignal(Signal.NEUTRAL, 0.0,
                                       f"Insufficient data ({n} < {min_bars} bars)")

        close = df['close']
        high  = df['high']
        low   = df['low']
        current_price = float(close.iloc[-1])

        # --- SMA200 — macro trend direction ---
        sma200 = float(SMAIndicator(close=close, window=cfg.sma200_period)
                       .sma_indicator().iloc[-1])
        macro_bull = current_price > sma200
        macro_bear = current_price < sma200

        # --- RSI ---
        rsi = float(RSIIndicator(close=close, window=cfg.rsi_period).rsi().iloc[-1])

        # --- StochRSI ---
        stochrsi_obj = StochRSIIndicator(
            close=close,
            window=cfg.stochrsi_period,
            smooth1=3, smooth2=3,
        )
        stochrsi_k = float(stochrsi_obj.stochrsi_k().iloc[-1])

        # --- Optional ADX filter ---
        if cfg.use_adx_filter and n >= 28:
            adx = float(ADXIndicator(high=high, low=low, close=close, window=14)
                        .adx().iloc[-1])
            if adx > cfg.adx_max:
                return GuideStrategySignal(
                    Signal.NEUTRAL, 0.0,
                    f"ADX={adx:.1f} too high (market trending, not ranging)",
                    rsi=round(rsi, 1), stochrsi_k=round(stochrsi_k, 1), sma200=round(sma200, 5),
                )

        # --- Signal logic ---
        is_long_setup  = (
            rsi <= cfg.rsi_oversold
            and stochrsi_k <= cfg.stochrsi_oversold
            and macro_bull
        )
        is_short_setup = (
            rsi >= cfg.rsi_overbought
            and stochrsi_k >= cfg.stochrsi_overbought
            and macro_bear
        )

        if not (is_long_setup or is_short_setup):
            # Generate informative neutral message
            issues = []
            if not (rsi <= cfg.rsi_oversold or rsi >= cfg.rsi_overbought):
                issues.append(f"RSI={rsi:.1f} not at extreme")
            if not (stochrsi_k <= cfg.stochrsi_oversold or stochrsi_k >= cfg.stochrsi_overbought):
                issues.append(f"StochRSI={stochrsi_k:.1f} not at extreme")
            if not (macro_bull or macro_bear):
                issues.append("Mixed macro trend")
            return GuideStrategySignal(
                Signal.NEUTRAL, 0.0,
                " | ".join(issues) or "No setup conditions met",
                rsi=round(rsi, 1), stochrsi_k=round(stochrsi_k, 1), sma200=round(sma200, 5),
            )

        # --- Confidence: distance from thresholds → stronger = more confident ---
        if is_long_setup:
            rsi_depth    = (cfg.rsi_oversold - rsi) / cfg.rsi_oversold       # 0–1
            stoch_depth  = (cfg.stochrsi_oversold - stochrsi_k) / cfg.stochrsi_oversold
            confidence   = min(0.50 + rsi_depth * 0.25 + stoch_depth * 0.25, 1.0)
            signal       = Signal.STRONG_BUY if confidence >= 0.70 else Signal.BUY
            sl           = round(current_price * (1 - cfg.sl_pct), 5)
            tp           = round(current_price * (1 + cfg.tp_pct), 5)
            reason       = (f"RSI={rsi:.1f} oversold | StochRSI={stochrsi_k:.1f} oversold"
                            f" | Price > SMA200 ({sma200:.5f})")

        else:  # short setup
            rsi_depth    = (rsi - cfg.rsi_overbought) / (100 - cfg.rsi_overbought)
            stoch_depth  = (stochrsi_k - cfg.stochrsi_overbought) / (100 - cfg.stochrsi_overbought)
            confidence   = min(0.50 + rsi_depth * 0.25 + stoch_depth * 0.25, 1.0)
            signal       = Signal.STRONG_SELL if confidence >= 0.70 else Signal.SELL
            sl           = round(current_price * (1 + cfg.sl_pct), 5)
            tp           = round(current_price * (1 - cfg.tp_pct), 5)
            reason       = (f"RSI={rsi:.1f} overbought | StochRSI={stochrsi_k:.1f} overbought"
                            f" | Price < SMA200 ({sma200:.5f})")

        if confidence < cfg.min_confidence:
            return GuideStrategySignal(
                Signal.NEUTRAL, round(confidence, 3),
                f"Setup found but confidence too low ({confidence*100:.0f}%): {reason}",
                rsi=round(rsi, 1), stochrsi_k=round(stochrsi_k, 1), sma200=round(sma200, 5),
            )

        return GuideStrategySignal(
            signal      = signal,
            confidence  = round(confidence, 3),
            reason      = reason,
            rsi         = round(rsi, 1),
            stochrsi_k  = round(stochrsi_k, 1),
            sma200      = round(sma200, 5),
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

    strat  = GuideStrategy()
    result = strat.analyze(df)

    print("Guide Strategy Test (RSI + StochRSI + SMA200)")
    print("=" * 50)
    print(f"Signal:     {result.signal.value}")
    print(f"Confidence: {result.confidence*100:.1f}%")
    print(f"Reason:     {result.reason}")
    print(f"RSI:        {result.rsi}  |  StochRSI: {result.stochrsi_k}")
    print(f"SMA200:     {result.sma200}")
    if result.stop_loss:
        print(f"SL:         {result.stop_loss:.5f}  |  TP: {result.take_profit:.5f}")
