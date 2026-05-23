# CLAUDE.md

## Project Mission

Build a safe, paper-first algorithmic trading system using TradingView, FastAPI, Alpaca Paper Trading, and OpenSPDD.

The system receives TradingView signals via webhook, validates them, applies strict risk controls, stores all decisions, and only then may execute orders in Alpaca Paper Trading.

This system does not promise guaranteed returns. The target of 0.3% daily return is an experimental benchmark, not a guarantee.

## Development Method

This project uses OpenSPDD.

Every meaningful feature must follow this flow:

1. Requirement
2. `/spdd-analysis`
3. `/spdd-reasons-canvas`
4. Human review
5. `/spdd-generate`
6. Tests
7. `/spdd-code-review`
8. `/spdd-sync`
9. Commit

Do not write production code before the requirement, analysis, and REASONS Canvas are aligned.

## Absolute Rules

- Paper trading is the default.
- Live trading is forbidden in V0 and V1.
- No order can be executed directly from a webhook.
- Every signal must pass validation.
- Every signal must pass idempotency checks.
- Every future order must pass the Risk Engine.
- Every order must have a `client_order_id`.
- Every signal must have a `client_signal_id`.
- Every rejected signal must store a rejection reason.
- Every execution decision must be logged.
- No secrets can be committed.
- No API keys can appear in logs.
- No trading strategy can claim guaranteed returns.

## Risk Rules

Default risk limits:

- Max risk per trade: 0.35% of equity.
- Max daily loss: 0.75% of equity.
- Max weekly loss: 2.5% of equity.
- Max trades per day: 3.
- Stop trading after 2 consecutive losing trades.
- Stop trading after reaching daily target.
- No order without stop loss.
- No order without take profit.
- Manual kill switch must override all execution.

## Architecture Boundary

The intended flow is:

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

The webhook layer must never execute orders directly.

## V0 Scope

V0 includes:

- FastAPI project structure.
- TradingView webhook endpoint.
- Webhook secret validation.
- Signal schema validation.
- Idempotency.
- Signal storage.
- Rejection logging.
- Basic risk-decision simulation.

V0 excludes:

- Live trading.
- Real money orders.
- Alpaca live execution.
- Crypto trading.
- Options trading.
- Full dashboard.
- Strategy optimization.

## Technology Choices

Preferred stack:

- Python
- FastAPI
- Pydantic
- SQLAlchemy or SQLModel
- SQLite for local development
- Postgres/Supabase for production
- Pytest
- Alpaca API for paper execution in later versions
- TradingView webhooks
- OpenSPDD inside Claude Code

## Coding Standards

- Use clear module boundaries.
- Use typed Python.
- Prefer small functions.
- Add tests for every risk rule.
- Add tests for every rejection path.
- Keep business rules out of route handlers.
- Keep webhook handlers thin.
- Store raw payloads for traceability.
- Use structured logging.
- Never log secrets.

## Testing Requirements

Every feature must include tests for:

- happy path
- invalid input
- security rejection
- duplicate handling
- risk rejection, when applicable
- persistence behavior
- edge cases

Critical trading logic requires unit tests before live or paper execution.

## OpenSPDD Usage

For every new feature:

1. Create or update a requirement file inside `/requirements`.
2. Run `/spdd-analysis`.
3. Run `/spdd-reasons-canvas`.
4. Review the canvas manually.
5. Only then run `/spdd-generate`.
6. Run tests.
7. Run `/spdd-code-review`.
8. Run `/spdd-sync`.

If code and design diverge, update the requirement or run sync before continuing.

## Claude Code Behavior

Act as a senior software engineer and product-minded trading system architect.

Before implementing:

1. Read this `CLAUDE.md`.
2. Read relevant files in `/memory`.
3. Read the related requirement.
4. Read the OpenSPDD analysis.
5. Read the REASONS Canvas.
6. Confirm the implementation boundary.
7. Implement only the approved scope.

Do not invent trading rules outside the risk policy.

Do not optimize for profit before optimizing for safety, observability, and reproducibility.

## Forbidden Actions

Never:

- Enable live trading by default.
- Place orders from the webhook handler.
- Skip the Risk Engine.
- Hardcode API keys.
- Commit secrets.
- Remove risk limits without updating `/memory/risk-policy.md`.
- Add Alpaca execution to V0.
- Change trading behavior without updating the requirement and OpenSPDD artifacts.

## Commit Discipline

Every meaningful commit should ideally include:

- requirement update, if needed
- OpenSPDD analysis
- REASONS Canvas
- implementation
- tests
- verification or sync notes

Commit messages should be explicit.

Example:

`feat: add TradingView webhook signal intake with idempotency`