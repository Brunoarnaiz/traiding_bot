# MT5 Bridge Design (Linux-first)

Goal: keep Nix/OpenClaw and bot logic on Linux while using the already-open MT5 terminal under Wine as the execution endpoint.

## Constraints discovered
- Native MetaTrader5 Python package is not installable in this Linux environment.
- MT5 terminal is running under Wine.
- User wants Linux-first operation and minimum future interference.

## Practical approach
1. Keep strategy/risk/backtesting in Python on Linux.
2. Use a lightweight bridge for signal generation first.
3. For immediate demonstrable functionality, run the bot in simulation mode using the same risk/config pipeline.
4. Prepare next-step integration for MT5 via one of:
   - HTTP/file bridge to MT5 EA
   - Windows-native runner later if needed

## Deliverable tonight
- Functional paper/sim bot runner
- Configured around the Vantage demo account context
- Risk rules and logs working
- Ready to evolve into MT5 execution bridge without redoing project structure
