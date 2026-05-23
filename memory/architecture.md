# System Architecture

## Tech Stack
- **Language**: Python 3.x
- **Framework**: FastAPI
- **Database**: SQLite (V0) → PostgreSQL (production)
- **Testing**: pytest
- **Logging**: Structured logging
- **Secrets**: Environment variables

## Core Flow (V0)
```
TradingView Alert
  ↓
FastAPI Webhook Endpoint
  ↓
Secret Validation (Bearer token)
  ↓
Signal Schema Validation (Pydantic)
  ↓
Idempotency Check (deduplication)
  ↓
Signal Storage (DB)
  ↓
Risk Engine Simulation
  ↓
Decision Logging (approved/rejected + reason)
  ↓
Response to TradingView (202 Accepted or error)
```

## Components

### Webhook Receiver
- POST endpoint validates incoming TradingView alerts
- Validates shared secret
- Parses and validates signal schema
- Returns synchronous response (no async processing in V0)

### Signal Processor
- Checks idempotency (duplicate detection)
- Stores signal with received timestamp
- Persists state changes

### Risk Engine
- Pure function that evaluates signal against risk limits
- Takes signal + daily stats as input
- Returns decision (approved/rejected) + reason
- Testable, deterministic

### Database
- Stores signals (full history)
- Stores daily stats (for limit calculations)
- Supports idempotency checks (signal_id lookup)
- Supports decision audit trail

### Logging
- Every signal logged (received, validated, decision)
- Structured format for observability
- Reason logged for rejections

## Data Model (conceptual, not schema)
- **Signal**: id, timestamp, ticker, action (buy/sell), quantity, schema_version
- **DailyStats**: date, trade_count, pnl, consecutive_losses, target_reached
- **Decision**: signal_id, approved, reason, timestamp
