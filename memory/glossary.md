# Glossary & Domain Terms

## Core Concepts

**Signal** - A trading intent received from TradingView via webhook. Contains ticker, action, and optional quantity. Core entity of the system.

**Idempotency Key** - Unique identifier attached to each signal to prevent duplicate processing. Enables safe webhook retries.

**Risk Engine** - Decision-making component that evaluates signals against all risk limits before approval. In V0, this simulates decisions without execution.

**Risk Decision** - Outcome of Risk Engine evaluation: approved or rejected with a specific reason.

**Rejection Reason** - Structured record explaining why a signal was rejected (e.g., "daily loss limit exceeded", "duplicate idempotency key").

**Kill Switch** - Global override that halts all trading execution, regardless of signal or risk state. Can override normal flow.

**DailyStats** - Accumulated trading state for a calendar day: trade count, PnL totals, consecutive losing trades, daily target status.

**Order** - Execution intent sent to Alpaca (buy/sell with quantity and price). In V0, not created yet.

**Client Order ID** - Unique identifier for each order at Alpaca level. Enables deduplication and audit trail.

**Paper Trading** - Simulated trading using Alpaca's paper trading account (virtual money, no real execution).

**Live Trading** - Real money trading (forbidden in V0 and V1).

**Equity** - Account balance (starting capital) used to calculate position sizes and risk percentages.

**Position Size** - Number of shares to buy/sell, calculated as: risk_limit / (entry - stop_loss).

**Stop Loss (SL)** - Exit price below entry where trade is automatically closed to limit losses. Mandatory for all orders.

**Take Profit (TP)** - Exit price above entry where trade is automatically closed to lock in gains. Mandatory for all orders.

**PnL** - Profit and Loss. In V0, simulated or estimated, not realized.

**Webhook** - HTTP POST endpoint that receives real-time alerts from TradingView.

**Secret Validation** - Verification that incoming webhooks are from TradingView using a shared bearer token.

**Schema Validation** - Verification that incoming signal data matches expected structure (via Pydantic).

## Abbreviations
- **V0** - Version 0 (current phase, no execution)
- **V1** - Version 1 (execution on paper, no live)
- **SL** - Stop Loss
- **TP** - Take Profit
- **PnL** - Profit and Loss
- **SPDD** - Structured-Prompt-Driven Development
