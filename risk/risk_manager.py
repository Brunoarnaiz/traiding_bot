"""
Professional Risk Management System
Handles position sizing, stop loss, take profit, and risk limits
"""
from dataclasses import dataclass
from typing import Optional, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk tolerance levels"""
    CONSERVATIVE = "conservative"  # 0.5% per trade, 2% daily
    MODERATE = "moderate"          # 1% per trade, 3% daily
    AGGRESSIVE = "aggressive"      # 2% per trade, 5% daily


@dataclass
class RiskLimits:
    """Risk limits configuration"""
    max_risk_per_trade_pct: float = 0.01  # 1% of account per trade
    max_daily_risk_pct: float = 0.03      # 3% of account per day
    max_open_positions: int = 3           # Maximum concurrent positions
    max_leverage: float = 1.0             # No leverage by default
    min_risk_reward_ratio: float = 1.5    # Minimum 1.5:1 reward to risk
    
    # Stop loss settings
    default_sl_pips: int = 20             # Default stop loss in pips
    trailing_sl_enabled: bool = False     # Trailing stop loss
    trailing_sl_distance_pips: int = 15   # Distance for trailing SL
    
    # Take profit settings
    default_tp_pips: int = 30             # Default take profit in pips
    
    # Circuit breakers
    max_consecutive_losses: int = 3       # Stop after X losses in a row
    daily_loss_limit_pct: float = 0.05    # Stop if lose 5% in one day
    
    @classmethod
    def from_risk_level(cls, level: RiskLevel):
        """Create risk limits from risk level preset"""
        if level == RiskLevel.CONSERVATIVE:
            return cls(
                max_risk_per_trade_pct=0.005,
                max_daily_risk_pct=0.02,
                max_open_positions=2,
                max_leverage=1.0,
                default_sl_pips=30,
                default_tp_pips=45,
                daily_loss_limit_pct=0.03
            )
        elif level == RiskLevel.MODERATE:
            return cls(
                max_risk_per_trade_pct=0.01,
                max_daily_risk_pct=0.03,
                max_open_positions=4,
                max_leverage=2.0,
                default_sl_pips=20,
                default_tp_pips=30,
                daily_loss_limit_pct=0.05
            )
        elif level == RiskLevel.AGGRESSIVE:
            return cls(
                max_risk_per_trade_pct=0.02,
                max_daily_risk_pct=0.05,
                max_open_positions=5,
                max_leverage=5.0,
                default_sl_pips=15,
                default_tp_pips=25,
                daily_loss_limit_pct=0.07
            )
        return cls()


@dataclass
class TradePosition:
    """Represents a trade position"""
    symbol: str
    side: str  # 'BUY' or 'SELL'
    entry_price: float
    lot_size: float
    stop_loss: float
    take_profit: float
    risk_amount: float
    potential_profit: float
    
    @property
    def risk_reward_ratio(self) -> float:
        """Calculate risk/reward ratio"""
        if self.risk_amount == 0:
            return 0.0
        return self.potential_profit / self.risk_amount


@dataclass
class AccountState:
    """Current account state"""
    balance: float
    equity: float
    open_positions: int = 0
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    trades_today: int = 0


class RiskManager:
    """
    Professional risk management system
    """
    
    def __init__(self, limits: RiskLimits = None):
        self.limits = limits or RiskLimits()
        self.account_state = None
        
    def set_account_state(self, state: AccountState):
        """Update current account state"""
        self.account_state = state
    
    def can_open_trade(self) -> Tuple[bool, str]:
        """
        Check if a new trade can be opened
        
        Returns:
            (can_trade, reason)
        """
        if not self.account_state:
            return False, "Account state not set"
        
        # Check open positions limit
        if self.account_state.open_positions >= self.limits.max_open_positions:
            return False, f"Maximum {self.limits.max_open_positions} positions already open"
        
        # Check consecutive losses
        if self.account_state.consecutive_losses >= self.limits.max_consecutive_losses:
            return False, f"Stopped after {self.limits.max_consecutive_losses} consecutive losses"
        
        # Check daily loss limit
        daily_loss_pct = abs(self.account_state.daily_pnl / self.account_state.balance)
        if self.account_state.daily_pnl < 0 and daily_loss_pct >= self.limits.daily_loss_limit_pct:
            return False, f"Daily loss limit reached ({daily_loss_pct*100:.1f}%)"
        
        # Check daily risk limit
        if self.account_state.daily_pnl < 0:
            remaining_risk = self.limits.max_daily_risk_pct - daily_loss_pct
            if remaining_risk <= 0:
                return False, "Daily risk limit exhausted"
        
        return True, "OK"
    
    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        symbol: str = "EURUSD",
        side: str = "BUY"
    ) -> Optional[float]:
        """
        Calculate position size based on risk parameters
        
        Args:
            entry_price: Entry price for the trade
            stop_loss: Stop loss price
            symbol: Trading symbol
            side: 'BUY' or 'SELL'
        
        Returns:
            Lot size (or None if trade should not be opened)
        """
        if not self.account_state:
            logger.error("Account state not set")
            return None
        
        can_trade, reason = self.can_open_trade()
        if not can_trade:
            logger.warning(f"Cannot open trade: {reason}")
            return None
        
        # Calculate risk amount in account currency
        max_risk_amount = self.account_state.balance * self.limits.max_risk_per_trade_pct
        
        # Calculate pips risked
        pip_value = 0.0001  # For EUR/USD
        if side == "BUY":
            pips_risked = (entry_price - stop_loss) / pip_value
        else:
            pips_risked = (stop_loss - entry_price) / pip_value
        
        if pips_risked <= 0:
            logger.error(f"Invalid stop loss: pips_risked={pips_risked}")
            return None
        
        # Calculate lot size
        # For standard lot (100,000 units), 1 pip = $10 for EUR/USD
        # For mini lot (10,000 units), 1 pip = $1
        # For micro lot (1,000 units), 1 pip = $0.10
        
        pip_value_per_lot = 10.0  # USD per pip for 1 standard lot (100k)
        risk_per_pip = max_risk_amount / pips_risked
        lot_size = risk_per_pip / pip_value_per_lot
        
        # Round to 2 decimal places (0.01 = 1 micro lot)
        lot_size = round(lot_size, 2)
        
        # Apply minimum and maximum lot size
        min_lot = 0.01  # 1 micro lot
        max_lot = 10.0  # Adjust based on broker
        
        lot_size = max(min_lot, min(lot_size, max_lot))
        
        logger.info(f"Position size calculated: {lot_size} lots (risk: ${max_risk_amount:.2f}, {pips_risked:.1f} pips)")
        
        return lot_size
    
    def calculate_stop_loss(
        self,
        entry_price: float,
        side: str,
        atr: Optional[float] = None,
        symbol: str = "EURUSD"
    ) -> float:
        """
        Calculate stop loss price
        
        Args:
            entry_price: Entry price
            side: 'BUY' or 'SELL'
            atr: Average True Range (optional, for dynamic SL)
            symbol: Trading symbol
        
        Returns:
            Stop loss price
        """
        pip_value = 0.0001
        
        # Use ATR-based stop loss if available (2x ATR)
        if atr is not None and atr > 0:
            sl_distance = atr * 2
        else:
            # Use default pip-based stop loss
            sl_distance = self.limits.default_sl_pips * pip_value
        
        if side == "BUY":
            stop_loss = entry_price - sl_distance
        else:
            stop_loss = entry_price + sl_distance
        
        return round(stop_loss, 5)
    
    def calculate_take_profit(
        self,
        entry_price: float,
        stop_loss: float,
        side: str,
        symbol: str = "EURUSD"
    ) -> float:
        """
        Calculate take profit price based on risk/reward ratio
        
        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            side: 'BUY' or 'SELL'
            symbol: Trading symbol
        
        Returns:
            Take profit price
        """
        # Calculate risk distance
        risk_distance = abs(entry_price - stop_loss)
        
        # Apply minimum risk/reward ratio
        tp_distance = risk_distance * self.limits.min_risk_reward_ratio
        
        if side == "BUY":
            take_profit = entry_price + tp_distance
        else:
            take_profit = entry_price - tp_distance
        
        return round(take_profit, 5)
    
    def create_trade_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        atr: Optional[float] = None,
        stop_loss_override: Optional[float] = None,
        take_profit_override: Optional[float] = None,
    ) -> Optional[TradePosition]:
        """
        Create a complete trade position with all parameters calculated
        
        Returns:
            TradePosition object or None if trade should not be opened
        """
        if not self.account_state:
            logger.error("Account state not set")
            return None
        
        # Check if we can trade
        can_trade, reason = self.can_open_trade()
        if not can_trade:
            logger.warning(f"Cannot create position: {reason}")
            return None

        # Use override SL/TP if provided (strategy-specific), otherwise compute from ATR
        if stop_loss_override is not None:
            stop_loss = stop_loss_override
        else:
            stop_loss = self.calculate_stop_loss(entry_price, side, atr, symbol)

        # ── E1: SL obligatorio ──────────────────────────────────────────
        # Reject the trade if stop_loss is missing, zero, or on the wrong side.
        # This rule is non-negotiable per the trading guide.
        if not stop_loss or stop_loss == 0.0:
            logger.warning(
                f"E1 REJECTED {side} {symbol} @ {entry_price:.5f}: "
                f"stop_loss is missing or zero — never trade without a stop loss"
            )
            return None

        if side == "BUY" and stop_loss >= entry_price:
            logger.warning(
                f"E1 REJECTED {side} {symbol} @ {entry_price:.5f}: "
                f"stop_loss {stop_loss:.5f} is above entry price — invalid SL for BUY"
            )
            return None

        if side == "SELL" and stop_loss <= entry_price:
            logger.warning(
                f"E1 REJECTED {side} {symbol} @ {entry_price:.5f}: "
                f"stop_loss {stop_loss:.5f} is below entry price — invalid SL for SELL"
            )
            return None

        # Position size is always based on the actual SL being used
        lot_size = self.calculate_position_size(entry_price, stop_loss, symbol, side)
        if lot_size is None:
            return None

        if take_profit_override is not None:
            take_profit = take_profit_override
        else:
            take_profit = self.calculate_take_profit(entry_price, stop_loss, side, symbol)

        # ── E3: Ratio TP/SL mínimo ─────────────────────────────────────
        # Reject trades where the actual reward:risk ratio is below the configured minimum.
        # This applies even when TP comes from a strategy override.
        pip_value = 0.0001
        pip_value_per_lot = 10.0

        if side == "BUY":
            risk_pips   = (entry_price - stop_loss) / pip_value
            profit_pips = (take_profit - entry_price) / pip_value
        else:
            risk_pips   = (stop_loss - entry_price) / pip_value
            profit_pips = (entry_price - take_profit) / pip_value

        if risk_pips > 0:
            actual_rr = profit_pips / risk_pips
            if actual_rr < self.limits.min_risk_reward_ratio - 1e-6:
                logger.warning(
                    f"E3 REJECTED {side} {symbol} @ {entry_price:.5f}: "
                    f"R:R={actual_rr:.2f} < minimum {self.limits.min_risk_reward_ratio:.2f} "
                    f"(SL={stop_loss:.5f}, TP={take_profit:.5f})"
                )
                return None

        risk_amount      = risk_pips   * pip_value_per_lot * lot_size
        potential_profit = profit_pips * pip_value_per_lot * lot_size

        position = TradePosition(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            lot_size=lot_size,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_amount=risk_amount,
            potential_profit=potential_profit
        )

        logger.info(f"Trade position created: {side} {lot_size} lots {symbol} @ {entry_price:.5f}")
        logger.info(f"  SL: {stop_loss:.5f} | TP: {take_profit:.5f}")
        logger.info(f"  Risk: ${risk_amount:.2f} | Potential: ${potential_profit:.2f} | R:R={position.risk_reward_ratio:.2f}")

        return position


if __name__ == '__main__':
    # Test the risk manager
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Risk Manager")
    print("="*60)
    
    # Create risk manager with moderate settings
    limits = RiskLimits.from_risk_level(RiskLevel.MODERATE)
    rm = RiskManager(limits)
    
    # Set account state
    account = AccountState(
        balance=10000.0,
        equity=10000.0,
        open_positions=0,
        daily_pnl=0.0,
        consecutive_losses=0
    )
    rm.set_account_state(account)
    
    print("\n💰 Account State:")
    print(f"   Balance: ${account.balance:.2f}")
    print(f"   Max risk per trade: {limits.max_risk_per_trade_pct*100}%")
    print(f"   Max daily risk: {limits.max_daily_risk_pct*100}%")
    
    # Create a trade position
    print("\n📈 Creating trade position:")
    position = rm.create_trade_position(
        symbol="EURUSD",
        side="BUY",
        entry_price=1.10000,
        atr=0.00150
    )
    
    if position:
        print("\n✓ Position created successfully")
        print(f"   {position.side} {position.lot_size} lots {position.symbol}")
        print(f"   Entry: {position.entry_price:.5f}")
        print(f"   Stop Loss: {position.stop_loss:.5f}")
        print(f"   Take Profit: {position.take_profit:.5f}")
        print(f"   Risk: ${position.risk_amount:.2f}")
        print(f"   Potential Profit: ${position.potential_profit:.2f}")
        print(f"   Risk/Reward: {position.risk_reward_ratio:.2f}:1")
    
    print("\n" + "="*60)
    print("Test complete!")
