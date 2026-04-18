"""
Position Tracking System
Tracks all open and closed positions with full history
"""
import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Union
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class Position:
    """Represents a trading position"""
    position_id: str
    symbol: str
    side: str  # 'BUY' or 'SELL'
    entry_price: float
    lot_size: float
    stop_loss: float
    take_profit: float
    entry_time: str
    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    pnl: Optional[float] = None
    status: str = "OPEN"  # OPEN, CLOSED, CANCELLED
    risk_amount: float = 0.0
    potential_profit: float = 0.0
    # Exit management (A1/A2/A3)
    trailing_stop_pips: Optional[float] = None    # A1: pips distance for trailing SL
    breakeven_trigger_pips: Optional[float] = None # A3: pips profit to activate breakeven
    breakeven_activated: bool = False              # A3: True once SL moved to entry
    trailing_ma_period: Optional[int] = None       # A2: EMA period for MA trailing

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'Position':
        """Create from dictionary, tolerant of missing fields from older saves."""
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


class PositionTracker:
    """
    Tracks all trading positions with persistence
    """
    
    def __init__(self, data_file: Union[str, Path, None] = None):
        if data_file is None:
            # Default: absolute path relative to project root
            data_file = Path(__file__).resolve().parents[1] / 'data' / 'positions.json'
        self.data_file = Path(data_file)
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        self.positions: List[Position] = []
        self.load()
    
    def load(self):
        """Load positions from file"""
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    self.positions = [Position.from_dict(p) for p in data]
                logger.info(f"Loaded {len(self.positions)} positions from {self.data_file}")
            except Exception as e:
                logger.error(f"Error loading positions: {e}")
                self.positions = []
        else:
            self.positions = []
    
    def save(self):
        """Save positions to file"""
        try:
            with open(self.data_file, 'w') as f:
                json.dump([p.to_dict() for p in self.positions], f, indent=2)
            logger.debug(f"Saved {len(self.positions)} positions to {self.data_file}")
        except Exception as e:
            logger.error(f"Error saving positions: {e}")
    
    def add_position(self, position: Position):
        """Add a new position"""
        self.positions.append(position)
        self.save()
        logger.info(f"Added position {position.position_id}: {position.side} {position.lot_size} {position.symbol}")
    
    def close_position(self, position_id: str, exit_price: float, pnl: float):
        """Close a position"""
        for pos in self.positions:
            if pos.position_id == position_id and pos.status == "OPEN":
                pos.exit_price = exit_price
                pos.exit_time = datetime.now().isoformat()
                pos.pnl = pnl
                pos.status = "CLOSED"
                self.save()
                logger.info(f"Closed position {position_id}: PnL ${pnl:.2f}")
                return True
        logger.warning(f"Position {position_id} not found or already closed")
        return False
    
    def get_open_positions(self) -> List[Position]:
        """Get all open positions"""
        return [p for p in self.positions if p.status == "OPEN"]
    
    def get_closed_positions(self) -> List[Position]:
        """Get all closed positions"""
        return [p for p in self.positions if p.status == "CLOSED"]
    
    def get_position_by_id(self, position_id: str) -> Optional[Position]:
        """Get position by ID"""
        for pos in self.positions:
            if pos.position_id == position_id:
                return pos
        return None
    
    def get_daily_pnl(self) -> float:
        """Calculate today's PnL"""
        today = datetime.now().date()
        daily_pnl = 0.0
        
        for pos in self.positions:
            if pos.status == "CLOSED" and pos.exit_time:
                exit_date = datetime.fromisoformat(pos.exit_time).date()
                if exit_date == today and pos.pnl is not None:
                    daily_pnl += pos.pnl
        
        return daily_pnl
    
    def get_statistics(self) -> Dict:
        """Get trading statistics"""
        closed = self.get_closed_positions()
        
        if not closed:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0
            }
        
        winning = [p for p in closed if p.pnl and p.pnl > 0]
        losing = [p for p in closed if p.pnl and p.pnl < 0]
        
        total_pnl = sum(p.pnl for p in closed if p.pnl)
        total_wins = sum(p.pnl for p in winning if p.pnl)
        total_losses = abs(sum(p.pnl for p in losing if p.pnl))
        
        return {
            'total_trades': len(closed),
            'winning_trades': len(winning),
            'losing_trades': len(losing),
            'win_rate': len(winning) / len(closed) * 100 if closed else 0.0,
            'total_pnl': total_pnl,
            'avg_win': total_wins / len(winning) if winning else 0.0,
            'avg_loss': total_losses / len(losing) if losing else 0.0,
            'profit_factor': total_wins / total_losses if total_losses > 0 else 0.0
        }
    
    def generate_position_id(self) -> str:
        """Generate a guaranteed-unique position ID."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S%f")
        short_uuid = uuid.uuid4().hex[:6].upper()
        return f"POS_{timestamp}_{short_uuid}"


if __name__ == '__main__':
    # Test the tracker
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Position Tracker")
    print("="*60)
    
    tracker = PositionTracker("data/test_positions.json")
    
    # Add a position
    pos = Position(
        position_id=tracker.generate_position_id(),
        symbol="EURUSD",
        side="BUY",
        entry_price=1.10000,
        lot_size=0.10,
        stop_loss=1.09800,
        take_profit=1.10300,
        entry_time=datetime.now().isoformat(),
        risk_amount=20.0,
        potential_profit=30.0
    )
    
    tracker.add_position(pos)
    
    print(f"\n✓ Added position: {pos.position_id}")
    print(f"  Open positions: {len(tracker.get_open_positions())}")
    
    # Close the position
    tracker.close_position(pos.position_id, 1.10250, 25.0)
    
    print(f"\n✓ Closed position with PnL: $25.00")
    print(f"  Open positions: {len(tracker.get_open_positions())}")
    print(f"  Closed positions: {len(tracker.get_closed_positions())}")
    
    # Statistics
    stats = tracker.get_statistics()
    print(f"\n📊 Statistics:")
    print(f"  Total trades: {stats['total_trades']}")
    print(f"  Win rate: {stats['win_rate']:.1f}%")
    print(f"  Total PnL: ${stats['total_pnl']:.2f}")
    
    print("\n" + "="*60)
    print("Test complete!")
