"""
Advanced Technical Analysis Engine
Weighted multi-indicator scoring with support/resistance, market regime detection,
volume analysis, and confluence-based signal generation.
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)

try:
    from ta.trend import SMAIndicator, EMAIndicator, MACD, ADXIndicator, IchimokuIndicator, CCIIndicator
    from ta.momentum import RSIIndicator, StochasticOscillator, WilliamsRIndicator, StochRSIIndicator
    from ta.volatility import BollingerBands, AverageTrueRange, KeltnerChannel
    from ta.volume import OnBalanceVolumeIndicator, MFIIndicator
    TA_AVAILABLE = True
except ImportError:
    logger.warning("ta library not installed. Install with: pip install ta")
    TA_AVAILABLE = False


class Signal(Enum):
    """Trading signals"""
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    NEUTRAL = "NEUTRAL"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


class MarketRegime(Enum):
    """Market regime classification"""
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    BREAKOUT_UP = "BREAKOUT_UP"
    BREAKOUT_DOWN = "BREAKOUT_DOWN"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    UNKNOWN = "UNKNOWN"


@dataclass
class SupportResistanceLevel:
    """A support or resistance level"""
    price: float
    strength: int       # Number of touches / confluence count
    level_type: str     # 'support' or 'resistance'
    last_touch: int     # Bar index of last touch


@dataclass
class TechnicalIndicators:
    """Container for all technical indicators"""
    # Trend
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    ema_9: Optional[float] = None
    ema_21: Optional[float] = None
    ema_12: Optional[float] = None
    ema_26: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_diff: Optional[float] = None
    macd_prev_diff: Optional[float] = None
    adx: Optional[float] = None
    adx_pos: Optional[float] = None   # +DI
    adx_neg: Optional[float] = None   # -DI

    # Ichimoku
    ichimoku_a: Optional[float] = None   # Senkou Span A
    ichimoku_b: Optional[float] = None   # Senkou Span B
    ichimoku_base: Optional[float] = None  # Kijun-sen
    ichimoku_conv: Optional[float] = None  # Tenkan-sen

    # Momentum
    rsi: Optional[float] = None
    rsi_prev: Optional[float] = None
    stoch_k: Optional[float] = None
    stoch_d: Optional[float] = None
    stoch_k_prev: Optional[float] = None
    stochrsi_k: Optional[float] = None   # C2: StochRSI %K
    stochrsi_d: Optional[float] = None   # C2: StochRSI %D (signal line)
    williams_r: Optional[float] = None
    cci: Optional[float] = None

    # Volatility
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_width: Optional[float] = None
    bb_pct: Optional[float] = None     # %B position within bands
    atr: Optional[float] = None
    atr_pct: Optional[float] = None    # ATR as % of price
    kc_upper: Optional[float] = None   # Keltner Channel upper
    kc_lower: Optional[float] = None   # Keltner Channel lower

    # Volume
    obv: Optional[float] = None
    obv_sma: Optional[float] = None    # OBV smoothed
    mfi: Optional[float] = None        # Money Flow Index
    volume_ratio: Optional[float] = None  # Current vol / avg vol

    # Price action
    current_price: Optional[float] = None
    price_change_pct: Optional[float] = None
    high_20: Optional[float] = None    # 20-bar high
    low_20: Optional[float] = None     # 20-bar low

    # Support / Resistance
    nearest_support: Optional[float] = None
    nearest_resistance: Optional[float] = None
    sr_levels: List[SupportResistanceLevel] = field(default_factory=list)

    # Market regime
    regime: MarketRegime = MarketRegime.UNKNOWN

    def __repr__(self):
        price = f"{self.current_price:.5f}" if self.current_price else "N/A"
        rsi = f"{self.rsi:.2f}" if self.rsi is not None else "N/A"
        macd_v = f"{self.macd:.5f}" if self.macd is not None else "N/A"
        adx_v = f"{self.adx:.2f}" if self.adx is not None else "N/A"
        return f"TechnicalIndicators(Price={price}, RSI={rsi}, MACD={macd_v}, ADX={adx_v}, Regime={self.regime.value})"


@dataclass
class IndicatorWeight:
    """Weight configuration for each indicator group"""
    rsi: float = 1.5
    macd: float = 1.5
    stochastic: float = 1.0
    stochrsi: float = 1.0      # C2: StochRSI weight
    williams_r: float = 0.8
    cci: float = 0.8
    moving_averages: float = 1.2
    ichimoku: float = 1.0
    bollinger: float = 0.9
    keltner: float = 0.7
    adx_filter: float = 1.0    # Only amplifies, doesn't generate signals
    volume: float = 0.8
    support_resistance: float = 1.3


class TechnicalAnalyzer:
    """
    Advanced technical analysis engine with weighted multi-indicator scoring.

    Uses a confluence-based approach: each indicator group contributes a
    weighted score between -1 and +1. Final signal is the weighted average,
    amplified when ADX confirms a strong trend.
    """

    def __init__(self, weights: Optional[IndicatorWeight] = None):
        self.weights = weights or IndicatorWeight()
        if not TA_AVAILABLE:
            logger.error("Technical analysis library not available. pip install ta")

    # ------------------------------------------------------------------
    # INDICATOR CALCULATION
    # ------------------------------------------------------------------

    def calculate_indicators(self, df: pd.DataFrame) -> TechnicalIndicators:
        """
        Calculate all technical indicators from OHLCV dataframe.

        Args:
            df: DataFrame with columns [open, high, low, close, volume]
                indexed by timestamp

        Returns:
            TechnicalIndicators with all computed values
        """
        if not TA_AVAILABLE:
            return TechnicalIndicators()

        n = len(df)
        if n < 50:
            logger.warning(f"Only {n} bars — many indicators will be unavailable")

        ind = TechnicalIndicators()

        try:
            close = df['close']
            high  = df['high']
            low   = df['low']
            vol   = df['volume'] if 'volume' in df.columns else pd.Series(np.zeros(n), index=df.index)

            ind.current_price = float(close.iloc[-1])
            if n >= 2:
                ind.price_change_pct = float((close.iloc[-1] / close.iloc[-2] - 1) * 100)

            # --- Trend: Moving Averages ---
            if n >= 9:
                ind.ema_9 = float(EMAIndicator(close=close, window=9).ema_indicator().iloc[-1])
            if n >= 20:
                ind.sma_20 = float(SMAIndicator(close=close, window=20).sma_indicator().iloc[-1])
                ind.high_20 = float(high.rolling(20).max().iloc[-1])
                ind.low_20  = float(low.rolling(20).min().iloc[-1])
            if n >= 21:
                ind.ema_21 = float(EMAIndicator(close=close, window=21).ema_indicator().iloc[-1])
            if n >= 26:
                ind.ema_12 = float(EMAIndicator(close=close, window=12).ema_indicator().iloc[-1])
                ind.ema_26 = float(EMAIndicator(close=close, window=26).ema_indicator().iloc[-1])
            if n >= 50:
                ind.sma_50 = float(SMAIndicator(close=close, window=50).sma_indicator().iloc[-1])
            if n >= 200:
                ind.sma_200 = float(SMAIndicator(close=close, window=200).sma_indicator().iloc[-1])

            # --- Trend: MACD ---
            if n >= 35:
                macd_obj = MACD(close=close)
                macd_vals  = macd_obj.macd()
                macd_sig   = macd_obj.macd_signal()
                macd_hist  = macd_obj.macd_diff()
                ind.macd         = float(macd_vals.iloc[-1])
                ind.macd_signal  = float(macd_sig.iloc[-1])
                ind.macd_diff    = float(macd_hist.iloc[-1])
                ind.macd_prev_diff = float(macd_hist.iloc[-2]) if n >= 36 else ind.macd_diff

            # --- Trend: ADX ---
            if n >= 28:
                adx_obj = ADXIndicator(high=high, low=low, close=close, window=14)
                ind.adx     = float(adx_obj.adx().iloc[-1])
                ind.adx_pos = float(adx_obj.adx_pos().iloc[-1])
                ind.adx_neg = float(adx_obj.adx_neg().iloc[-1])

            # --- Ichimoku (standard 9/26/52) ---
            if n >= 52:
                try:
                    ichi = IchimokuIndicator(high=high, low=low)
                    ind.ichimoku_conv = float(ichi.ichimoku_conversion_line().iloc[-1])
                    ind.ichimoku_base = float(ichi.ichimoku_base_line().iloc[-1])
                    ind.ichimoku_a    = float(ichi.ichimoku_a().iloc[-1])
                    ind.ichimoku_b    = float(ichi.ichimoku_b().iloc[-1])
                except Exception:
                    pass  # Ichimoku can fail on some datasets

            # --- Momentum: RSI ---
            if n >= 15:
                rsi_obj  = RSIIndicator(close=close, window=14)
                rsi_vals = rsi_obj.rsi()
                ind.rsi      = float(rsi_vals.iloc[-1])
                ind.rsi_prev = float(rsi_vals.iloc[-2]) if n >= 16 else ind.rsi

            # --- Momentum: Stochastic ---
            if n >= 17:
                stoch = StochasticOscillator(high=high, low=low, close=close, window=14, smooth_window=3)
                k_vals = stoch.stoch()
                ind.stoch_k      = float(k_vals.iloc[-1])
                ind.stoch_d      = float(stoch.stoch_signal().iloc[-1])
                ind.stoch_k_prev = float(k_vals.iloc[-2]) if n >= 18 else ind.stoch_k

            # --- Momentum: StochRSI (C2) ---
            # Note: ta library returns StochRSI in 0-1 scale; multiply × 100 for readability
            if n >= 20:
                try:
                    srsi = StochRSIIndicator(close=close, window=14, smooth1=3, smooth2=3)
                    k_val = float(srsi.stochrsi_k().iloc[-1])
                    d_val = float(srsi.stochrsi_d().iloc[-1])
                    if not (np.isnan(k_val) or np.isnan(d_val)):
                        ind.stochrsi_k = k_val * 100.0   # → 0-100 scale
                        ind.stochrsi_d = d_val * 100.0
                except Exception:
                    pass

            # --- Momentum: Williams %R ---
            if n >= 14:
                try:
                    wr = WilliamsRIndicator(high=high, low=low, close=close, lbp=14)
                    ind.williams_r = float(wr.williams_r().iloc[-1])
                except Exception:
                    pass

            # --- Momentum: CCI ---
            if n >= 20:
                try:
                    cci = CCIIndicator(high=high, low=low, close=close, window=20)
                    ind.cci = float(cci.cci().iloc[-1])
                except Exception:
                    pass

            # --- Volatility: Bollinger Bands ---
            if n >= 20:
                bb = BollingerBands(close=close, window=20, window_dev=2)
                ind.bb_upper  = float(bb.bollinger_hband().iloc[-1])
                ind.bb_middle = float(bb.bollinger_mavg().iloc[-1])
                ind.bb_lower  = float(bb.bollinger_lband().iloc[-1])
                ind.bb_width  = float(bb.bollinger_wband().iloc[-1])
                ind.bb_pct    = float(bb.bollinger_pband().iloc[-1])

            # --- Volatility: ATR ---
            if n >= 15:
                atr_obj = AverageTrueRange(high=high, low=low, close=close, window=14)
                ind.atr     = float(atr_obj.average_true_range().iloc[-1])
                ind.atr_pct = ind.atr / ind.current_price * 100 if ind.current_price else None

            # --- Volatility: Keltner Channel ---
            if n >= 22:
                try:
                    kc = KeltnerChannel(high=high, low=low, close=close, window=20)
                    ind.kc_upper = float(kc.keltner_channel_hband().iloc[-1])
                    ind.kc_lower = float(kc.keltner_channel_lband().iloc[-1])
                except Exception:
                    pass

            # --- Volume: OBV ---
            if vol.sum() > 0:
                try:
                    obv_obj  = OnBalanceVolumeIndicator(close=close, volume=vol)
                    obv_vals = obv_obj.on_balance_volume()
                    ind.obv     = float(obv_vals.iloc[-1])
                    ind.obv_sma = float(obv_vals.rolling(20).mean().iloc[-1]) if n >= 20 else ind.obv
                    avg_vol = float(vol.rolling(20).mean().iloc[-1]) if n >= 20 else float(vol.mean())
                    ind.volume_ratio = float(vol.iloc[-1]) / avg_vol if avg_vol > 0 else 1.0
                except Exception:
                    pass

                try:
                    mfi = MFIIndicator(high=high, low=low, close=close, volume=vol, window=14)
                    ind.mfi = float(mfi.money_flow_index().iloc[-1])
                except Exception:
                    pass

            # --- Support / Resistance ---
            if n >= 20:
                sr_levels = self._detect_support_resistance(df)
                ind.sr_levels = sr_levels
                price = ind.current_price
                supports    = [l for l in sr_levels if l.level_type == 'support'    and l.price < price]
                resistances = [l for l in sr_levels if l.level_type == 'resistance' and l.price > price]
                if supports:
                    ind.nearest_support    = max(supports,    key=lambda l: l.price).price
                if resistances:
                    ind.nearest_resistance = min(resistances, key=lambda l: l.price).price

            # --- Market Regime ---
            ind.regime = self._classify_regime(ind)

        except Exception as e:
            logger.error(f"Error calculating indicators: {e}", exc_info=True)

        return ind

    # ------------------------------------------------------------------
    # SUPPORT / RESISTANCE DETECTION
    # ------------------------------------------------------------------

    def _detect_support_resistance(
        self,
        df: pd.DataFrame,
        lookback: int = 50,
        tolerance_pct: float = 0.001,
        min_touches: int = 2
    ) -> List[SupportResistanceLevel]:
        """
        Detect key S/R levels using swing high/low confluence.

        Strategy:
          1. Find local swing highs and lows (5-bar fractal)
          2. Cluster nearby levels (within tolerance_pct of each other)
          3. Keep levels with >= min_touches
        """
        n = min(lookback, len(df))
        recent = df.tail(n)
        high  = recent['high'].values
        low   = recent['low'].values
        close = recent['close'].values

        swing_highs: List[Tuple[int, float]] = []
        swing_lows:  List[Tuple[int, float]] = []

        for i in range(2, n - 2):
            if high[i] > high[i-1] and high[i] > high[i-2] and high[i] > high[i+1] and high[i] > high[i+2]:
                swing_highs.append((i, high[i]))
            if low[i] < low[i-1] and low[i] < low[i-2] and low[i] < low[i+1] and low[i] < low[i+2]:
                swing_lows.append((i, low[i]))

        def cluster_levels(raw: List[Tuple[int, float]], level_type: str) -> List[SupportResistanceLevel]:
            if not raw:
                return []
            # Sort by price
            sorted_raw = sorted(raw, key=lambda x: x[1])
            clusters: List[SupportResistanceLevel] = []
            base_price = sorted_raw[0][1]
            touches    = [sorted_raw[0]]

            for idx, price in sorted_raw[1:]:
                if abs(price - base_price) / base_price <= tolerance_pct:
                    touches.append((idx, price))
                else:
                    if len(touches) >= min_touches:
                        avg_price  = np.mean([p for _, p in touches])
                        last_touch = max(i for i, _ in touches)
                        clusters.append(SupportResistanceLevel(
                            price=float(round(avg_price, 5)),
                            strength=len(touches),
                            level_type=level_type,
                            last_touch=last_touch
                        ))
                    base_price = price
                    touches    = [(idx, price)]

            if len(touches) >= min_touches:
                avg_price  = np.mean([p for _, p in touches])
                last_touch = max(i for i, _ in touches)
                clusters.append(SupportResistanceLevel(
                    price=float(round(avg_price, 5)),
                    strength=len(touches),
                    level_type=level_type,
                    last_touch=last_touch
                ))
            return clusters

        support_levels    = cluster_levels(swing_lows,  'support')
        resistance_levels = cluster_levels(swing_highs, 'resistance')
        return support_levels + resistance_levels

    # ------------------------------------------------------------------
    # MARKET REGIME CLASSIFICATION
    # ------------------------------------------------------------------

    def _classify_regime(self, ind: TechnicalIndicators) -> MarketRegime:
        """Classify current market regime."""
        adx = ind.adx
        price = ind.current_price

        if adx is None or price is None:
            return MarketRegime.UNKNOWN

        trending = adx >= 25

        # Check Bollinger Band squeeze (low volatility → potential breakout)
        bb_squeeze = ind.bb_width is not None and ind.bb_width < 0.5

        if not trending:
            if bb_squeeze:
                # Price direction for breakout
                if ind.ema_9 and ind.ema_21:
                    if ind.ema_9 > ind.ema_21:
                        return MarketRegime.BREAKOUT_UP
                    else:
                        return MarketRegime.BREAKOUT_DOWN
            return MarketRegime.RANGING

        # High volatility
        if ind.atr_pct is not None and ind.atr_pct > 0.5:
            return MarketRegime.HIGH_VOLATILITY

        # Direction
        if ind.adx_pos is not None and ind.adx_neg is not None:
            if ind.adx_pos > ind.adx_neg:
                return MarketRegime.TRENDING_UP
            else:
                return MarketRegime.TRENDING_DOWN

        # Fallback via SMAs
        if ind.sma_20 and ind.sma_50:
            if ind.sma_20 > ind.sma_50:
                return MarketRegime.TRENDING_UP
            else:
                return MarketRegime.TRENDING_DOWN

        return MarketRegime.UNKNOWN

    # ------------------------------------------------------------------
    # SIGNAL GENERATION — WEIGHTED SCORING
    # ------------------------------------------------------------------

    def generate_signal(self, ind: TechnicalIndicators) -> Tuple[Signal, float, str]:
        """
        Generate trading signal using weighted multi-indicator confluence.

        Each indicator group returns a score in [-1, +1].
        The final weighted score determines the signal and confidence.

        Returns:
            (signal, confidence 0-1, reason string)
        """
        if not ind.current_price:
            return Signal.NEUTRAL, 0.0, "No price data"

        scores: List[Tuple[float, float, str]] = []   # (score, weight, reason)

        # 1. RSI
        rsi_score, rsi_reason = self._score_rsi(ind)
        if rsi_score is not None:
            scores.append((rsi_score, self.weights.rsi, rsi_reason))

        # 2. MACD
        macd_score, macd_reason = self._score_macd(ind)
        if macd_score is not None:
            scores.append((macd_score, self.weights.macd, macd_reason))

        # 3. Stochastic
        stoch_score, stoch_reason = self._score_stochastic(ind)
        if stoch_score is not None:
            scores.append((stoch_score, self.weights.stochastic, stoch_reason))

        # 3b. StochRSI (C2)
        srsi_score, srsi_reason = self._score_stochrsi(ind)
        if srsi_score is not None:
            scores.append((srsi_score, self.weights.stochrsi, srsi_reason))

        # 4. Williams %R
        wr_score, wr_reason = self._score_williams_r(ind)
        if wr_score is not None:
            scores.append((wr_score, self.weights.williams_r, wr_reason))

        # 5. CCI
        cci_score, cci_reason = self._score_cci(ind)
        if cci_score is not None:
            scores.append((cci_score, self.weights.cci, cci_reason))

        # 6. Moving Averages
        ma_score, ma_reason = self._score_moving_averages(ind)
        if ma_score is not None:
            scores.append((ma_score, self.weights.moving_averages, ma_reason))

        # 7. Ichimoku
        ichi_score, ichi_reason = self._score_ichimoku(ind)
        if ichi_score is not None:
            scores.append((ichi_score, self.weights.ichimoku, ichi_reason))

        # 8. Bollinger Bands
        bb_score, bb_reason = self._score_bollinger(ind)
        if bb_score is not None:
            scores.append((bb_score, self.weights.bollinger, bb_reason))

        # 9. Keltner Channel
        kc_score, kc_reason = self._score_keltner(ind)
        if kc_score is not None:
            scores.append((kc_score, self.weights.keltner, kc_reason))

        # 10. Volume confirmation
        vol_score, vol_reason = self._score_volume(ind)
        if vol_score is not None:
            scores.append((vol_score, self.weights.volume, vol_reason))

        # 11. Support / Resistance proximity
        sr_score, sr_reason = self._score_support_resistance(ind)
        if sr_score is not None:
            scores.append((sr_score, self.weights.support_resistance, sr_reason))

        if not scores:
            return Signal.NEUTRAL, 0.0, "Insufficient data"

        # Weighted average
        total_weight = sum(w for _, w, _ in scores)
        weighted_sum = sum(s * w for s, w, _ in scores)
        raw_score = weighted_sum / total_weight  # in [-1, +1]

        # ADX amplifier: strong trend → amplify by up to 20%
        adx_mult = 1.0
        if ind.adx is not None:
            if ind.adx >= 40:
                adx_mult = 1.20
            elif ind.adx >= 25:
                adx_mult = 1.10

        # Regime-based adjustments
        regime_mult = self._regime_multiplier(ind.regime, raw_score)

        final_score = np.clip(raw_score * adx_mult * regime_mult, -1.0, 1.0)

        # Confidence = |final_score|, boosted by indicator count
        base_confidence = abs(final_score)
        count_boost = min(len(scores) / 8.0, 1.0)  # Full boost at 8+ indicators
        confidence = float(np.clip(base_confidence * (0.7 + 0.3 * count_boost), 0.0, 1.0))

        # Determine signal with tiered thresholds
        if final_score >= 0.50:
            signal = Signal.STRONG_BUY
        elif final_score >= 0.15:
            signal = Signal.BUY
        elif final_score <= -0.50:
            signal = Signal.STRONG_SELL
        elif final_score <= -0.15:
            signal = Signal.SELL
        else:
            signal = Signal.NEUTRAL

        # Build reason string from top 4 contributing indicators
        sorted_reasons = sorted(scores, key=lambda x: abs(x[0]) * x[1], reverse=True)
        reason_parts = [r for _, _, r in sorted_reasons[:4] if r]
        reason = "; ".join(reason_parts)
        reason += f" | Regime: {ind.regime.value} | Score: {final_score:.3f}"

        return signal, confidence, reason

    def _regime_multiplier(self, regime: MarketRegime, score: float) -> float:
        """Adjust score multiplier based on market regime and signal direction."""
        if regime == MarketRegime.TRENDING_UP:
            return 1.15 if score > 0 else 0.85
        if regime == MarketRegime.TRENDING_DOWN:
            return 1.15 if score < 0 else 0.85
        if regime in (MarketRegime.BREAKOUT_UP, MarketRegime.BREAKOUT_DOWN):
            return 1.10
        if regime == MarketRegime.HIGH_VOLATILITY:
            return 0.75   # Be conservative in high vol
        if regime == MarketRegime.RANGING:
            return 0.90   # Slightly less confident in ranges
        return 1.0

    # ------------------------------------------------------------------
    # INDIVIDUAL INDICATOR SCORERS  (return score in [-1,+1])
    # ------------------------------------------------------------------

    def _score_rsi(self, ind: TechnicalIndicators) -> Tuple[Optional[float], str]:
        if ind.rsi is None:
            return None, ""
        rsi = ind.rsi
        prev = ind.rsi_prev or rsi
        rising = rsi > prev

        # In strong trends (ADX >= 40) oscillators stay overbought/oversold for
        # long periods — treat them as trend confirmation, not reversal signals.
        strong_trend_up   = (ind.adx or 0) >= 40 and ind.regime == MarketRegime.TRENDING_UP
        strong_trend_down = (ind.adx or 0) >= 40 and ind.regime == MarketRegime.TRENDING_DOWN

        if rsi < 20:
            return 1.0, f"RSI extreme oversold ({rsi:.1f})"
        if rsi < 30:
            return 0.8, f"RSI oversold ({rsi:.1f})"
        if rsi < 40:
            if strong_trend_down:
                return -0.3, f"RSI low in downtrend ({rsi:.1f})"
            score = 0.4 if rising else 0.2
            return score, f"RSI low ({rsi:.1f})"
        if rsi > 80:
            if strong_trend_up:
                return 0.3, f"RSI overbought in strong uptrend ({rsi:.1f})"
            return -1.0, f"RSI extreme overbought ({rsi:.1f})"
        if rsi > 70:
            if strong_trend_up:
                return 0.2, f"RSI high in strong uptrend ({rsi:.1f})"
            return -0.8, f"RSI overbought ({rsi:.1f})"
        if rsi > 60:
            if strong_trend_up:
                return 0.1, f"RSI high in uptrend ({rsi:.1f})"
            score = -0.4 if not rising else -0.2
            return score, f"RSI high ({rsi:.1f})"
        # Neutral zone 40-60
        score = 0.1 if rising else -0.1
        return score, ""

    def _score_macd(self, ind: TechnicalIndicators) -> Tuple[Optional[float], str]:
        if ind.macd is None or ind.macd_signal is None or ind.macd_diff is None:
            return None, ""
        diff      = ind.macd_diff
        prev_diff = ind.macd_prev_diff if ind.macd_prev_diff is not None else diff

        # Histogram direction
        hist_growing   = diff > prev_diff
        hist_shrinking = diff < prev_diff

        if diff > 0:
            if hist_growing:
                return 0.9, "MACD bullish & accelerating"
            else:
                return 0.4, "MACD bullish but decelerating"
        else:
            if hist_shrinking:
                return -0.9, "MACD bearish & accelerating"
            else:
                return -0.4, "MACD bearish but decelerating"

    def _score_stochastic(self, ind: TechnicalIndicators) -> Tuple[Optional[float], str]:
        if ind.stoch_k is None or ind.stoch_d is None:
            return None, ""
        k = ind.stoch_k
        d = ind.stoch_d
        prev_k = ind.stoch_k_prev if ind.stoch_k_prev is not None else k

        strong_trend_up   = (ind.adx or 0) >= 40 and ind.regime == MarketRegime.TRENDING_UP
        strong_trend_down = (ind.adx or 0) >= 40 and ind.regime == MarketRegime.TRENDING_DOWN

        if k < 20 and d < 20:
            if strong_trend_down:
                return -0.3, f"Stoch oversold in downtrend (K={k:.1f})"
            if k > d:
                return 1.0, f"Stoch oversold bullish cross (K={k:.1f})"
            return 0.7, f"Stoch oversold (K={k:.1f})"
        if k > 80 and d > 80:
            if strong_trend_up:
                return 0.2, f"Stoch overbought in strong uptrend (K={k:.1f})"
            if k < d:
                return -1.0, f"Stoch overbought bearish cross (K={k:.1f})"
            return -0.7, f"Stoch overbought (K={k:.1f})"
        # Mid-zone directional
        score = 0.3 if k > prev_k else -0.3
        return score, ""

    def _score_williams_r(self, ind: TechnicalIndicators) -> Tuple[Optional[float], str]:
        if ind.williams_r is None:
            return None, ""
        wr = ind.williams_r

        strong_trend_up   = (ind.adx or 0) >= 40 and ind.regime == MarketRegime.TRENDING_UP
        strong_trend_down = (ind.adx or 0) >= 40 and ind.regime == MarketRegime.TRENDING_DOWN

        if wr <= -80:
            if strong_trend_down:
                return -0.2, f"Williams %R oversold in downtrend ({wr:.1f})"
            return 0.8, f"Williams %R oversold ({wr:.1f})"
        if wr >= -20:
            if strong_trend_up:
                return 0.2, f"Williams %R overbought in uptrend ({wr:.1f})"
            return -0.8, f"Williams %R overbought ({wr:.1f})"
        score = 0.15 if wr < -50 else -0.15
        return score, ""

    def _score_cci(self, ind: TechnicalIndicators) -> Tuple[Optional[float], str]:
        if ind.cci is None:
            return None, ""
        cci = ind.cci

        strong_trend_up   = (ind.adx or 0) >= 40 and ind.regime == MarketRegime.TRENDING_UP
        strong_trend_down = (ind.adx or 0) >= 40 and ind.regime == MarketRegime.TRENDING_DOWN

        if cci <= -200:
            if strong_trend_down:
                return -0.3, f"CCI extreme oversold in downtrend ({cci:.0f})"
            return 1.0, f"CCI extreme oversold ({cci:.0f})"
        if cci <= -100:
            if strong_trend_down:
                return -0.2, f"CCI oversold in downtrend ({cci:.0f})"
            return 0.7, f"CCI oversold ({cci:.0f})"
        if cci >= 200:
            if strong_trend_up:
                return 0.3, f"CCI extreme overbought in uptrend ({cci:.0f})"
            return -1.0, f"CCI extreme overbought ({cci:.0f})"
        if cci >= 100:
            if strong_trend_up:
                return 0.2, f"CCI overbought in uptrend ({cci:.0f})"
            return -0.7, f"CCI overbought ({cci:.0f})"
        score = np.clip(cci / 100.0 * 0.3, -0.3, 0.3)
        return float(score), ""

    def _score_moving_averages(self, ind: TechnicalIndicators) -> Tuple[Optional[float], str]:
        if ind.current_price is None:
            return None, ""
        price = ind.current_price
        bulls = 0
        bears = 0
        details = []

        # Price vs SMA20
        if ind.sma_20:
            if price > ind.sma_20:
                bulls += 1
            else:
                bears += 1

        # SMA20 vs SMA50
        if ind.sma_20 and ind.sma_50:
            if ind.sma_20 > ind.sma_50:
                bulls += 1
                details.append("MA20>MA50")
            else:
                bears += 1
                details.append("MA20<MA50")

        # Price vs SMA200
        if ind.sma_200:
            if price > ind.sma_200:
                bulls += 1
                details.append("above MA200")
            else:
                bears += 1
                details.append("below MA200")

        # EMA9 vs EMA21
        if ind.ema_9 and ind.ema_21:
            if ind.ema_9 > ind.ema_21:
                bulls += 1
            else:
                bears += 1

        total = bulls + bears
        if total == 0:
            return None, ""

        score = (bulls - bears) / total
        direction = "bullish" if score > 0 else "bearish"
        reason = f"MAs {direction} ({bulls}/{total})" + (f": {', '.join(details)}" if details else "")
        return float(score), reason

    def _score_ichimoku(self, ind: TechnicalIndicators) -> Tuple[Optional[float], str]:
        if ind.ichimoku_a is None or ind.ichimoku_b is None or ind.current_price is None:
            return None, ""
        price = ind.current_price
        cloud_top    = max(ind.ichimoku_a, ind.ichimoku_b)
        cloud_bottom = min(ind.ichimoku_a, ind.ichimoku_b)

        if price > cloud_top:
            score = 0.9
            reason = "Price above Ichimoku cloud (bullish)"
        elif price < cloud_bottom:
            score = -0.9
            reason = "Price below Ichimoku cloud (bearish)"
        else:
            score = 0.0
            reason = "Price inside Ichimoku cloud"

        # Tenkan/Kijun cross
        if ind.ichimoku_conv and ind.ichimoku_base:
            if ind.ichimoku_conv > ind.ichimoku_base:
                score = min(score + 0.1, 1.0)
            else:
                score = max(score - 0.1, -1.0)

        return float(score), reason

    def _score_bollinger(self, ind: TechnicalIndicators) -> Tuple[Optional[float], str]:
        if ind.bb_pct is None or ind.current_price is None:
            return None, ""
        pct = ind.bb_pct  # 0 = lower band, 1 = upper band

        if pct <= 0.05:
            return 0.9, f"At lower Bollinger Band (%B={pct:.2f})"
        if pct >= 0.95:
            return -0.9, f"At upper Bollinger Band (%B={pct:.2f})"
        if pct < 0.20:
            return 0.5, f"Near lower Bollinger Band (%B={pct:.2f})"
        if pct > 0.80:
            return -0.5, f"Near upper Bollinger Band (%B={pct:.2f})"

        # Mid-band: momentum direction
        score = -0.4 * (pct - 0.5) * 2   # Positive below mid, negative above mid
        return float(score), ""

    def _score_keltner(self, ind: TechnicalIndicators) -> Tuple[Optional[float], str]:
        if ind.kc_upper is None or ind.kc_lower is None or ind.current_price is None:
            return None, ""
        price = ind.current_price
        if price < ind.kc_lower:
            return 0.7, "Below Keltner Channel (oversold)"
        if price > ind.kc_upper:
            return -0.7, "Above Keltner Channel (overbought)"
        # Inside KC → neutral
        mid = (ind.kc_upper + ind.kc_lower) / 2
        score = -0.3 * (price - mid) / (ind.kc_upper - mid) if (ind.kc_upper - mid) != 0 else 0.0
        return float(score), ""

    def _score_volume(self, ind: TechnicalIndicators) -> Tuple[Optional[float], str]:
        """Volume confirms or weakens directional signals."""
        if ind.volume_ratio is None:
            return None, ""

        vol_ratio = ind.volume_ratio
        mfi = ind.mfi
        obv_rising = ind.obv is not None and ind.obv_sma is not None and ind.obv > ind.obv_sma

        score = 0.0
        reason = ""

        # OBV trend
        if obv_rising:
            score += 0.4
        elif ind.obv is not None and ind.obv_sma is not None:
            score -= 0.4

        # High volume adds conviction
        if vol_ratio > 1.5:
            score = score * 1.2
            reason = f"High volume ({vol_ratio:.1f}x)"

        # MFI
        if mfi is not None:
            if mfi < 20:
                score += 0.4
                reason = f"MFI oversold ({mfi:.1f})"
            elif mfi > 80:
                score -= 0.4
                reason = f"MFI overbought ({mfi:.1f})"

        return float(np.clip(score, -1.0, 1.0)), reason

    def _score_stochrsi(self, ind: TechnicalIndicators) -> Tuple[Optional[float], str]:
        """
        StochRSI scorer (C2).
        Applies Stochastic formula to RSI values — more sensitive than plain RSI
        and more stable than plain Stochastic. Confirms RSI extremes.
        Values are in 0-100 scale (converted from ta's 0-1 output on ingestion).
        """
        if ind.stochrsi_k is None or ind.stochrsi_d is None:
            return None, ""
        if np.isnan(ind.stochrsi_k) or np.isnan(ind.stochrsi_d):
            return None, ""

        k = ind.stochrsi_k
        d = ind.stochrsi_d

        strong_trend_up   = (ind.adx or 0) >= 40 and ind.regime == MarketRegime.TRENDING_UP
        strong_trend_down = (ind.adx or 0) >= 40 and ind.regime == MarketRegime.TRENDING_DOWN

        # Extreme oversold
        if k < 10:
            if strong_trend_down:
                return -0.2, f"StochRSI extreme oversold in downtrend ({k:.1f})"
            return 1.0, f"StochRSI extreme oversold ({k:.1f})"
        if k < 20:
            if strong_trend_down:
                return -0.1, f"StochRSI oversold in downtrend ({k:.1f})"
            cross_up = k > d
            return (0.8 if cross_up else 0.5), f"StochRSI oversold {'+ K>D' if cross_up else ''}({k:.1f})"

        # Extreme overbought
        if k > 90:
            if strong_trend_up:
                return 0.2, f"StochRSI extreme overbought in uptrend ({k:.1f})"
            return -1.0, f"StochRSI extreme overbought ({k:.1f})"
        if k > 80:
            if strong_trend_up:
                return 0.1, f"StochRSI overbought in uptrend ({k:.1f})"
            cross_down = k < d
            return (-0.8 if cross_down else -0.5), f"StochRSI overbought {'+ K<D' if cross_down else ''}({k:.1f})"

        # Mid-zone: direction of K vs D line
        if k > d:
            score = 0.3 * min((k - d) / 20.0, 1.0)
        else:
            score = -0.3 * min((d - k) / 20.0, 1.0)
        return float(score), ""

    def _score_support_resistance(self, ind: TechnicalIndicators) -> Tuple[Optional[float], str]:
        """Score based on proximity to key S/R levels."""
        if ind.current_price is None or (ind.nearest_support is None and ind.nearest_resistance is None):
            return None, ""

        price = ind.current_price
        score = 0.0
        reason = ""

        if ind.nearest_support is not None:
            dist_support_pct = (price - ind.nearest_support) / price
            if dist_support_pct < 0.002:   # Within 0.2% of support
                score += 0.8
                reason = f"Near support {ind.nearest_support:.5f}"
            elif dist_support_pct < 0.005:  # Within 0.5%
                score += 0.4

        if ind.nearest_resistance is not None:
            dist_resist_pct = (ind.nearest_resistance - price) / price
            if dist_resist_pct < 0.002:
                score -= 0.8
                reason = f"Near resistance {ind.nearest_resistance:.5f}"
            elif dist_resist_pct < 0.005:
                score -= 0.4

        return float(np.clip(score, -1.0, 1.0)), reason


# ------------------------------------------------------------------
# HELPER
# ------------------------------------------------------------------

def ohlcv_to_dataframe(ohlcv_list) -> pd.DataFrame:
    """Convert list of OHLCV objects to pandas DataFrame."""
    data = {
        'timestamp': [bar.timestamp for bar in ohlcv_list],
        'open':      [bar.open      for bar in ohlcv_list],
        'high':      [bar.high      for bar in ohlcv_list],
        'low':       [bar.low       for bar in ohlcv_list],
        'close':     [bar.close     for bar in ohlcv_list],
        'volume':    [bar.volume    for bar in ohlcv_list],
    }
    df = pd.DataFrame(data)
    df.set_index('timestamp', inplace=True)
    return df


# ------------------------------------------------------------------
# STANDALONE TEST
# ------------------------------------------------------------------

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    import sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))

    from data.market_data import MarketDataProvider, DataSource, Timeframe

    print("Testing Advanced Technical Analyzer")
    print("=" * 60)

    provider = MarketDataProvider(primary_source=DataSource.MOCK)
    ohlcv    = provider.get_ohlcv('EURUSD', Timeframe.H1, bars=300)

    if ohlcv:
        df = ohlcv_to_dataframe(ohlcv)
        analyzer  = TechnicalAnalyzer()
        ind = analyzer.calculate_indicators(df)

        print(f"\nPrice:        {ind.current_price:.5f}")
        print(f"RSI:          {ind.rsi:.2f}" if ind.rsi else "RSI: N/A")
        print(f"MACD diff:    {ind.macd_diff:.6f}" if ind.macd_diff else "MACD: N/A")
        print(f"ADX:          {ind.adx:.2f}" if ind.adx else "ADX: N/A")
        print(f"ATR:          {ind.atr:.5f}" if ind.atr else "ATR: N/A")
        print(f"Williams %R:  {ind.williams_r:.2f}" if ind.williams_r else "WR: N/A")
        print(f"CCI:          {ind.cci:.2f}" if ind.cci else "CCI: N/A")
        print(f"MFI:          {ind.mfi:.2f}" if ind.mfi else "MFI: N/A")
        print(f"S/R levels:   {len(ind.sr_levels)}")
        print(f"Regime:       {ind.regime.value}")

        signal, confidence, reason = analyzer.generate_signal(ind)
        print(f"\nSignal:     {signal.value}")
        print(f"Confidence: {confidence*100:.1f}%")
        print(f"Reason:     {reason}")

    print("\n" + "=" * 60)
    print("Test complete!")
