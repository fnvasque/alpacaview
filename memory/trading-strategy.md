# Trading Strategy Memory

## Strategy Concept

The initial strategy is a momentum pullback system.

It uses trend confirmation, pullback entry, stop loss, take profit, and strict risk sizing.

## Target

The strategy may target 0.3% average daily return, but this is only a benchmark.

## Initial Assets

Preferred initial assets:

- SPY
- QQQ
- AAPL
- MSFT
- NVDA
- BTC/USD
- ETH/USD

Final asset availability depends on broker permissions and account configuration.

## Signal Logic

Initial concept:

- Price above EMA 200
- EMA 20 above EMA 50
- Pullback toward EMA 20, EMA 50 or VWAP
- Bullish confirmation candle
- Volume confirmation
- Entry after break of confirmation candle

## Exit Logic

- Stop loss below pullback low or based on ATR
- Take profit at 1R, 1.5R or 2R
- Move stop to break-even after partial profit
- Do not overtrade after reaching daily target

## Important Rule

The strategy is secondary.

Risk management is primary.