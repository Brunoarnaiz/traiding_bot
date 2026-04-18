"""
Professional Trading Bot - Main Runner
Integrates market data, technical analysis, risk management, and execution
"""
import time
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional
import logging
from dataclasses import dataclass

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.market_data import MarketDataProvider, DataSource, Timeframe
from strategies.technical_analysis import TechnicalAnalyzer, ohlcv_to_dataframe, Signal
from risk.risk_manager import RiskManager, RiskLimits, RiskLevel, AccountState
from bot.mt5_file_bridge import MT5Bridge
from config.credentials import get_trading_config

logger = logging.getLogger(__name__)


@dataclass
class BotConfig:
    """Bot configuration"""
    symbol: str = "EURUSD"
    timeframe: Timeframe = Timeframe.M15
    check_interval_seconds: int = 60
    risk_level: RiskLevel = RiskLevel.MODERATE
    max_trades_per_day: int = 10
    demo_mode: bool = True  # Start in demo mode
    

class TradingBot:
    """
    Professional trading bot with full risk management
    """
    
    def __init__(self, config: BotConfig):
        self.config = config
        self.running = False
        
        # Initialize components
        self.data_provider = MarketDataProvider(primary_source=DataSource.YAHOO_FINANCE)
        self.analyzer = TechnicalAnalyzer()
        self.risk_manager = RiskManager(RiskLimits.from_risk_level(config.risk_level))
        self.bridge = MT5Bridge()
        
        # State
        self.trades_today = 0
        self.last_signal = Signal.NEUTRAL
        self.last_check_time = None
        
        logger.info(f"Trading Bot initialized: {config.symbol} {config.timeframe.value}")
        logger.info(f"Risk level: {config.risk_level.value}, Demo mode: {config.demo_mode}")
    
    def start(self):
        """Start the trading bot"""
        logger.info("="*60)
        logger.info("🤖 Trading Bot Starting...")
        logger.info("="*60)
        
        # Check MT5 connection
        if not self.bridge.check_connection():
            logger.error("❌ MT5 Bridge not responding!")
            logger.error("Make sure MT5 is running with NixBridge EA attached")
            return
        
        logger.info("✓ MT5 Bridge connected")
        
        # Initialize account state
        # TODO: Get real account info from MT5
        initial_balance = 10000.0 if self.config.demo_mode else 10000.0
        self.risk_manager.set_account_state(AccountState(
            balance=initial_balance,
            equity=initial_balance,
            open_positions=0,
            daily_pnl=0.0,
            consecutive_losses=0,
            trades_today=0
        ))
        
        logger.info(f"✓ Account initialized: ${initial_balance:.2f}")
        logger.info("")
        
        self.running = True
        
        try:
            self.run_loop()
        except KeyboardInterrupt:
            logger.info("\\n⚠️  Bot stopped by user")
        except Exception as e:
            logger.error(f"❌ Bot error: {e}", exc_info=True)
        finally:
            self.stop()
    
    def stop(self):
        """Stop the trading bot"""
        self.running = False
        logger.info("Bot stopped")
    
    def run_loop(self):
        """Main trading loop"""
        while self.running:
            try:
                self.check_market()
                time.sleep(self.config.check_interval_seconds)
            except Exception as e:
                logger.error(f"Error in trading loop: {e}", exc_info=True)
                time.sleep(60)  # Wait a minute before retrying
    
    def check_market(self):
        """Check market conditions and execute trades if conditions are met"""
        now = datetime.now()
        
        logger.info(f"\\n{'='*60}")
        logger.info(f"📊 Market Check: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'='*60}")
        
        # Get market data
        logger.info(f"Fetching {self.config.symbol} data...")
        ohlcv = self.data_provider.get_ohlcv(
            self.config.symbol,
            self.config.timeframe,
            bars=200  # Need 200 bars for SMA(200)
        )
        
        if not ohlcv or len(ohlcv) < 50:
            logger.warning("⚠️  Insufficient market data")
            return
        
        logger.info(f"✓ Received {len(ohlcv)} bars")
        
        # Convert to dataframe
        df = ohlcv_to_dataframe(ohlcv)
        
        # Calculate indicators
        logger.info("Calculating technical indicators...")
        indicators = self.analyzer.calculate_indicators(df)
        
        # Display key indicators
        logger.info(f"\\n📈 Current Market State:")
        logger.info(f"   Price: {indicators.current_price:.5f}")
        logger.info(f"   RSI(14): {f'{indicators.rsi:.2f}' if indicators.rsi is not None else 'N/A'}")
        logger.info(f"   MACD: {f'{indicators.macd:.5f}' if indicators.macd is not None else 'N/A'}")
        logger.info(f"   ADX: {f'{indicators.adx:.2f}' if indicators.adx is not None else 'N/A'}")
        logger.info(f"   ATR: {f'{indicators.atr:.5f}' if indicators.atr is not None else 'N/A'}")
        
        # Generate trading signal
        signal, confidence, reason = self.analyzer.generate_signal(indicators)
        
        logger.info(f"\\n🎯 Signal: {signal.value} (confidence: {confidence*100:.1f}%)")
        logger.info(f"   Reason: {reason}")
        
        # Check if we should trade
        if signal in [Signal.STRONG_BUY, Signal.BUY]:
            self.execute_buy_signal(indicators, signal, confidence)
        elif signal in [Signal.STRONG_SELL, Signal.SELL]:
            self.execute_sell_signal(indicators, signal, confidence)
        else:
            logger.info("   → No action (neutral signal)")
        
        self.last_check_time = now
        self.last_signal = signal
    
    def execute_buy_signal(self, indicators, signal: Signal, confidence: float):
        """Execute a buy trade"""
        logger.info("\\n💰 Evaluating BUY opportunity...")
        
        # Minimum confidence threshold (lowered to 50% for more trades)
        min_confidence = 0.5 if signal == Signal.STRONG_BUY else 0.5
        if confidence < min_confidence:
            logger.info(f"   ✗ Confidence too low ({confidence*100:.1f}% < {min_confidence*100:.1f}%)")
            return
        
        # Check if we can trade
        can_trade, reason = self.risk_manager.can_open_trade()
        if not can_trade:
            logger.info(f"   ✗ Cannot trade: {reason}")
            return
        
        # Create position with risk management
        position = self.risk_manager.create_trade_position(
            symbol=self.config.symbol,
            side="BUY",
            entry_price=indicators.current_price,
            atr=indicators.atr
        )
        
        if position is None:
            logger.warning("   ✗ Failed to create position")
            return
        
        # Execute trade
        if self.config.demo_mode:
            logger.info("\\n🧪 DEMO MODE - Would execute:")
            logger.info(f"   BUY {position.lot_size} lots {position.symbol} @ {position.entry_price:.5f}")
            logger.info(f"   SL: {position.stop_loss:.5f} | TP: {position.take_profit:.5f}")
            logger.info(f"   Risk: ${position.risk_amount:.2f} | Potential: ${position.potential_profit:.2f}")
        else:
            logger.info("\\n🚀 Executing LIVE trade...")
            result = self.bridge.send_market_order(
                symbol=position.symbol,
                side=position.side,
                lot=position.lot_size,
                stop_loss=position.stop_loss,
                take_profit=position.take_profit
            )
            
            if result['success']:
                logger.info(f"   ✓ Order executed: {result['message']}")
                self.trades_today += 1
                # TODO: Track position in database/file
            else:
                logger.error(f"   ✗ Order failed: {result['error']}")
    
    def execute_sell_signal(self, indicators, signal: Signal, confidence: float):
        """Execute a sell trade"""
        logger.info("\\n💰 Evaluating SELL opportunity...")
        
        # Minimum confidence threshold (lowered to 50% for more trades)
        min_confidence = 0.5 if signal == Signal.STRONG_SELL else 0.5
        if confidence < min_confidence:
            logger.info(f"   ✗ Confidence too low ({confidence*100:.1f}% < {min_confidence*100:.1f}%)")
            return
        
        # Check if we can trade
        can_trade, reason = self.risk_manager.can_open_trade()
        if not can_trade:
            logger.info(f"   ✗ Cannot trade: {reason}")
            return
        
        # Create position with risk management
        position = self.risk_manager.create_trade_position(
            symbol=self.config.symbol,
            side="SELL",
            entry_price=indicators.current_price,
            atr=indicators.atr
        )
        
        if position is None:
            logger.warning("   ✗ Failed to create position")
            return
        
        # Execute trade
        if self.config.demo_mode:
            logger.info("\\n🧪 DEMO MODE - Would execute:")
            logger.info(f"   SELL {position.lot_size} lots {position.symbol} @ {position.entry_price:.5f}")
            logger.info(f"   SL: {position.stop_loss:.5f} | TP: {position.take_profit:.5f}")
            logger.info(f"   Risk: ${position.risk_amount:.2f} | Potential: ${position.potential_profit:.2f}")
        else:
            logger.info("\\n🚀 Executing LIVE trade...")
            result = self.bridge.send_market_order(
                symbol=position.symbol,
                side=position.side,
                lot=position.lot_size,
                stop_loss=position.stop_loss,
                take_profit=position.take_profit
            )
            
            if result['success']:
                logger.info(f"   ✓ Order executed: {result['message']}")
                self.trades_today += 1
                # TODO: Track position in database/file
            else:
                logger.error(f"   ✗ Order failed: {result['error']}")


def main():
    """Main entry point"""
    # Configure logging
    log_dir = ROOT / 'logs'
    log_dir.mkdir(exist_ok=True)
    
    log_file = log_dir / f'bot_{datetime.now().strftime("%Y%m%d")}.log'
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    
    # Create bot configuration
    config = BotConfig(
        symbol="EURUSD",
        timeframe=Timeframe.M15,
        check_interval_seconds=300,  # Check every 5 minutes
        risk_level=RiskLevel.MODERATE,  # 1% risk per trade, max 3 positions
        demo_mode=False  # Execute real trades on demo account
    )
    
    # Create and start bot
    bot = TradingBot(config)
    bot.start()


if __name__ == '__main__':
    main()
