"""
Market Context Analysis
Analyzes market conditions to filter trading opportunities
"""
from datetime import datetime, time
from typing import Dict, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class MarketContext:
    """Market context information"""
    is_trading_hours: bool
    volatility_level: str  # LOW, NORMAL, HIGH, EXTREME
    trend_strength: str  # WEAK, MODERATE, STRONG
    market_phase: str  # RANGING, TRENDING, BREAKOUT
    should_trade: bool
    reason: str


class MarketContextAnalyzer:
    """
    Analyzes market context to determine if conditions are favorable for trading
    """
    
    def __init__(self):
        # Trading hours (UTC) - avoid low liquidity periods
        self.trading_hours = {
            'london_open': time(7, 0),
            'london_close': time(16, 0),
            'ny_open': time(13, 0),
            'ny_close': time(22, 0)
        }
        
        # Volatility thresholds (ATR-based)
        self.volatility_thresholds = {
            'low': 0.0005,
            'normal': 0.0015,
            'high': 0.0025,
            'extreme': 0.0040
        }
        
        # ADX thresholds for trend strength
        self.adx_thresholds = {
            'weak': 20,
            'moderate': 25,
            'strong': 40
        }
    
    def analyze(self, indicators, current_time: datetime = None) -> MarketContext:
        """
        Analyze market context and determine if we should trade
        
        Args:
            indicators: TechnicalIndicators object
            current_time: Current datetime (defaults to now)
        
        Returns:
            MarketContext object
        """
        if current_time is None:
            current_time = datetime.utcnow()
        
        # Check trading hours
        is_trading_hours = self._is_trading_hours(current_time)
        
        # Analyze volatility
        volatility_level = self._analyze_volatility(indicators.atr)
        
        # Analyze trend strength
        trend_strength = self._analyze_trend_strength(indicators.adx)
        
        # Determine market phase
        market_phase = self._determine_market_phase(indicators)
        
        # Decide if we should trade
        should_trade, reason = self._should_trade(
            is_trading_hours,
            volatility_level,
            trend_strength,
            market_phase
        )
        
        return MarketContext(
            is_trading_hours=is_trading_hours,
            volatility_level=volatility_level,
            trend_strength=trend_strength,
            market_phase=market_phase,
            should_trade=should_trade,
            reason=reason
        )
    
    def _is_trading_hours(self, current_time: datetime) -> bool:
        """Check if current time is within major trading sessions"""
        current_time_utc = current_time.time()
        
        # London session
        london_active = (
            self.trading_hours['london_open'] <= current_time_utc <= self.trading_hours['london_close']
        )
        
        # New York session
        ny_active = (
            self.trading_hours['ny_open'] <= current_time_utc <= self.trading_hours['ny_close']
        )
        
        # Trade during major sessions
        return london_active or ny_active
    
    def _analyze_volatility(self, atr: float) -> str:
        """Analyze volatility level based on ATR"""
        if atr is None:
            return "UNKNOWN"
        
        if atr < self.volatility_thresholds['low']:
            return "LOW"
        elif atr < self.volatility_thresholds['normal']:
            return "NORMAL"
        elif atr < self.volatility_thresholds['high']:
            return "HIGH"
        else:
            return "EXTREME"
    
    def _analyze_trend_strength(self, adx: float) -> str:
        """Analyze trend strength based on ADX"""
        if adx is None:
            return "UNKNOWN"
        
        if adx < self.adx_thresholds['weak']:
            return "WEAK"
        elif adx < self.adx_thresholds['strong']:
            return "MODERATE"
        else:
            return "STRONG"
    
    def _determine_market_phase(self, indicators) -> str:
        """Determine current market phase"""
        # Check if we have required indicators
        if indicators.bb_upper is None or indicators.bb_lower is None:
            return "UNKNOWN"
        
        # Calculate Bollinger Band width percentage
        bb_width_pct = (indicators.bb_upper - indicators.bb_lower) / indicators.current_price * 100
        
        # Check ADX for trend
        if indicators.adx is not None:
            if indicators.adx > 25:
                # Strong trend
                return "TRENDING"
            elif indicators.adx < 20 and bb_width_pct < 2.0:
                # Weak trend and tight bands = ranging
                return "RANGING"
        
        # Check for potential breakout (tight bands with increasing volatility)
        if bb_width_pct < 1.5 and indicators.atr is not None:
            return "BREAKOUT"
        
        return "TRENDING"
    
    def _should_trade(
        self,
        is_trading_hours: bool,
        volatility_level: str,
        trend_strength: str,
        market_phase: str
    ) -> Tuple[bool, str]:
        """
        Determine if we should trade based on market context
        
        Returns:
            (should_trade, reason)
        """
        reasons = []
        
        # Check trading hours
        if not is_trading_hours:
            return False, "Outside major trading sessions (low liquidity)"
        
        # Check volatility
        if volatility_level == "EXTREME":
            return False, "Extreme volatility - too risky"
        
        if volatility_level == "LOW":
            reasons.append("Low volatility")
        
        # Check trend strength for trending strategies
        if trend_strength == "WEAK" and market_phase == "RANGING":
            return False, "Weak trend in ranging market - no clear direction"
        
        # Extreme conditions
        if volatility_level == "UNKNOWN" or trend_strength == "UNKNOWN":
            return False, "Insufficient data for context analysis"
        
        # Good conditions
        if trend_strength in ["MODERATE", "STRONG"] and volatility_level in ["NORMAL", "HIGH"]:
            return True, f"Good conditions: {trend_strength} trend, {volatility_level} volatility"
        
        if market_phase == "BREAKOUT" and volatility_level != "LOW":
            return True, "Potential breakout detected"
        
        # Default: allow trading but note conditions
        return True, f"Acceptable conditions: {market_phase} phase, {volatility_level} volatility"


if __name__ == '__main__':
    # Test the analyzer
    logging.basicConfig(level=logging.INFO)
    
    from strategies.technical_analysis import TechnicalIndicators
    
    print("Testing Market Context Analyzer")
    print("="*60)
    
    analyzer = MarketContextAnalyzer()
    
    # Test case 1: Good conditions
    indicators = TechnicalIndicators(
        current_price=1.10000,
        atr=0.00150,
        adx=28.5,
        bb_upper=1.10200,
        bb_lower=1.09800
    )
    
    context = analyzer.analyze(indicators)
    
    print("\n📊 Market Context:")
    print(f"  Trading hours: {context.is_trading_hours}")
    print(f"  Volatility: {context.volatility_level}")
    print(f"  Trend strength: {context.trend_strength}")
    print(f"  Market phase: {context.market_phase}")
    print(f"  Should trade: {context.should_trade}")
    print(f"  Reason: {context.reason}")
    
    print("\n" + "="*60)
    print("Test complete!")
