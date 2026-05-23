# Product Definition

## Vision
Build a safe, paper-first algorithmic trading system using TradingView webhooks, FastAPI, and Alpaca Paper Trading with strict risk controls.

## Objective
Paper-first system that receives trading signals from TradingView, validates them through a Risk Engine, and executes orders in Alpaca Paper Trading with focus on **risk-controlled execution, observability and learning**.

Target: Average daily return of 0.3% (aspirational, not guaranteed).

## V0 Scope

### Included
- Project structure (Python + FastAPI)
- TradingView webhook endpoint
- Signal schema validation
- Secret validation
- Idempotency (duplicate prevention)
- Signal storage and history
- Risk Engine decision simulation
- Logging and observability

### Excluded
- Alpaca order execution (V1+)
- Real money trading (V0/V1 forever)
- Dashboard (post-V0)
- Strategy optimization (V2+)
- Crypto or options trading

## Core Concepts
- **Signal**: Trading intent from TradingView (buy/sell)
- **Risk Engine**: Evaluates signals against risk limits
- **Order**: Execution intent (not sent in V0)
- **Idempotency**: Prevents duplicate signal processing
- **Kill Switch**: Global trading halt override

## Non-Negotiable Rules
1. Paper trading only (V0/V1 forever)
2. No order execution directly from webhook
3. Every signal passes through Risk Engine
4. Every signal has idempotency key
5. Every rejected signal stores reason
6. Every execution is logged
7. No guaranteed returns promised
8. Secrets never committed
9. Tests mandatory for risk rules
