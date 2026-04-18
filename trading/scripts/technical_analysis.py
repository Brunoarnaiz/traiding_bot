"""
Professional Technical Analysis Module
Calculates indicators and provides analysis tools
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)

try:
    from ta.trend import SMAIndicator, EMAIndicator, MACD, ADXIndicator
    from ta.momentum import RSIIndicator, StochasticOscillator
    from ta.volatility import BollingerBands, AverageTrueRange
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


@dataclass
class TechnicalIndicators:
    """Container for all technical indicators"""
    # Trend indicators
    sma_20: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    ema_12: Optional[float] = None
    ema_26: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_diff: Optional[float] = None
    adx: Optional[float] = None
    
    # Momentum indicators
    rsi: Optional[float] = None
    stoch_k: Optional[float] = None
    stoch_d: Optional[float] = None
    
    # Volatility indicators
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    bb_width: Optional[float] = None
    atr: Optional[float] = None
    
    # Price action
    current_price: Optional[float] = None
    price_change_pct: Optional[float] = None
    
    def __repr__(self):
        return f"TechnicalIndicators(RSI={self.rsi:.2f if self.rsi else 'N/A'}, MACD={self.macd:.5f if self.macd else 'N/A'}, Price={self.current_price:.5f if self.current_price else 'N/A'})"


class TechnicalAnalyzer:
    """
    Professional technical analysis engine
    Calculates indicators and generates trading signals
    """
    
    def __init__(self):
        if not TA_AVAILABLE:
            logger.error("Technical analysis library not available")
    
    def calculate_indicators(self, df: pd.DataFrame) -> TechnicalIndicators:
        """
        Calculate all technical indicators from OHLCV dataframe
        
        Args:
            df: DataFrame with columns [timestamp, open, high, low, close, volume]
        
        Returns:
            TechnicalIndicators object with all calculated values
        """
        if not TA_AVAILABLE:
            return TechnicalIndicators()
        
        if len(df) < 200:
            logger.warning(f"Only {len(df)} bars available, some indicators may be unreliable")
        
        indicators = TechnicalIndicators()
        
        try:
            # Current price
            indicators.current_price = df['close'].iloc[-1]
            indicators.price_change_pct = ((df['close'].iloc[-1] / df['close'].iloc[-2]) - 1) * 100
            
            # Trend indicators
            if len(df) >= 20:
                sma_20 = SMAIndicator(close=df['close'], window=20)
                indicators.sma_20 = sma_20.sma_indicator().iloc[-1]
            
            if len(df) >= 50:
                sma_50 = SMAIndicator(close=df['close'], window=50)
                indicators.sma_50 = sma_50.sma_indicator().iloc[-1]
            
            if len(df) >= 200:
                sma_200 = SMAIndicator(close=df['close'], window=200)
                indicators.sma_200 = sma_200.sma_indicator().iloc[-1]
            
            if len(df) >= 26:
                ema_12 = EMAIndicator(close=df['close'], window=12)
                ema_26 = EMAIndicator(close=df['close'], window=26)
                indicators.ema_12 = ema_12.ema_indicator().iloc[-1]
                indicators.ema_26 = ema_26.ema_indicator().iloc[-1]
            
            if len(df) >= 35:
                macd = MACD(close=df['close'])
                indicators.macd = macd.macd().iloc[-1]
                indicators.macd_signal = macd.macd_signal().iloc[-1]
                indicators.macd_diff = macd.macd_diff().iloc[-1]
            
            if len(df) >= 26:
                adx = ADXIndicator(high=df['high'], low=df['low'], close=df['close'], window=14)
                indicators.adx = adx.adx().iloc[-1]
            
            # Momentum indicators
            if len(df) >= 14:
                rsi = RSIIndicator(close=df['close'], window=14)
                indicators.rsi = rsi.rsi().iloc[-1]
            
            if len(df) >= 14:
                stoch = StochasticOscillator(
                    high=df['high'], 
                    low=df['low'], 
                    close=df['close'],
                    window=14,
                    smooth_window=3
                )
                indicators.stoch_k = stoch.stoch().iloc[-1]
                indicators.stoch_d = stoch.stoch_signal().iloc[-1]
            
            # Volatility indicators
            if len(df) >= 20:
                bb = BollingerBands(close=df['close'], window=20, window_dev=2)
                indicators.bb_upper = bb.bollinger_hband().iloc[-1]
                indicators.bb_middle = bb.bollinger_mavg().iloc[-1]
                indicators.bb_lower = bb.bollinger_lband().iloc[-1]
                indicators.bb_width = bb.bollinger_wband().iloc[-1]
            
            if len(df) >= 14:
                atr = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'], window=14)
                indicators.atr = atr.average_true_range().iloc[-1]
            
        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")
        
        return indicators
    
    def generate_signal(self, indicators: TechnicalIndicators) -> tuple[Signal, float, str]:
        """
        Generate trading signal based on multiple indicators
        
        Returns:
            (signal, confidence, reason)
        """
        if not indicators.current_price:
            return Signal.NEUTRAL, 0.0, "No data available"
        
        signals = []
        reasons = []
        
        # RSI Analysis
        if indicators.rsi is not None:
            if indicators.rsi < 30:
                signals.append(2)  # Strong buy
                reasons.append(f"RSI oversold ({indicators.rsi:.1f})")
            elif indicators.rsi < 40:
                signals.append(1)  # Buy
                reasons.append(f"RSI low ({indicators.rsi:.1f})")
            elif indicators.rsi > 70:
                signals.append(-2)  # Strong sell
                reasons.append(f"RSI overbought ({indicators.rsi:.1f})")
            elif indicators.rsi > 60:
                signals.append(-1)  # Sell
                reasons.append(f"RSI high ({indicators.rsi:.1f})")
        
        # MACD Analysis
        if indicators.macd is not None and indicators.macd_signal is not None:
            if indicators.macd > indicators.macd_signal and indicators.macd_diff > 0:
                signals.append(1)
                reasons.append("MACD bullish crossover")
            elif indicators.macd < indicators.macd_signal and indicators.macd_diff < 0:
                signals.append(-1)
                reasons.append("MACD bearish crossover")
        
        # Moving Average Analysis
        if indicators.sma_20 and indicators.sma_50:
            if indicators.current_price > indicators.sma_20 > indicators.sma_50:
                signals.append(1)
                reasons.append("Price above SMAs (bullish)")
            elif indicators.current_price < indicators.sma_20 < indicators.sma_50:
                signals.append(-1)
                reasons.append("Price below SMAs (bearish)")
        
        # Bollinger Bands Analysis
        if indicators.bb_upper and indicators.bb_lower:
            if indicators.current_price <= indicators.bb_lower:
                signals.append(1)
                reasons.append("Price at lower Bollinger Band")
            elif indicators.current_price >= indicators.bb_upper:
                signals.append(-1)
                reasons.append("Price at upper Bollinger Band")
        
        # ADX Trend Strength
        if indicators.adx is not None:
            if indicators.adx > 25:
                reasons.append(f"Strong trend (ADX {indicators.adx:.1f})")
            elif indicators.adx < 20:
                reasons.append(f"Weak trend (ADX {indicators.adx:.1f})")
        
        # Calculate overall signal
        if not signals:
            return Signal.NEUTRAL, 0.0, "Insufficient data for signal"
        
        avg_signal = sum(signals) / len(signals)
        confidence = min(abs(avg_signal) / 2.0, 1.0)
        
        # Determine final signal
        if avg_signal >= 1.5:
            final_signal = Signal.STRONG_BUY
        elif avg_signal >= 0.5:
            final_signal = Signal.BUY
        elif avg_signal <= -1.5:
            final_signal = Signal.STRONG_SELL
        elif avg_signal <= -0.5:
            final_signal = Signal.SELL
        else:
            final_signal = Signal.NEUTRAL
        
        reason = "; ".join(reasons[:3])  # Top 3 reasons
        
        return final_signal, confidence, reason


def ohlcv_to_dataframe(ohlcv_list) -> pd.DataFrame:
    """Convert list of OHLCV objects to pandas DataFrame"""
    data = {
        'timestamp': [bar.timestamp for bar in ohlcv_list],
        'open': [bar.open for bar in ohlcv_list],
        'high': [bar.high for bar in ohlcv_list],
        'low': [bar.low for bar in ohlcv_list],
        'close': [bar.close for bar in ohlcv_list],
        'volume': [bar.volume for bar in ohlcv_list]
    }
    df = pd.DataFrame(data)
    df.set_index('timestamp', inplace=True)
    return df


if __name__ == '__main__':
    # Test the analyzer
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Technical Analyzer")
    print("="*60)
    
    # Generate mock data
    import sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(ROOT))
    
    from data.market_data import MarketDataProvider, DataSource, Timeframe
    
    provider = MarketDataProvider(primary_source=DataSource.MOCK)
    ohlcv = provider.get_ohlcv('EURUSD', Timeframe.H1, bars=200)
    
    if ohlcv:
        df = ohlcv_to_dataframe(ohlcv)
        
        analyzer = TechnicalAnalyzer()
        indicators = analyzer.calculate_indicators(df)
        
        print("\n📊 Technical Indicators:")
        print(f"   Current Price: {indicators.current_price:.5f}")
        print(f"   RSI(14): {f'{indicators.rsi:.2f}' if indicators.rsi is not None else 'N/A'}")
        print(f"   MACD: {f'{indicators.macd:.5f}' if indicators.macd is not None else 'N/A'}")
        print(f"   MACD Signal: {f'{indicators.macd_signal:.5f}' if indicators.macd_signal is not None else 'N/A'}")
        print(f"   ADX: {f'{indicators.adx:.2f}' if indicators.adx is not None else 'N/A'}")
        print(f"   ATR: {f'{indicators.atr:.5f}' if indicators.atr is not None else 'N/A'}")
        
        signal, confidence, reason = analyzer.generate_signal(indicators)
        
        print(f"\n🎯 Trading Signal:")
        print(f"   Signal: {signal.value}")
        print(f"   Confidence: {confidence*100:.1f}%")
        print(f"   Reason: {reason}")
    
    print("\n" + "="*60)
    print("Test complete!")
