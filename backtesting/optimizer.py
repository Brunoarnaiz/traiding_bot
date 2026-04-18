"""
Strategy Optimizer
Provides three optimization methods:
  1. Grid Search       — exhaustive parameter sweep
  2. Monte Carlo       — robustness testing via randomized trade sequences
  3. Walk-Forward Test — out-of-sample validation to prevent overfitting
"""
from __future__ import annotations

import copy
import itertools
import math
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtesting.engine import BacktestEngine, BacktestConfig, BacktestResult


# ---------------------------------------------------------------------------
# DATA STRUCTURES
# ---------------------------------------------------------------------------

@dataclass
class GridSearchResult:
    """Result of a single parameter combination."""
    params:           Dict[str, Any]
    net_profit:       float
    total_return_pct: float
    win_rate:         float
    profit_factor:    float
    max_drawdown_pct: float
    sharpe_ratio:     float
    sortino_ratio:    float
    sqn:              float
    total_trades:     int
    score:            float    # Composite optimisation score


@dataclass
class GridSearchSummary:
    """Summary of a grid search run."""
    param_grid:     Dict[str, List[Any]]
    total_runs:     int
    elapsed_secs:   float
    results:        List[GridSearchResult]

    @property
    def best(self) -> Optional[GridSearchResult]:
        return max(self.results, key=lambda r: r.score) if self.results else None

    @property
    def top_10(self) -> List[GridSearchResult]:
        return sorted(self.results, key=lambda r: r.score, reverse=True)[:10]


@dataclass
class MonteCarloResult:
    """Result of a single Monte Carlo simulation."""
    sim_id:           int
    final_balance:    float
    total_return_pct: float
    max_drawdown_pct: float
    win_rate:         float
    profit_factor:    float


@dataclass
class MonteCarloSummary:
    """Summary of a Monte Carlo simulation run."""
    n_simulations:         int
    initial_balance:       float
    results:               List[MonteCarloResult]

    mean_return:           float = 0.0
    median_return:         float = 0.0
    std_return:            float = 0.0

    mean_max_drawdown:     float = 0.0
    worst_drawdown:        float = 0.0

    prob_profitable:       float = 0.0
    prob_loss_over_10pct:  float = 0.0
    var_95:                float = 0.0    # Value at Risk (5th percentile return)
    cvar_95:               float = 0.0   # Conditional VaR


@dataclass
class RobustnessVerdict:
    """Result of an IS vs OOS overfitting check (D1)."""
    verdict:                str    # "ROBUST" | "WARNING" | "OVERFIT"
    efficiency_ratio:       float  # OOS return / IS return
    sharpe_ratio_oos_vs_is: float  # OOS sharpe / IS sharpe  (target ≥ 0.5)
    is_sharpe:              float
    oos_sharpe:             float
    is_return:              float
    oos_return:             float
    is_trades:              int
    oos_trades:             int
    reasons:                List[str]

    @property
    def color(self) -> str:
        return {"ROBUST": "#27ae60", "WARNING": "#f39c12", "OVERFIT": "#e74c3c"}.get(self.verdict, "#aaa")


@dataclass
class MultiSymbolResult:
    """Result for a single symbol in a multi-symbol test (D2)."""
    symbol:      str
    result:      BacktestResult
    passed:      bool   # True if net positive AND drawdown acceptable


@dataclass
class MultiSymbolSummary:
    """Summary of multi-symbol robustness test (D2)."""
    results:     List[MultiSymbolResult]
    n_passed:    int
    n_total:     int
    pass_rate:   float   # 0-100
    verdict:     str     # "ROBUST" | "WARNING" | "SYMBOL_SPECIFIC"

    @property
    def color(self) -> str:
        return {"ROBUST": "#27ae60", "WARNING": "#f39c12", "SYMBOL_SPECIFIC": "#e74c3c"}.get(self.verdict, "#aaa")


@dataclass
class WalkForwardPeriod:
    """Single in-sample/out-of-sample period."""
    period_id:    int
    is_start:     int
    is_end:       int
    oos_start:    int
    oos_end:      int
    best_params:  Dict[str, Any]
    is_result:    BacktestResult
    oos_result:   BacktestResult


@dataclass
class WalkForwardSummary:
    """Summary of walk-forward testing."""
    periods:              List[WalkForwardPeriod]
    combined_oos_return:  float
    combined_oos_trades:  int
    avg_oos_win_rate:     float
    avg_oos_profit_factor: float
    efficiency_ratio:     float   # OOS return / IS return (ideally > 0.5)


# ---------------------------------------------------------------------------
# D1 — OVERFIT DETECTOR
# ---------------------------------------------------------------------------

class OverfitDetector:
    """
    D1: IS vs OOS comparison to detect curve-fitting.

    Takes two BacktestResult objects (in-sample and out-of-sample) and
    computes a RobustnessVerdict with objective pass/fail criteria.

    Verdict thresholds:
      ROBUST  : efficiency ≥ 0.60  AND  OOS sharpe ≥ 0  AND  oos_vs_is_sharpe ≥ 0.50
      WARNING : efficiency ≥ 0.30  OR   oos_vs_is_sharpe ≥ 0.30
      OVERFIT : everything else
    """

    EFFICIENCY_ROBUST  = 0.60
    EFFICIENCY_WARNING = 0.30
    SHARPE_RATIO_ROBUST  = 0.50
    SHARPE_RATIO_WARNING = 0.30
    MIN_OOS_TRADES = 10

    @classmethod
    def compare(
        cls,
        is_result:  BacktestResult,
        oos_result: BacktestResult,
    ) -> RobustnessVerdict:
        """
        Compare IS and OOS BacktestResult and return a verdict.

        Args:
            is_result:  BacktestResult for the in-sample (fitted) period
            oos_result: BacktestResult for the out-of-sample period

        Returns:
            RobustnessVerdict
        """
        reasons: List[str] = []

        is_ret  = is_result.total_return_pct
        oos_ret = oos_result.total_return_pct
        is_sharpe  = is_result.sharpe_ratio
        oos_sharpe = oos_result.sharpe_ratio

        # -- Efficiency ratio (OOS return / IS return) --
        if is_ret == 0.0:
            efficiency = 0.0
            reasons.append("IS return is 0% — cannot compute efficiency ratio")
        elif is_ret < 0.0:
            # IS itself unprofitable → fitting failed; treat efficiency as 0
            efficiency = 0.0
            reasons.append(f"IS period was unprofitable ({is_ret:+.2f}%)")
        else:
            efficiency = oos_ret / is_ret
            if efficiency < 0:
                reasons.append(f"OOS return is negative ({oos_ret:+.2f}%) — strategy flips in OOS")

        efficiency = round(efficiency, 4)

        # -- Sharpe OOS/IS ratio --
        if is_sharpe == 0.0 or is_sharpe < 0.0:
            sharpe_ratio_oos_vs_is = 0.0
            if is_sharpe < 0:
                reasons.append(f"IS Sharpe is negative ({is_sharpe:.3f})")
        else:
            sharpe_ratio_oos_vs_is = oos_sharpe / is_sharpe

        sharpe_ratio_oos_vs_is = round(sharpe_ratio_oos_vs_is, 4)

        # -- Trade count check --
        if oos_result.total_trades < cls.MIN_OOS_TRADES:
            reasons.append(
                f"OOS has only {oos_result.total_trades} trades "
                f"(minimum {cls.MIN_OOS_TRADES} required for statistical significance)"
            )

        # -- OOS profitability --
        if oos_ret < 0:
            reasons.append(f"OOS period is unprofitable ({oos_ret:+.2f}%)")
        if oos_sharpe < 0:
            reasons.append(f"OOS Sharpe is negative ({oos_sharpe:.3f})")

        # -- Drawdown degradation --
        if oos_result.max_drawdown_pct > is_result.max_drawdown_pct * 1.5 and is_result.max_drawdown_pct > 0:
            reasons.append(
                f"OOS drawdown ({oos_result.max_drawdown_pct:.1f}%) is "
                f">150% of IS drawdown ({is_result.max_drawdown_pct:.1f}%)"
            )

        # -- Win-rate decay --
        if is_result.win_rate > 0 and oos_result.win_rate < is_result.win_rate * 0.70:
            reasons.append(
                f"OOS win rate ({oos_result.win_rate:.1f}%) dropped >30% "
                f"vs IS win rate ({is_result.win_rate:.1f}%)"
            )

        # -- Verdict --
        is_robust = (
            efficiency >= cls.EFFICIENCY_ROBUST
            and oos_sharpe >= 0
            and sharpe_ratio_oos_vs_is >= cls.SHARPE_RATIO_ROBUST
        )
        is_warning = (
            efficiency >= cls.EFFICIENCY_WARNING
            or sharpe_ratio_oos_vs_is >= cls.SHARPE_RATIO_WARNING
        )

        if is_robust and not reasons:
            verdict = "ROBUST"
        elif is_warning:
            verdict = "WARNING"
        else:
            verdict = "OVERFIT"

        if not reasons and verdict == "ROBUST":
            reasons.append(
                f"Efficiency {efficiency:.2f} ≥ 0.60  |  "
                f"Sharpe OOS/IS {sharpe_ratio_oos_vs_is:.2f} ≥ 0.50"
            )

        return RobustnessVerdict(
            verdict                = verdict,
            efficiency_ratio       = efficiency,
            sharpe_ratio_oos_vs_is = sharpe_ratio_oos_vs_is,
            is_sharpe              = round(is_sharpe, 4),
            oos_sharpe             = round(oos_sharpe, 4),
            is_return              = round(is_ret, 4),
            oos_return             = round(oos_ret, 4),
            is_trades              = is_result.total_trades,
            oos_trades             = oos_result.total_trades,
            reasons                = reasons,
        )

    @staticmethod
    def print_verdict(v: RobustnessVerdict):
        bar = "=" * 60
        print(f"\n{bar}")
        print(f"  OVERFIT DETECTOR — verdict: {v.verdict}")
        print(f"{'─'*60}")
        print(f"  IS  → return: {v.is_return:+.2f}%  sharpe: {v.is_sharpe:.3f}  trades: {v.is_trades}")
        print(f"  OOS → return: {v.oos_return:+.2f}%  sharpe: {v.oos_sharpe:.3f}  trades: {v.oos_trades}")
        print(f"{'─'*60}")
        print(f"  Efficiency ratio (OOS/IS return):  {v.efficiency_ratio:.3f}  (target ≥ 0.60)")
        print(f"  Sharpe ratio    (OOS/IS sharpe):   {v.sharpe_ratio_oos_vs_is:.3f}  (target ≥ 0.50)")
        print(f"{'─'*60}")
        for r in v.reasons:
            print(f"  • {r}")
        print(f"{bar}\n")


# ---------------------------------------------------------------------------
# D2 — MULTI-SYMBOL TESTER
# ---------------------------------------------------------------------------

class MultiSymbolTester:
    """
    D2: Test a strategy across multiple symbols/instruments.

    Runs the same BacktestConfig on N DataFrames (one per symbol).
    A symbol 'passes' if net profit > 0 AND drawdown < threshold.
    Aggregate pass rate determines the verdict:
      ROBUST         : ≥ 70% of symbols pass
      WARNING        : ≥ 50% of symbols pass
      SYMBOL_SPECIFIC: < 50% pass (strategy works for specific instruments only)
    """

    PASS_RATE_ROBUST  = 70.0
    PASS_RATE_WARNING = 50.0

    def __init__(
        self,
        base_config:   BacktestConfig,
        max_dd_pct:    float = 20.0,    # Max allowed drawdown for "pass"
        min_trades:    int   = 10,      # Min trades to be counted
        verbose:       bool  = True,
    ):
        self.base_config = base_config
        self.max_dd_pct  = max_dd_pct
        self.min_trades  = min_trades
        self.verbose     = verbose

    def run(self, symbol_dfs: Dict[str, pd.DataFrame]) -> MultiSymbolSummary:
        """
        Run backtest on each symbol.

        Args:
            symbol_dfs: Dict mapping symbol name → OHLCV DataFrame

        Returns:
            MultiSymbolSummary
        """
        if self.verbose:
            print(f"\n[Multi-Symbol Test] {len(symbol_dfs)} symbols")
            print(f"  Pass criteria: profit > 0  AND  drawdown < {self.max_dd_pct}%  "
                  f"AND  trades ≥ {self.min_trades}")

        ms_results: List[MultiSymbolResult] = []

        for symbol, df in symbol_dfs.items():
            cfg = copy.copy(self.base_config)
            cfg.symbol = symbol
            try:
                bt = BacktestEngine(cfg).run(df, verbose=False)
            except Exception as e:
                if self.verbose:
                    print(f"  {symbol}: ERROR — {e}")
                continue

            passed = (
                bt.net_profit > 0
                and bt.max_drawdown_pct <= self.max_dd_pct
                and bt.total_trades >= self.min_trades
            )

            ms_results.append(MultiSymbolResult(
                symbol = symbol,
                result = bt,
                passed = passed,
            ))

            if self.verbose:
                status = "PASS" if passed else "FAIL"
                print(
                    f"  {symbol:10s} [{status}]  "
                    f"return={bt.total_return_pct:+.2f}%  "
                    f"dd={bt.max_drawdown_pct:.1f}%  "
                    f"WR={bt.win_rate:.1f}%  "
                    f"trades={bt.total_trades}"
                )

        n_total  = len(ms_results)
        n_passed = sum(1 for r in ms_results if r.passed)
        pass_rate = (n_passed / n_total * 100) if n_total > 0 else 0.0

        if pass_rate >= self.PASS_RATE_ROBUST:
            verdict = "ROBUST"
        elif pass_rate >= self.PASS_RATE_WARNING:
            verdict = "WARNING"
        else:
            verdict = "SYMBOL_SPECIFIC"

        summary = MultiSymbolSummary(
            results    = ms_results,
            n_passed   = n_passed,
            n_total    = n_total,
            pass_rate  = round(pass_rate, 1),
            verdict    = verdict,
        )

        if self.verbose:
            self._print_summary(summary)

        return summary

    @staticmethod
    def _print_summary(s: MultiSymbolSummary):
        print(f"\n{'='*60}")
        print(f"  MULTI-SYMBOL RESULT  — verdict: {s.verdict}")
        print(f"  Pass rate: {s.n_passed}/{s.n_total} symbols ({s.pass_rate:.1f}%)")
        print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# SCORING FUNCTION (can be overridden)
# ---------------------------------------------------------------------------

def default_score(r: BacktestResult) -> float:
    """
    Composite optimisation score that balances return, risk and robustness.

    Formula:
      score = (profit_factor × win_rate%) × sharpe × (1 / (1 + max_dd_pct/10))
              × log(max(total_trades, 1))  × (1 if sqn>1.6 else 0.8)

    Penalises:
      - Low trade count (insufficient sample)
      - High drawdown
      - Negative Sharpe
    """
    if r.total_trades < 5:
        return -999.0

    pf        = max(r.profit_factor, 0.0)
    wr        = r.win_rate / 100
    sharpe    = max(r.sharpe_ratio, -2.0)
    dd_pct    = max(r.max_drawdown_pct, 0.01)
    n_trades  = r.total_trades

    score = (pf * wr) * (1 + sharpe * 0.3) * (1 / (1 + dd_pct / 10))
    score *= math.log(max(n_trades, 1)) / 3
    if r.sqn >= 1.6:
        score *= 1.10

    return round(score, 6)


# ---------------------------------------------------------------------------
# GRID SEARCH
# ---------------------------------------------------------------------------

class GridSearch:
    """
    Exhaustive parameter grid search.

    Example:
        param_grid = {
            'risk_per_trade_pct': [0.005, 0.01, 0.02],
            'atr_sl_multiplier':  [1.5, 2.0, 2.5],
            'min_rr_ratio':       [1.5, 2.0],
        }
        gs = GridSearch(base_config, df)
        summary = gs.run(param_grid)
        print(summary.best.params)
    """

    def __init__(
        self,
        base_config: BacktestConfig,
        df:          pd.DataFrame,
        score_fn:    Optional[Any] = None,
        verbose:     bool = True,
    ):
        self.base_config = base_config
        self.df          = df
        self.score_fn    = score_fn or default_score
        self.verbose     = verbose

    def run(self, param_grid: Dict[str, List[Any]]) -> GridSearchSummary:
        """
        Run grid search over all parameter combinations.

        Args:
            param_grid: Dict mapping config field names to lists of values

        Returns:
            GridSearchSummary with all results sorted by score
        """
        keys   = list(param_grid.keys())
        values = list(param_grid.values())
        combos = list(itertools.product(*values))
        total  = len(combos)

        if self.verbose:
            print(f"\n[Grid Search] {total} combinations × {len(keys)} params")
            print(f"  Params: {keys}")

        start_t = time.time()
        results: List[GridSearchResult] = []

        for i, combo in enumerate(combos, 1):
            params = dict(zip(keys, combo))
            config = self._build_config(params)
            engine = BacktestEngine(config)

            try:
                bt = engine.run(self.df, verbose=False)
                score = self.score_fn(bt)
            except Exception as e:
                if self.verbose:
                    print(f"  [{i}/{total}] ERROR: {e}")
                continue

            gr = GridSearchResult(
                params           = params,
                net_profit       = bt.net_profit,
                total_return_pct = bt.total_return_pct,
                win_rate         = bt.win_rate,
                profit_factor    = bt.profit_factor,
                max_drawdown_pct = bt.max_drawdown_pct,
                sharpe_ratio     = bt.sharpe_ratio,
                sortino_ratio    = bt.sortino_ratio,
                sqn              = bt.sqn,
                total_trades     = bt.total_trades,
                score            = score,
            )
            results.append(gr)

            if self.verbose and (i % max(1, total // 20) == 0 or i == total):
                elapsed = time.time() - start_t
                best_so_far = max(results, key=lambda r: r.score).score if results else 0
                print(f"  [{i:>{len(str(total))}}/{total}] "
                      f"elapsed={elapsed:.1f}s  best_score={best_so_far:.4f}")

        elapsed = time.time() - start_t
        results.sort(key=lambda r: r.score, reverse=True)

        summary = GridSearchSummary(
            param_grid   = param_grid,
            total_runs   = len(results),
            elapsed_secs = round(elapsed, 2),
            results      = results,
        )

        if self.verbose and summary.best:
            self._print_grid_summary(summary)

        return summary

    def _build_config(self, params: Dict[str, Any]) -> BacktestConfig:
        """Create a BacktestConfig from base + override params."""
        config = copy.copy(self.base_config)
        for k, v in params.items():
            if hasattr(config, k):
                setattr(config, k, v)
        return config

    @staticmethod
    def _print_grid_summary(summary: GridSearchSummary):
        best = summary.best
        print(f"\n{'='*60}")
        print(f"  GRID SEARCH COMPLETE  ({summary.total_runs} runs, {summary.elapsed_secs:.1f}s)")
        print(f"{'─'*60}")
        print(f"  Best Score:       {best.score:.4f}")
        print(f"  Best Params:      {best.params}")
        print(f"  Net Profit:       ${best.net_profit:+,.2f} ({best.total_return_pct:+.2f}%)")
        print(f"  Win Rate:         {best.win_rate:.1f}%")
        print(f"  Profit Factor:    {best.profit_factor:.3f}")
        print(f"  Max Drawdown:     -{best.max_drawdown_pct:.2f}%")
        print(f"  Sharpe:           {best.sharpe_ratio:.3f}")
        print(f"  SQN:              {best.sqn:.3f}")
        print(f"  Total Trades:     {best.total_trades}")
        print(f"\n  Top 5 Param Sets:")
        for rank, r in enumerate(summary.top_10[:5], 1):
            print(f"    #{rank}: score={r.score:.4f}  {r.params}")
        print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# MONTE CARLO
# ---------------------------------------------------------------------------

class MonteCarloSimulator:
    """
    Robustness testing via trade-sequence randomization.

    Takes a completed backtest's trade list, shuffles the order N times,
    and measures the distribution of equity curves. This reveals:
      - How much luck contributed to the results
      - Realistic drawdown range
      - Probability of profitable outcomes
    """

    def __init__(self, initial_balance: float = 10_000.0, n_simulations: int = 1000):
        self.initial_balance = initial_balance
        self.n_simulations   = n_simulations

    def run(self, result: BacktestResult, verbose: bool = True) -> MonteCarloSummary:
        """
        Run Monte Carlo simulation on a BacktestResult.

        Args:
            result:  BacktestResult with at least some trades
            verbose: Print summary

        Returns:
            MonteCarloSummary with statistics
        """
        trades = result.trades
        if len(trades) < 5:
            raise ValueError(f"Need at least 5 trades for MC simulation, got {len(trades)}")

        pnls = [t.net_pnl for t in trades]
        sim_results: List[MonteCarloResult] = []

        for sim_id in range(1, self.n_simulations + 1):
            shuffled = random.sample(pnls, len(pnls))
            balance  = self.initial_balance
            peak     = balance
            max_dd   = 0.0
            winners  = 0
            gross_p  = gross_l = 0.0

            for pnl in shuffled:
                balance += pnl
                if balance > peak:
                    peak = balance
                dd = (peak - balance) / peak * 100
                max_dd = max(max_dd, dd)
                if pnl > 0:
                    winners += 1
                    gross_p += pnl
                else:
                    gross_l += abs(pnl)

            n = len(shuffled)
            win_rate      = winners / n * 100
            profit_factor = gross_p / gross_l if gross_l > 0 else float('inf')
            ret_pct       = (balance - self.initial_balance) / self.initial_balance * 100

            sim_results.append(MonteCarloResult(
                sim_id           = sim_id,
                final_balance    = round(balance, 2),
                total_return_pct = round(ret_pct, 3),
                max_drawdown_pct = round(max_dd, 3),
                win_rate         = round(win_rate, 2),
                profit_factor    = round(profit_factor, 3),
            ))

        returns = np.array([r.total_return_pct for r in sim_results])
        drawdowns = np.array([r.max_drawdown_pct for r in sim_results])

        summary = MonteCarloSummary(
            n_simulations        = self.n_simulations,
            initial_balance      = self.initial_balance,
            results              = sim_results,
            mean_return          = round(float(np.mean(returns)), 3),
            median_return        = round(float(np.median(returns)), 3),
            std_return           = round(float(np.std(returns)), 3),
            mean_max_drawdown    = round(float(np.mean(drawdowns)), 3),
            worst_drawdown       = round(float(np.max(drawdowns)), 3),
            prob_profitable      = round(float(np.mean(returns > 0)) * 100, 2),
            prob_loss_over_10pct = round(float(np.mean(returns < -10)) * 100, 2),
            var_95               = round(float(np.percentile(returns, 5)), 3),
            cvar_95              = round(float(np.mean(returns[returns <= np.percentile(returns, 5)])), 3),
        )

        if verbose:
            self._print_summary(summary)
        return summary

    @staticmethod
    def _print_summary(s: MonteCarloSummary):
        print(f"\n{'='*60}")
        print(f"  MONTE CARLO SIMULATION  (n={s.n_simulations:,})")
        print(f"{'─'*60}")
        print(f"  Return Distribution:")
        print(f"    Mean:   {s.mean_return:+.2f}%   Median: {s.median_return:+.2f}%   StdDev: {s.std_return:.2f}%")
        print(f"    VaR 5%: {s.var_95:+.2f}%         CVaR 5%: {s.cvar_95:+.2f}%")
        print(f"  Drawdown:")
        print(f"    Mean Max DD:  {s.mean_max_drawdown:.2f}%")
        print(f"    Worst DD:     {s.worst_drawdown:.2f}%")
        print(f"  Risk Metrics:")
        print(f"    P(profitable):      {s.prob_profitable:.1f}%")
        print(f"    P(loss > 10%):      {s.prob_loss_over_10pct:.1f}%")
        print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# WALK-FORWARD TESTING
# ---------------------------------------------------------------------------

class WalkForwardTester:
    """
    Walk-forward testing to validate out-of-sample performance.

    Splits data into alternating IS (in-sample) and OOS (out-of-sample)
    windows. For each IS period, runs a mini grid search to find optimal
    params, then tests those params on the OOS period.

    This combats curve-fitting and validates strategy robustness.
    """

    def __init__(
        self,
        base_config:    BacktestConfig,
        param_grid:     Dict[str, List[Any]],
        n_periods:      int   = 5,
        is_ratio:       float = 0.70,   # 70% IS, 30% OOS
        score_fn:       Optional[Any] = None,
        verbose:        bool = True,
    ):
        self.base_config = base_config
        self.param_grid  = param_grid
        self.n_periods   = n_periods
        self.is_ratio    = is_ratio
        self.score_fn    = score_fn or default_score
        self.verbose     = verbose

    def run(self, df: pd.DataFrame) -> WalkForwardSummary:
        """
        Run walk-forward test on full dataset.

        Args:
            df: Full OHLCV DataFrame

        Returns:
            WalkForwardSummary with per-period and aggregate metrics
        """
        n       = len(df)
        periods = self._build_periods(n)

        if self.verbose:
            print(f"\n[Walk-Forward] {len(periods)} periods  |  {n} total bars")
            print(f"  IS ratio: {self.is_ratio*100:.0f}%  |  OOS ratio: {(1-self.is_ratio)*100:.0f}%")

        wf_periods: List[WalkForwardPeriod] = []

        for pid, (is_start, is_end, oos_start, oos_end) in enumerate(periods, 1):
            is_df  = df.iloc[is_start:is_end]
            oos_df = df.iloc[oos_start:oos_end]

            if self.verbose:
                print(f"\n  Period {pid}/{len(periods)}:")
                print(f"    IS:  bars {is_start}–{is_end}  ({len(is_df)} bars)")
                print(f"    OOS: bars {oos_start}–{oos_end}  ({len(oos_df)} bars)")

            # Grid search on IS
            gs      = GridSearch(self.base_config, is_df, self.score_fn, verbose=False)
            gs_sum  = gs.run(self.param_grid)
            best_p  = gs_sum.best.params if gs_sum.best else {}

            # Build config with best IS params
            is_config = self._build_config(best_p)

            # Evaluate IS
            is_result = BacktestEngine(is_config).run(is_df, verbose=False)

            # Evaluate OOS with same params (no re-fitting)
            oos_result = BacktestEngine(is_config).run(oos_df, verbose=False)

            if self.verbose:
                print(f"    Best IS params: {best_p}")
                print(f"    IS  return: {is_result.total_return_pct:+.2f}%   "
                      f"WR: {is_result.win_rate:.1f}%   PF: {is_result.profit_factor:.2f}")
                print(f"    OOS return: {oos_result.total_return_pct:+.2f}%   "
                      f"WR: {oos_result.win_rate:.1f}%   PF: {oos_result.profit_factor:.2f}")

            wf_periods.append(WalkForwardPeriod(
                period_id   = pid,
                is_start    = is_start,
                is_end      = is_end,
                oos_start   = oos_start,
                oos_end     = oos_end,
                best_params = best_p,
                is_result   = is_result,
                oos_result  = oos_result,
            ))

        summary = self._build_summary(wf_periods)

        if self.verbose:
            self._print_wf_summary(summary)

        return summary

    def _build_periods(self, n: int) -> List[Tuple[int, int, int, int]]:
        """Build IS/OOS period boundaries."""
        period_size = n // (self.n_periods + 1)
        is_len      = int(period_size * self.is_ratio * (self.n_periods + 1) / self.n_periods)
        oos_len     = period_size - (is_len // self.n_periods)

        periods = []
        start   = 0
        while start + is_len + oos_len <= n and len(periods) < self.n_periods:
            is_start  = start
            is_end    = start + is_len
            oos_start = is_end
            oos_end   = min(oos_start + oos_len, n)
            periods.append((is_start, is_end, oos_start, oos_end))
            start = oos_end  # Walk forward
        return periods

    def _build_config(self, params: Dict[str, Any]) -> BacktestConfig:
        config = copy.copy(self.base_config)
        for k, v in params.items():
            if hasattr(config, k):
                setattr(config, k, v)
        return config

    @staticmethod
    def _build_summary(periods: List[WalkForwardPeriod]) -> WalkForwardSummary:
        if not periods:
            return WalkForwardSummary([], 0, 0, 0, 0, 0)

        oos_returns     = [p.oos_result.total_return_pct for p in periods]
        oos_win_rates   = [p.oos_result.win_rate         for p in periods if p.oos_result.total_trades > 0]
        oos_pf          = [p.oos_result.profit_factor    for p in periods if p.oos_result.profit_factor < 1e6]
        is_returns      = [p.is_result.total_return_pct  for p in periods]
        oos_trades      = sum(p.oos_result.total_trades  for p in periods)

        combined_oos   = float(np.mean(oos_returns)) if oos_returns else 0.0
        combined_is    = float(np.mean(is_returns))  if is_returns  else 0.0
        efficiency     = combined_oos / combined_is if combined_is != 0 else 0.0

        return WalkForwardSummary(
            periods               = periods,
            combined_oos_return   = round(combined_oos, 3),
            combined_oos_trades   = oos_trades,
            avg_oos_win_rate      = round(float(np.mean(oos_win_rates)), 2) if oos_win_rates else 0.0,
            avg_oos_profit_factor = round(float(np.mean(oos_pf)), 3) if oos_pf else 0.0,
            efficiency_ratio      = round(efficiency, 3),
        )

    @staticmethod
    def _print_wf_summary(s: WalkForwardSummary):
        print(f"\n{'='*60}")
        print(f"  WALK-FORWARD SUMMARY  ({len(s.periods)} periods)")
        print(f"{'─'*60}")
        print(f"  Combined OOS Return:   {s.combined_oos_return:+.2f}%")
        print(f"  OOS Total Trades:      {s.combined_oos_trades}")
        print(f"  Avg OOS Win Rate:      {s.avg_oos_win_rate:.1f}%")
        print(f"  Avg OOS Profit Factor: {s.avg_oos_profit_factor:.3f}")
        print(f"  Efficiency Ratio:      {s.efficiency_ratio:.3f}")
        print(f"    (>0.5 = robust; <0.3 = likely overfit)")
        print(f"{'─'*60}")
        for p in s.periods:
            print(f"  P{p.period_id}: IS={p.is_result.total_return_pct:+.1f}%  "
                  f"OOS={p.oos_result.total_return_pct:+.1f}%  "
                  f"Params={p.best_params}")
        print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# STANDALONE TEST
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.WARNING)

    from data.market_data import MarketDataProvider, DataSource, Timeframe
    from strategies.technical_analysis import ohlcv_to_dataframe

    print("Loading mock data...")
    provider = MarketDataProvider(primary_source=DataSource.MOCK)
    ohlcv    = provider.get_ohlcv('EURUSD', Timeframe.H1, bars=2000)

    if not ohlcv or len(ohlcv) < 200:
        print("ERROR: insufficient mock data")
        sys.exit(1)

    df = ohlcv_to_dataframe(ohlcv)
    print(f"Loaded {len(df)} bars")

    base_config = BacktestConfig(
        symbol               = 'EURUSD',
        initial_balance      = 10_000.0,
        risk_per_trade_pct   = 0.01,
        min_rr_ratio         = 1.5,
        spread_pips          = 1.0,
        commission_per_lot   = 7.0,
        min_signal_confidence= 0.55,
    )

    param_grid = {
        'risk_per_trade_pct':   [0.005, 0.01, 0.02],
        'atr_sl_multiplier':    [1.5, 2.0, 2.5],
        'min_rr_ratio':         [1.5, 2.0],
        'min_signal_confidence':[0.50, 0.60],
    }

    # 1. Grid Search
    print("\n--- GRID SEARCH ---")
    gs      = GridSearch(base_config, df, verbose=True)
    gs_summ = gs.run(param_grid)

    # 2. Monte Carlo on best config
    if gs_summ.best:
        print("\n--- MONTE CARLO ---")
        best_config = copy.copy(base_config)
        for k, v in gs_summ.best.params.items():
            setattr(best_config, k, v)
        best_bt = BacktestEngine(best_config).run(df, verbose=False)
        mc = MonteCarloSimulator(initial_balance=10_000.0, n_simulations=500)
        mc.run(best_bt, verbose=True)

    # 3. Walk-Forward
    print("\n--- WALK-FORWARD ---")
    wf = WalkForwardTester(
        base_config = base_config,
        param_grid  = {
            'atr_sl_multiplier':  [1.5, 2.0],
            'min_rr_ratio':       [1.5, 2.0],
        },
        n_periods   = 3,
        verbose     = True,
    )
    wf.run(df)
