# Trading SPDD System

Paper-first algorithmic trading system built with TradingView, FastAPI, Alpaca Paper Trading, Claude Code, and OpenSPDD.

## Objective

The goal of this project is to build a safe and observable trading system that can receive trading signals, validate them, apply risk controls, and execute orders in paper trading before any live trading is considered.

The system may target an average daily return benchmark of 0.3%, but this is not a guarantee. The primary objective is controlled execution, learning, and risk management.

## Core Architecture

```text
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