# SPDD Analysis: Trading System V0 — Webhook Reception & Risk Engine Simulation

## Original Business Requirement

> Source: `requirements/trading-system-v0.md`

```
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
→ Every signal must have an idempotency key.
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
```

> Additional context incorporated from `memory/trading-strategy.md`:

```
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
```

---

## Domain Concept Identification

### Existing Concepts (from codebase)

This is a **fully greenfield project**. No application code, database schemas, or domain models exist yet. The project has only:
- `requirements/` — specification documents (stubs + `trading-system-v0.md` + `trading-strategy.md`)
- `memory/` — reference knowledge files
- `CLAUDE.md` — engineering norms and development methodology
- `.claude/commands/` — SPDD workflow commands

No concepts exist in code yet — all are new.

### New Concepts Required

- **Signal**: The core business entity. A trading intent received from TradingView, carrying ticker, direction (buy/sell), stop loss, take profit, and an idempotency key. Governs the entire ingestion pipeline. Lifecycle: received → validated → deduplicated → risk-evaluated → persisted.

- **IdempotencyRecord**: A deduplication mechanism that tracks which signal keys have already been processed. Prevents double-execution when TradingView retries a webhook. Owned by Signal; checked before any processing begins.

- **WebhookSecret**: The shared credential that authenticates TradingView as the sender. A configuration concept — not persisted as a domain entity, but validated on every incoming request. Fails fast before any processing if invalid.

- **RiskEngine**: The rule-evaluation component. A pure, stateless evaluator that receives a Signal and the current TradingContext, applies all risk limits, and returns an approved or rejected decision. Has no side effects; its output is the RiskDecision.

- **RiskDecision**: The output of the Risk Engine. Records whether a Signal was approved or rejected and the specific reason. Always persisted alongside the Signal for audit purposes.

- **TradingContext**: The accumulated state the Risk Engine needs to evaluate limits — today's trade count, today's realized PnL, this week's PnL, consecutive loss count, daily target status, and kill switch state. Computed from Signal and Decision history at evaluation time.

- **DailyStats**: A derived view of TradingContext scoped to a calendar day. Tracks trade count, cumulative loss, consecutive losing trades, and whether the daily target has been reached. Resets at the start of each trading day.

- **WeeklyStats**: A derived view scoped to the trading week. Tracks cumulative weekly PnL for the weekly loss limit check. Resets at the start of each trading week (Monday open).

- **KillSwitch**: A global trading halt flag. When active, the Risk Engine rejects all incoming Signals regardless of other limits. Must be checkable before any execution. Mechanism for toggling (env var, DB flag, or API endpoint) is a design decision.

- **RejectionReason**: A structured enumeration of all reasons a Signal can be rejected. Not a standalone entity — a field on RiskDecision. Ensures rejection causes are machine-readable and testable, not free-form strings.

### Key Business Rules

- **No direct execution**: A Signal received at the webhook cannot trigger an order without passing through the Risk Engine. Enforced architecturally — the webhook layer has no access to order execution.

- **Idempotency is mandatory**: No Signal may be processed twice. Checked by idempotency key before Risk Engine evaluation. Duplicate → reject immediately with reason "duplicate signal".

- **Rejection must be persisted**: Every Signal that is rejected (schema invalid, idempotency duplicate, risk limit exceeded, kill switch) must store its RejectionReason. No silent drops.

- **Risk limits are cumulative**: Daily loss, weekly loss, and trade count are evaluated against the running total of all approved signals for that day/week — not per-signal in isolation.

- **Kill switch is absolute**: When the kill switch is active, no other rule is evaluated. It overrides all limits and approvals.

- **Stop loss and take profit are mandatory per order**: In V0 this is enforced at Signal validation — a signal without stop_loss and take_profit values is schema-invalid and rejected before reaching the Risk Engine. (Note: "order" constraints apply in V1 execution; in V0 they manifest as signal validation requirements.)

- **No guaranteed returns**: The system must never expose or log language that implies guaranteed profitability. A compliance constraint — not a code rule, but a documentation and response-message standard.

- **Secrets never committed**: All credentials (webhook secret, future Alpaca API keys) must be loaded from environment variables. Enforced by `.gitignore` and engineering norm — not code.

- **Tests are mandatory for every risk rule**: Each limit (daily loss, weekly loss, max trades, consecutive losses, daily target, kill switch) must have a corresponding pytest test. Non-negotiable.

---

## Strategic Approach

### Solution Direction

- Build a single-responsibility FastAPI application where the webhook endpoint is the only external surface in V0.
- The processing pipeline is **synchronous and linear** within a single request: receive → validate secret → validate schema → check idempotency → evaluate risk → persist decision → respond.
- The Risk Engine is implemented as a **pure function** (no I/O, no side effects) that receives Signal + TradingContext and returns a RiskDecision. This makes it trivially testable in isolation.
- TradingContext is assembled from the database immediately before Risk Engine evaluation — computed on-the-fly from signal history, not cached. Simple and correct for V0 trade volumes.
- All Signal and RiskDecision records are persisted to a local SQLite database via SQLAlchemy ORM. No migrations framework needed in V0 (schema created on startup).
- Structured logging wraps every stage of the pipeline so the audit trail is available from logs even without a dashboard.

### Key Design Decisions

- **Database for V0 — SQLite vs. PostgreSQL**: SQLite requires zero infrastructure, is included in Python's standard library, and is sufficient for the low throughput of V0 (max 3 signals/day). PostgreSQL would add operational overhead with no benefit at this stage. → **Recommend SQLite with SQLAlchemy** for V0; migration path to PostgreSQL is straightforward via `DATABASE_URL` environment variable.

- **Risk Engine as pure function vs. stateful service**: A stateful service would require careful lifecycle management and is harder to test. A pure function that receives all inputs explicitly (Signal, TradingContext) produces deterministic output with no hidden dependencies. → **Recommend pure function** with TradingContext assembled by a thin service layer before calling the engine.

- **Secret validation mechanism — bearer token vs. HMAC signature**: TradingView does not natively sign webhook payloads with HMAC; it includes a user-defined secret in the payload body. Simple bearer token comparison (constant-time equality check) is appropriate for V0 and matches TradingView's actual capability. → **Recommend bearer token** (constant-time comparison) for V0. HMAC is a future hardening option.

- **Synchronous vs. async processing**: Async processing (background tasks, queues) would add complexity without benefit in V0 — there is no execution to defer and trade volume is negligible. The webhook must respond quickly to TradingView (avoid timeout), which synchronous linear processing handles cleanly. → **Recommend synchronous processing** for V0.

- **Kill switch mechanism — env var vs. DB flag**: An env var requires a service restart to change. A DB flag can be toggled at runtime via a future API endpoint. For V0, an env var is simpler and there is no dashboard or admin surface yet. → **Recommend DB flag** with env var fallback; this allows runtime toggling via direct DB access in V0 and API endpoint in V1.

- **TradingContext computation — on-the-fly vs. cached**: Caching (e.g., Redis) would add infrastructure complexity. On-the-fly computation from signal history is correct and performant at V0 volumes (≤3 signals/day). → **Recommend on-the-fly computation** from persisted Signal and RiskDecision records.

### Alternatives Considered

- **Async task queue (Celery/RQ) for signal processing**: Rejected — adds broker infrastructure (Redis/RabbitMQ), complicates error handling, and provides no benefit when execution is simulated and not time-critical in V0.

- **Separate microservices for Validator, Risk Engine, and Storage**: Rejected — premature decomposition. A single FastAPI application with well-separated internal modules achieves the same separation of concerns without network overhead or deployment complexity.

- **No database in V0 (in-memory only)**: Rejected — idempotency checks require persistence across requests, and the requirement explicitly mandates signal storage and rejection reason persistence.

---

## Risk & Gap Analysis

### Requirement Ambiguities

All 7 ambiguities identified in the initial analysis have been resolved by the product owner. See **Resolved Design Decisions** section below for full details. No open ambiguities remain for REASONS Canvas generation.

### Edge Cases

- **TradingView webhook retries on non-2xx responses**: If the system returns a 5xx error (e.g., DB unavailable), TradingView will retry. A signal that was partially processed (stored but not risk-evaluated) on first attempt could produce inconsistent state on retry. → Idempotency check must be atomic with signal storage (within a single DB transaction).

- **Simultaneous webhook calls with the same idempotency key**: A race condition where two requests arrive with the same key before either is stored. At V0 volumes this is unlikely but the idempotency check must use a DB-level unique constraint, not application-level logic, to be safe.

- **Kill switch toggled mid-request**: If the kill switch is checked at the start of Risk Engine evaluation but toggled to active during processing, the signal might be approved incorrectly. → Kill switch check must happen at the Risk Engine entry point with the final DB read before decision.

- **Week boundary crossing**: A weekly loss limit that started accumulating on Thursday will reset on Monday. A signal arriving late Sunday vs. early Monday must be correctly attributed to the current vs. new week. → Week boundary definition (trading week start, timezone) must be explicit.

- **Timezone handling**: TradingView alerts fire on market time (US Eastern). Signal timestamps must be stored and compared in a consistent timezone to correctly evaluate daily and weekly limits. → Must define: UTC storage with US/Eastern business-day logic, or US/Eastern throughout?

- **Non-market-hours signals**: TradingView may fire alerts outside US market hours (pre-market, after-hours, weekends). The Risk Engine has no explicit rule for this. → Should the system reject signals outside market hours, or pass them to the Risk Engine for limit evaluation?

- **Signal with stop_loss > entry price on a buy**: A logically invalid signal (stop loss above entry for a long position). Schema validation catches format errors but not business-logic errors like this. → Should the validator include basic price sanity checks?

### Technical Risks

- **No formal AC definitions in the requirement**: The V0 scope is expressed as a bullet list of included/excluded features, not as testable acceptance criteria. This makes it ambiguous when V0 is "done." → ACs must be derived and agreed upon before REASONS Canvas (see table below).

- **SQLite concurrency under load**: SQLite uses file-level write locking. Under concurrent requests (multiple TradingView alerts arriving simultaneously), writes will serialize. At V0 volumes (max 3/day) this is not a practical risk, but it must not be assumed safe for V1.

- **Secret in request body (not header)**: TradingView sends the user-defined secret in the JSON body, not in a standard Authorization header. This means the secret is logged by default in most middleware. → Request logging must mask or exclude the secret field.

- **No authentication beyond shared secret**: The webhook is publicly accessible by URL. Anyone who discovers the URL but not the secret can attempt brute-force or replay attacks. → Secret comparison must use `hmac.compare_digest` (constant-time) to prevent timing attacks.

- **Testing PnL-based risk rules without execution**: Unit tests for daily/weekly loss limits require the ability to inject a TradingContext with arbitrary PnL values. The Risk Engine pure function design makes this straightforward, but test fixtures must simulate realistic PnL scenarios.

- **CLAUDE.md prescribes SPDD workflow**: Per `CLAUDE.md`, no production code may be generated before Story, Analysis, and REASONS Canvas are aligned. This analysis fulfills the Analysis phase; the REASONS Canvas is the mandatory next step before any code generation.

---

## Resolved Design Decisions

Resolved by product owner on 2026-05-18. All ambiguities are closed. No open questions remain.

### 1. Signal Payload Schema

Custom TradingView JSON alert with the following structure:

**Required fields** (reject 422 if any missing):
- `secret` — shared webhook authentication token
- `strategy` — strategy name/identifier
- `version` — strategy version string
- `ticker` — asset symbol (e.g., SPY, AAPL)
- `side` — trade direction (`buy` or `sell`)
- `price` — signal price at alert time
- `timeframe` — chart timeframe (e.g., `5`, `15`, `60`)
- `bar_time` — ISO timestamp of the triggering bar
- `event_time` — ISO timestamp when the alert fired
- `client_signal_id` — idempotency key (user-defined, mandatory)

**Optional fields** (present if configured in TradingView alert):
- `exchange` — exchange identifier
- `order_id` — external reference ID
- `stop_loss` — stop loss price
- `take_profit` — take profit price
- `risk_hint` — suggested risk size hint from strategy
- `position_size` — suggested position size from strategy

### 2. Idempotency Key (`client_signal_id`)

- **Source**: Mandatory user-defined field in the TradingView alert message body
- **Format convention**: `strategy:version:ticker:timeframe:bar_time:side`
- **Behavior**: If missing or empty → reject with 422 (schema validation failure, not idempotency failure)
- **Behavior**: If duplicate (already seen) → reject with 409, reason `DUPLICATE_SIGNAL`
- **Constraint**: DB-level `UNIQUE` constraint on `client_signal_id` — not application-level check
- **V0 principle**: No backend hash as primary mechanism; hash-based fallback deferred to V1 if needed

### 3. Equity Source in V0

- **Mechanism**: Environment variable `INITIAL_EQUITY`, default `10000` (USD)
- **Usage**: All risk limit calculations (0.35%/trade, 0.75%/day, 2.5%/week) use this value in V0
- **V1 migration**: When Alpaca Paper is integrated, equity is fetched from Alpaca account state at request time; `INITIAL_EQUITY` becomes the fallback

### 4. Daily Target

- **Default value**: 0.30% of starting daily equity
- **Configuration**: `DAILY_TARGET_PCT=0.003` (float), `STOP_AFTER_DAILY_TARGET=true` (bool)
- **V0 behavior**: Target tracking is simulated and logged; does not lock execution in V0 (no fills to track against)
- **V1 behavior**: When fills exist, reaching target locks further signal approval for the calendar day

### 5. PnL-Based Risk Limits in V0

- **Decision**: Real enforcement deferred to V1/V2 when simulated or Alpaca Paper fills exist
- **V0 behavior**: Risk Engine defines the full RiskState model (daily PnL, weekly PnL, consecutive losses) and logs would-be decisions, but does **not enforce** limits that require realized PnL
- **Exception**: Test fixtures may inject explicit TradingContext state to verify enforcement logic is correct even in V0 tests
- **Affects**: AC8 (daily loss), AC9 (weekly loss), AC10 (consecutive losses) — all logged-only in V0
- **Enforced in V0**: max daily trades (AC7), daily target hard-stop (AC11, when `STOP_AFTER_DAILY_TARGET=true`), kill switch (AC12)

### 6. Crypto Ticker Handling

- **Decision**: Crypto tickers actively rejected in V0
- **Mechanism**: Configurable allowlist of supported asset symbols/classes (US equities and ETFs only)
- **Rejection reason**: `UNSUPPORTED_ASSET_CLASS`
- **Future path**: BTC/USD, ETH/USD added through a separate V1+ requirement; not silently ignored
- **Allowlist approach**: Validated against a list of configured tickers or a pattern-based asset class check (e.g., no `/` in ticker, no `USDT` suffix)

### 7. Timezone

- **Storage**: All timestamps stored in UTC
- **Risk resets**: Daily and weekly limit windows computed using `America/New_York` timezone
  - Day boundary: 00:00 America/New_York (midnight ET)
  - Week boundary: Monday 00:00 America/New_York
- **Rationale**: First supported universe is US equities/ETFs; NYSE/NASDAQ market hours align with US/Eastern
- **Chile time**: Not used for any trading risk windows

### Acceptance Criteria Coverage

The V0 requirement does not define formal Acceptance Criteria. The following ACs are **derived** from the scope bullets and non-negotiable rules, and must be confirmed before REASONS Canvas generation:

| AC# | Description | Addressable? | Gaps/Notes |
|-----|-------------|--------------|------------|
| 1 | `POST /webhook/signal` receives a TradingView alert and returns 202 if valid | Yes | Endpoint path decided: `/webhook/signal` |
| 2 | Requests with invalid or missing `secret` field are rejected with 401, reason stored | Yes | Secret field name: `secret` in JSON body |
| 3 | Signals missing any required field (`secret`, `strategy`, `version`, `ticker`, `side`, `price`, `timeframe`, `bar_time`, `event_time`, `client_signal_id`) are rejected with 422, reason stored | Yes | Schema fully defined — see Resolved Decisions |
| 4 | Duplicate `client_signal_id` values are rejected with 409 and reason `DUPLICATE_SIGNAL` stored | Yes | Format: `strategy:version:ticker:timeframe:bar_time:side` |
| 5 | Every signal (valid or not) is persisted with status and UTC timestamp | Yes | |
| 6 | Risk Engine model and all limit checks are implemented and individually tested | Yes | PnL-based limits defined and logged (not enforced) in V0 |
| 7 | Risk Engine rejects signal if daily approved trade count ≥ 3 | Yes | |
| 8 | Risk Engine logs would-be rejection if daily loss would exceed 0.75% of `INITIAL_EQUITY`; enforcement deferred to V1 | Yes | Equity: env var `INITIAL_EQUITY`, default 10000 |
| 9 | Risk Engine logs would-be rejection if weekly loss would exceed 2.5% of `INITIAL_EQUITY`; enforcement deferred to V1 | Yes | Week boundary: Monday 00:00 America/New_York |
| 10 | Risk Engine logs would-be rejection for 2+ consecutive losing trades; enforcement deferred to V1 | Yes | No PnL without fills — logged only in V0 |
| 11 | Risk Engine rejects signal if daily target (0.3% equity, configurable via `DAILY_TARGET_PCT`) has been reached, when `STOP_AFTER_DAILY_TARGET=true` | Yes | Logged in V0; locks execution in V1 |
| 12 | Kill switch active → all signals rejected with reason `KILL_SWITCH_ACTIVE`, regardless of other rules | Yes | DB flag mechanism; env var fallback |
| 13 | Every RiskDecision (approved or rejected) is persisted with structured reason code | Yes | |
| 14 | Every risk rule has at least one pytest test covering the rejection path | Yes | Pure function design enables isolated unit tests |
| 15 | Ticker with unsupported asset class (crypto: BTC, ETH, etc.) is rejected with `UNSUPPORTED_ASSET_CLASS` | Yes | Actively rejected; configurable allowlist of US equities/ETFs |
| 16 | No Alpaca API calls are made anywhere in V0 | Yes | Verified by absence of alpaca-py import in codebase |
| 17 | No secrets appear in committed files; secret field masked in request logs | Yes | `.gitignore` + structured logging field exclusion |
