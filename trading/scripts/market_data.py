"""
Professional Market Data Provider
Supports multiple data sources with automatic fallback
"""
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class DataSource(Enum):
    """Available data sources"""
    MT5_TERMINAL = "mt5_terminal"  # Direct from MT5
    ALPHA_VANTAGE = "alpha_vantage"  # API key required
    YAHOO_FINANCE = "yahoo_finance"  # Free but rate limited
    TWELVE_DATA = "twelve_data"  # API key required
    MOCK = "mock"  # For testing


class Timeframe(Enum):
    """Standard timeframes"""
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


@dataclass
class OHLCV:
    """Open High Low Close Volume data point"""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    
    def __repr__(self):
        return f"OHLCV({self.timestamp.strftime('%Y-%m-%d %H:%M')}, O:{self.open:.5f}, C:{self.close:.5f}, V:{self.volume})"


@dataclass
class Tick:
    """Real-time tick data"""
    timestamp: datetime
    bid: float
    ask: float
    last: float
    volume: float
    
    @property
    def spread(self) -> float:
        return self.ask - self.bid
    
    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


class MarketDataProvider:
    """
    Professional market data provider with multiple sources and fallback
    """
    
    def __init__(self, primary_source: DataSource = DataSource.MT5_TERMINAL):
        self.primary_source = primary_source
        self.fallback_sources = [
            DataSource.YAHOO_FINANCE,
            DataSource.MOCK
        ]
        self.cache = {}
        self.cache_ttl = 60  # seconds
        
    def get_current_price(self, symbol: str) -> Optional[Tick]:
        """Get current price tick"""
        cache_key = f"tick_{symbol}"
        
        # Check cache
        if cache_key in self.cache:
            cached_data, cached_time = self.cache[cache_key]
            if time.time() - cached_time < self.cache_ttl:
                return cached_data
        
        # Try primary source
        tick = self._fetch_tick(symbol, self.primary_source)
        
        # Try fallbacks if primary fails
        if tick is None:
            for source in self.fallback_sources:
                tick = self._fetch_tick(symbol, source)
                if tick is not None:
                    logger.warning(f"Primary source failed, using {source.value}")
                    break
        
        # Cache result
        if tick is not None:
            self.cache[cache_key] = (tick, time.time())
        
        return tick
    
    def get_ohlcv(self, symbol: str, timeframe: Timeframe, bars: int = 100) -> List[OHLCV]:
        """Get historical OHLCV data"""
        cache_key = f"ohlcv_{symbol}_{timeframe.value}_{bars}"
        
        # Check cache
        if cache_key in self.cache:
            cached_data, cached_time = self.cache[cache_key]
            if time.time() - cached_time < self.cache_ttl:
                return cached_data
        
        # Try primary source
        data = self._fetch_ohlcv(symbol, timeframe, bars, self.primary_source)
        
        # Try fallbacks if primary fails
        if not data:
            for source in self.fallback_sources:
                data = self._fetch_ohlcv(symbol, timeframe, bars, source)
                if data:
                    logger.warning(f"Primary source failed, using {source.value}")
                    break
        
        # Cache result
        if data:
            self.cache[cache_key] = (data, time.time())
        
        return data
    
    def _fetch_tick(self, symbol: str, source: DataSource) -> Optional[Tick]:
        """Fetch tick from specific source"""
        try:
            if source == DataSource.MT5_TERMINAL:
                return self._fetch_tick_mt5(symbol)
            elif source == DataSource.YAHOO_FINANCE:
                return self._fetch_tick_yahoo(symbol)
            elif source == DataSource.MOCK:
                return self._fetch_tick_mock(symbol)
            else:
                logger.error(f"Source {source.value} not implemented for ticks")
                return None
        except Exception as e:
            logger.error(f"Error fetching tick from {source.value}: {e}")
            return None
    
    def _fetch_ohlcv(self, symbol: str, timeframe: Timeframe, bars: int, source: DataSource) -> List[OHLCV]:
        """Fetch OHLCV from specific source"""
        try:
            if source == DataSource.MT5_TERMINAL:
                return self._fetch_ohlcv_mt5(symbol, timeframe, bars)
            elif source == DataSource.YAHOO_FINANCE:
                return self._fetch_ohlcv_yahoo(symbol, timeframe, bars)
            elif source == DataSource.MOCK:
                return self._fetch_ohlcv_mock(symbol, timeframe, bars)
            else:
                logger.error(f"Source {source.value} not implemented for OHLCV")
                return []
        except Exception as e:
            logger.error(f"Error fetching OHLCV from {source.value}: {e}")
            return []
    
    # MT5 Terminal data source
    def _fetch_tick_mt5(self, symbol: str) -> Optional[Tick]:
        """Fetch tick from MT5 terminal via file bridge"""
        # TODO: Implement MT5 tick fetching via enhanced bridge
        logger.debug(f"MT5 tick fetch not yet implemented for {symbol}")
        return None
    
    def _fetch_ohlcv_mt5(self, symbol: str, timeframe: Timeframe, bars: int) -> List[OHLCV]:
        """Fetch OHLCV from MT5 terminal"""
        # TODO: Implement MT5 OHLCV fetching
        logger.debug(f"MT5 OHLCV fetch not yet implemented for {symbol}")
        return []
    
    # Yahoo Finance data source
    def _fetch_tick_yahoo(self, symbol: str) -> Optional[Tick]:
        """Fetch current price from Yahoo Finance"""
        try:
            import yfinance as yf
            
            # Convert forex symbol (EURUSD -> EURUSD=X)
            yahoo_symbol = self._convert_symbol_yahoo(symbol)
            ticker = yf.Ticker(yahoo_symbol)
            info = ticker.info
            
            if 'regularMarketPrice' in info:
                price = info['regularMarketPrice']
                spread = price * 0.0001  # Estimate 1 pip spread
                
                return Tick(
                    timestamp=datetime.now(),
                    bid=price - spread/2,
                    ask=price + spread/2,
                    last=price,
                    volume=info.get('regularMarketVolume', 0)
                )
            
            return None
        except ImportError:
            logger.error("yfinance not installed. Install with: pip install yfinance")
            return None
        except Exception as e:
            logger.error(f"Yahoo Finance error: {e}")
            return None
    
    def _fetch_ohlcv_yahoo(self, symbol: str, timeframe: Timeframe, bars: int) -> List[OHLCV]:
        """Fetch OHLCV from Yahoo Finance"""
        try:
            import yfinance as yf
            import pandas as pd
            
            yahoo_symbol = self._convert_symbol_yahoo(symbol)
            ticker = yf.Ticker(yahoo_symbol)
            
            # Map timeframe to Yahoo interval
            interval_map = {
                Timeframe.M1: "1m",
                Timeframe.M5: "5m",
                Timeframe.M15: "15m",
                Timeframe.M30: "30m",
                Timeframe.H1: "1h",
                Timeframe.H4: "1h",  # Yahoo doesn't have 4h
                Timeframe.D1: "1d"
            }
            
            interval = interval_map.get(timeframe, "1h")
            period = "7d" if interval in ["1m", "5m", "15m", "30m"] else "60d"
            
            df = ticker.history(period=period, interval=interval)
            
            if df.empty:
                return []
            
            # Convert to OHLCV list
            result = []
            for idx, row in df.tail(bars).iterrows():
                result.append(OHLCV(
                    timestamp=idx.to_pydatetime(),
                    open=float(row['Open']),
                    high=float(row['High']),
                    low=float(row['Low']),
                    close=float(row['Close']),
                    volume=float(row['Volume'])
                ))
            
            return result
            
        except ImportError:
            logger.error("yfinance or pandas not installed")
            return []
        except Exception as e:
            logger.error(f"Yahoo Finance OHLCV error: {e}")
            return []
    
    def _convert_symbol_yahoo(self, symbol: str) -> str:
        """Convert trading symbol to Yahoo format"""
        # Forex pairs need =X suffix
        forex_pairs = ['EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'AUDUSD', 'USDCAD', 'NZDUSD']
        if symbol in forex_pairs:
            return f"{symbol}=X"
        return symbol
    
    # Mock data source for testing
    def _fetch_tick_mock(self, symbol: str) -> Tick:
        """Generate mock tick data"""
        import random
        base_price = 1.10 if 'EUR' in symbol else 100.0
        noise = random.gauss(0, 0.0005)
        price = base_price + noise
        spread = base_price * 0.0001
        
        return Tick(
            timestamp=datetime.now(),
            bid=price - spread/2,
            ask=price + spread/2,
            last=price,
            volume=random.randint(10, 100)
        )
    
    def _fetch_ohlcv_mock(self, symbol: str, timeframe: Timeframe, bars: int) -> List[OHLCV]:
        """Generate mock OHLCV data"""
        import random
        
        base_price = 1.10 if 'EUR' in symbol else 100.0
        result = []
        current_time = datetime.now()
        
        # Calculate time delta based on timeframe
        delta_map = {
            Timeframe.M1: timedelta(minutes=1),
            Timeframe.M5: timedelta(minutes=5),
            Timeframe.M15: timedelta(minutes=15),
            Timeframe.M30: timedelta(minutes=30),
            Timeframe.H1: timedelta(hours=1),
            Timeframe.H4: timedelta(hours=4),
            Timeframe.D1: timedelta(days=1)
        }
        delta = delta_map.get(timeframe, timedelta(hours=1))
        
        price = base_price
        for i in range(bars):
            timestamp = current_time - delta * (bars - i)
            
            open_price = price
            change = random.gauss(0, base_price * 0.001)
            close_price = open_price + change
            high_price = max(open_price, close_price) + abs(random.gauss(0, base_price * 0.0005))
            low_price = min(open_price, close_price) - abs(random.gauss(0, base_price * 0.0005))
            volume = random.randint(100, 1000)
            
            result.append(OHLCV(
                timestamp=timestamp,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume
            ))
            
            price = close_price
        
        return result


if __name__ == '__main__':
    # Test the provider
    logging.basicConfig(level=logging.INFO)
    
    provider = MarketDataProvider(primary_source=DataSource.MOCK)
    
    print("Testing Market Data Provider")
    print("="*60)
    
    # Test tick
    print("\n1. Current Tick:")
    tick = provider.get_current_price('EURUSD')
    if tick:
        print(f"   {tick.timestamp.strftime('%H:%M:%S')}")
        print(f"   Bid: {tick.bid:.5f}")
        print(f"   Ask: {tick.ask:.5f}")
        print(f"   Spread: {tick.spread:.5f}")
    
    # Test OHLCV
    print("\n2. Historical Data (last 10 bars, 1H):")
    ohlcv = provider.get_ohlcv('EURUSD', Timeframe.H1, bars=10)
    for bar in ohlcv[-5:]:
        print(f"   {bar}")
    
    print("\n" + "="*60)
    print("Test complete!")
