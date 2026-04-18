"""
Automatic Strategy Selector
Chooses the best strategy based on current market regime and
aggregates signals with regime-aware weighting.

Strategies available:
  1. TechnicalAnalysis   — multi-indicator trend-following
  2. BreakoutStrategy    — range breakouts with volume confirmation
  3. MeanReversionStrategy — ranging market pullbacks
  4. MACrossoverStrategy — EMA9/EMA21 crossover with SMA200 filter    (B1)
  5. MomentumStrategy    — RSI momentum + EMA alignment + MACD        (B2)
  6. GuideStrategy       — RSI+StochRSI+SMA200 pullback              (B3)

Regime → Strategy mapping:
  TRENDING_UP / TRENDING_DOWN → TA + MACrossover + Momentum dominate
  RANGING                     → MeanReversion + Guide dominate
  BREAKOUT_UP / BREAKOUT_DOWN → Breakout + MACrossover + Momentum dominate
  HIGH_VOLATILITY             → TA dominates; reduced confidence
  UNKNOWN                     → Equal weight, conservative
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import logging

import pandas as pd

from strategies.technical_analysis import (
    TechnicalAnalyzer, TechnicalIndicators, Signal, MarketRegime,
    ohlcv_to_dataframe, IndicatorWeight
)
from strategies.breakout_strategy import BreakoutStrategy, BreakoutConfig
from strategies.mean_reversion import MeanReversionStrategy, MeanReversionConfig
from strategies.ma_crossover import MACrossoverStrategy, MACrossoverConfig
from strategies.momentum_strategy import MomentumStrategy, MomentumConfig
from strategies.guide_strategy import GuideStrategy, GuideStrategyConfig

logger = logging.getLogger(__name__)


@dataclass
class AggregatedSignal:
    """Output from the strategy selector."""
    signal:          Signal
    confidence:      float
    reason:          str
    regime:          MarketRegime
    active_strategy: str          # Which strategy dominated the decision
    # Individual strategy outputs (for transparency)
    ta_signal:       Optional[Signal] = None
    ta_confidence:   Optional[float]  = None
    bo_signal:       Optional[Signal] = None
    bo_confidence:   Optional[float]  = None
    mr_signal:       Optional[Signal] = None
    mr_confidence:   Optional[float]  = None
    mac_signal:      Optional[Signal] = None   # B1 MA Crossover
    mac_confidence:  Optional[float]  = None
    mom_signal:      Optional[Signal] = None   # B2 Momentum
    mom_confidence:  Optional[float]  = None
    gs_signal:       Optional[Signal] = None   # B3 Guide (RSI+StochRSI+SMA200)
    gs_confidence:   Optional[float]  = None
    # Suggested trade params (from dominant strategy if available)
    stop_loss:       Optional[float]  = None
    take_profit:     Optional[float]  = None
    # Market data needed by the bot for position sizing
    current_price:   Optional[float]  = None
    atr:             Optional[float]  = None
    rsi:             Optional[float]  = None
    adx:             Optional[float]  = None


# Map Signal → numeric score for aggregation
_SIGNAL_SCORE: Dict[Signal, float] = {
    Signal.STRONG_BUY:  1.0,
    Signal.BUY:         0.5,
    Signal.NEUTRAL:     0.0,
    Signal.SELL:       -0.5,
    Signal.STRONG_SELL:-1.0,
}


def _score_to_signal(score: float) -> Signal:
    if score >= 0.45:
        return Signal.STRONG_BUY
    if score >= 0.08:
        return Signal.BUY
    if score <= -0.45:
        return Signal.STRONG_SELL
    if score <= -0.08:
        return Signal.SELL
    return Signal.NEUTRAL


class StrategySelector:
    """
    Aggregates signals from 6 strategies, weighted by market regime.

    Usage:
        selector = StrategySelector()
        signal   = selector.select(df)
    """

    # Regime → weights (ta, breakout, mean_reversion, ma_crossover, momentum, guide)
    # Each row sums to 1.0
    _REGIME_WEIGHTS: Dict[MarketRegime, Tuple[float, float, float, float, float, float]] = {
        #                                    TA     BO    MR    MAC   MOM   GS
        MarketRegime.TRENDING_UP:    (0.30, 0.10, 0.05, 0.25, 0.25, 0.05),
        MarketRegime.TRENDING_DOWN:  (0.30, 0.10, 0.05, 0.25, 0.25, 0.05),
        MarketRegime.RANGING:        (0.15, 0.05, 0.30, 0.05, 0.05, 0.40),
        MarketRegime.BREAKOUT_UP:    (0.20, 0.35, 0.05, 0.20, 0.15, 0.05),
        MarketRegime.BREAKOUT_DOWN:  (0.20, 0.35, 0.05, 0.20, 0.15, 0.05),
        MarketRegime.HIGH_VOLATILITY:(0.45, 0.10, 0.05, 0.15, 0.20, 0.05),
        MarketRegime.UNKNOWN:        (0.25, 0.15, 0.15, 0.15, 0.15, 0.15),
    }

    # Confidence multiplier per regime
    _REGIME_CONF_MULT: Dict[MarketRegime, float] = {
        MarketRegime.TRENDING_UP:    1.00,
        MarketRegime.TRENDING_DOWN:  1.00,
        MarketRegime.RANGING:        0.90,
        MarketRegime.BREAKOUT_UP:    0.95,
        MarketRegime.BREAKOUT_DOWN:  0.95,
        MarketRegime.HIGH_VOLATILITY:0.75,
        MarketRegime.UNKNOWN:        0.70,
    }

    def __init__(
        self,
        ta_weights:  Optional[IndicatorWeight]      = None,
        bo_config:   Optional[BreakoutConfig]       = None,
        mr_config:   Optional[MeanReversionConfig]  = None,
        mac_config:  Optional[MACrossoverConfig]    = None,
        mom_config:  Optional[MomentumConfig]       = None,
        gs_config:   Optional[GuideStrategyConfig]  = None,
    ):
        self.ta  = TechnicalAnalyzer(weights=ta_weights)
        self.bo  = BreakoutStrategy(config=bo_config)
        self.mr  = MeanReversionStrategy(config=mr_config)
        self.mac = MACrossoverStrategy(config=mac_config)
        self.mom = MomentumStrategy(config=mom_config)
        self.gs  = GuideStrategy(config=gs_config)

    def select(self, df: pd.DataFrame) -> AggregatedSignal:
        """
        Run all 6 strategies and return the aggregated best signal.

        Args:
            df: OHLCV DataFrame indexed by timestamp

        Returns:
            AggregatedSignal with the combined decision
        """
        # 1. Technical analysis + regime detection
        ta_indicators = self.ta.calculate_indicators(df)
        ta_sig, ta_conf, ta_reason = self.ta.generate_signal(ta_indicators)
        regime = ta_indicators.regime

        # 2. Existing strategies
        bo_result = self.bo.analyze(df)
        mr_result = self.mr.analyze(df)

        # 3. New strategies (B1, B2, B3)
        mac_result = self.mac.analyze(df)
        mom_result = self.mom.analyze(df)
        gs_result  = self.gs.analyze(df)

        # Unpack signals and confidences
        bo_sig,  bo_conf  = bo_result.signal,  bo_result.confidence
        mr_sig,  mr_conf  = mr_result.signal,  mr_result.confidence
        mac_sig, mac_conf = mac_result.signal, mac_result.confidence
        mom_sig, mom_conf = mom_result.signal, mom_result.confidence
        gs_sig,  gs_conf  = gs_result.signal,  gs_result.confidence

        # 4. Weighted aggregation
        w_ta, w_bo, w_mr, w_mac, w_mom, w_gs = self._REGIME_WEIGHTS.get(
            regime, (0.25, 0.15, 0.15, 0.15, 0.15, 0.15)
        )

        def weighted_entry(sig: Signal, conf: float, weight: float) -> Tuple[float, float]:
            score = _SIGNAL_SCORE.get(sig, 0.0) * conf
            if sig != Signal.NEUTRAL:
                eff_weight = weight
            elif conf > 0:
                eff_weight = weight * 0.2
            else:
                eff_weight = 0.0
            return score * weight, eff_weight

        ta_ws,  ta_ww  = weighted_entry(ta_sig,  ta_conf,  w_ta)
        bo_ws,  bo_ww  = weighted_entry(bo_sig,  bo_conf,  w_bo)
        mr_ws,  mr_ww  = weighted_entry(mr_sig,  mr_conf,  w_mr)
        mac_ws, mac_ww = weighted_entry(mac_sig, mac_conf, w_mac)
        mom_ws, mom_ww = weighted_entry(mom_sig, mom_conf, w_mom)
        gs_ws,  gs_ww  = weighted_entry(gs_sig,  gs_conf,  w_gs)

        total_w   = ta_ww + bo_ww + mr_ww + mac_ww + mom_ww + gs_ww
        raw_score = (
            (ta_ws + bo_ws + mr_ws + mac_ws + mom_ws + gs_ws) / total_w
            if total_w > 0 else 0.0
        )

        conf_mult  = self._REGIME_CONF_MULT.get(regime, 0.80)
        confidence = min(abs(raw_score) * conf_mult, 1.0)
        final_signal = _score_to_signal(raw_score)

        # 5. Dominant strategy for labeling + trade params
        contributions = {
            'TechnicalAnalysis': abs(ta_ws),
            'BreakoutStrategy':  abs(bo_ws),
            'MeanReversion':     abs(mr_ws),
            'MACrossover':       abs(mac_ws),
            'Momentum':          abs(mom_ws),
            'GuideStrategy':     abs(gs_ws),
        }
        active_strategy = max(contributions, key=contributions.get)

        # Trade params from dominant strategy (when SL/TP provided)
        sl = tp = None
        _sl_tp_map = {
            'BreakoutStrategy': (bo_result.stop_loss,  bo_result.take_profit),
            'MeanReversion':    (mr_result.stop_loss,  mr_result.take_profit),
            'MACrossover':      (mac_result.stop_loss, mac_result.take_profit),
            'Momentum':         (mom_result.stop_loss, mom_result.take_profit),
            'GuideStrategy':    (gs_result.stop_loss,  gs_result.take_profit),
        }
        if active_strategy in _sl_tp_map:
            sl, tp = _sl_tp_map[active_strategy]

        # Reason assembly
        parts = [
            f"Regime: {regime.value}",
            f"TA: {ta_sig.value}({ta_conf*100:.0f}%)",
            f"BO: {bo_sig.value}({bo_conf*100:.0f}%)",
            f"MR: {mr_sig.value}({mr_conf*100:.0f}%)",
            f"MAC: {mac_sig.value}({mac_conf*100:.0f}%)",
            f"MOM: {mom_sig.value}({mom_conf*100:.0f}%)",
            f"GS: {gs_sig.value}({gs_conf*100:.0f}%)",
            f"Score: {raw_score:+.3f}",
        ]
        reason = " | ".join(parts)

        return AggregatedSignal(
            signal          = final_signal,
            confidence      = round(confidence, 3),
            reason          = reason,
            regime          = regime,
            active_strategy = active_strategy,
            ta_signal       = ta_sig,
            ta_confidence   = round(ta_conf, 3),
            bo_signal       = bo_sig,
            bo_confidence   = round(bo_conf, 3),
            mr_signal       = mr_sig,
            mr_confidence   = round(mr_conf, 3),
            mac_signal      = mac_sig,
            mac_confidence  = round(mac_conf, 3),
            mom_signal      = mom_sig,
            mom_confidence  = round(mom_conf, 3),
            gs_signal       = gs_sig,
            gs_confidence   = round(gs_conf, 3),
            stop_loss       = sl,
            take_profit     = tp,
            current_price   = ta_indicators.current_price,
            atr             = ta_indicators.atr,
            rsi             = ta_indicators.rsi,
            adx             = ta_indicators.adx,
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
    logging.basicConfig(level=logging.WARNING)

    from data.market_data import MarketDataProvider, DataSource, Timeframe

    provider = MarketDataProvider(primary_source=DataSource.MOCK)
    ohlcv    = provider.get_ohlcv('EURUSD', Timeframe.H1, bars=500)
    df = ohlcv_to_dataframe(ohlcv)

    selector = StrategySelector()
    result   = selector.select(df)

    print("Strategy Selector Test")
    print("=" * 60)
    print(f"Final Signal:    {result.signal.value}")
    print(f"Confidence:      {result.confidence*100:.1f}%")
    print(f"Active Strategy: {result.active_strategy}")
    print(f"Regime:          {result.regime.value}")
    print(f"\nBreakdown:")
    print(f"  TechnicalAnalysis: {result.ta_signal.value} ({result.ta_confidence*100:.0f}%)")
    print(f"  BreakoutStrategy:  {result.bo_signal.value} ({result.bo_confidence*100:.0f}%)")
    print(f"  MeanReversion:     {result.mr_signal.value} ({result.mr_confidence*100:.0f}%)")
    print(f"\nReason: {result.reason}")
    if result.stop_loss:
        print(f"\nSL: {result.stop_loss:.5f}  |  TP: {result.take_profit:.5f}")
