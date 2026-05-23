# Trading System V0

## Objective

Build a paper-first algorithmic trading system using TradingView, FastAPI, Alpaca Paper Trading and Claude Code.

The system receives trading signals from TradingView via webhook, validates them, stores them, applies a Risk Engine, and only then executes orders in Alpaca Paper Trading.

## Important clarification

The system targets an average daily return of 0.3%, but it must never promise or assume guaranteed daily returns.

The main objective is risk-controlled execution, observability and learning.

## Architecture

TradingView Alert
→ FastAPI Webhook
→ Signal Validation
→ Idempotency Check
→ Risk Engine
→ Order Builder
→ Alpaca Paper Trading
→ Order State Sync
→ Database
→ Dashboard / Notifications

## Non-negotiable rules

- Paper trading by default.
- Live trading forbidden in V0 and V1.
- No order can be executed directly from the webhook.
- Every signal must pass through the Risk Engine.
- Every signal must have an idempotency key.
- Every order must have a client_order_id.
- Every rejected signal must store a rejection reason.
- Every execution must be logged.
- No strategy can promise guaranteed returns.
- Secrets must never be committed.
- Tests are mandatory for risk rules.

## Risk limits

- Max risk per trade: 0.35% of equity.
- Max daily loss: 0.75% of equity.
- Max weekly loss: 2.5% of equity.
- Max trades per day: 3.
- Stop after 2 consecutive losing trades.
- Stop after reaching daily target.
- No order without stop loss.
- No order without take profit.
- Kill switch must override all execution.

## V0 scope

Included:

- Project structure.
- FastAPI app.
- TradingView webhook endpoint.
- Signal schema validation.
- Secret validation.
- Idempotency.
- Signal storage.
- Risk Engine decision simulation.
- No Alpaca execution yet.

Excluded:

- Live trading.
- Real money orders.
- Full dashboard.
- Strategy optimization.
- Crypto trading.
- Options trading.