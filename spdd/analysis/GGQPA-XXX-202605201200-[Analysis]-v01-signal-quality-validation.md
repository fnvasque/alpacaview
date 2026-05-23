# SPDD Analysis: V0.1 — Signal Quality Validation

## Original Business Requirement

Vamos a construir V0.1 del sistema alpacaview.

Contexto:
V0 ya está terminado. El sistema recibe señales por /webhook/signal y por /integrations/resend/inbound. Valida secret, schema, ticker, side, asset class, duplicate_signal, kill switch y max daily trades. Persiste signals, risk_decisions y webhook_events. No hay Alpaca ni órdenes.

Objetivo V0.1:
Agregar validaciones de calidad de señal antes de aprobar una señal BUY.

Reglas nuevas:
1. price debe ser > 0.
2. stop_loss debe ser > 0.
3. take_profit debe ser > 0.
4. Para side=buy, stop_loss debe ser menor que price.
5. Para side=buy, take_profit debe ser mayor que price.
6. Calcular risk_reward:
   risk = price - stop_loss
   reward = take_profit - price
   risk_reward = reward / risk
7. Rechazar si risk_reward < MIN_RISK_REWARD.
8. Agregar setting MIN_RISK_REWARD con default 1.5.
9. Agregar setting ALLOWED_TIMEFRAMES con default ["5m", "15m", "1h"].
10. Rechazar timeframe no permitido.
11. Agregar setting MAX_SIGNAL_AGE_SECONDS con default 900.
12. Rechazar señales stale si event_time es demasiado antiguo.
13. Mantener el comportamiento actual de V0.
14. No agregar Alpaca.
15. No crear órdenes.
16. No cambiar Resend adapter salvo que sea necesario para tests.
17. Agregar tests unitarios e integración.

Reason codes esperados:
- invalid_price
- invalid_stop_loss
- invalid_take_profit
- stop_loss_above_entry
- take_profit_below_entry
- risk_reward_too_low
- unsupported_timeframe
- stale_signal

Deliverables:
- Código actualizado.
- Tests nuevos.
- Documentación en docs/validation/v0.1-validation.md.

---

## Domain Concept Identification

### Existing Concepts (from codebase)

- **Signal**: core entity persisted in `signals` table. Already carries `price` (required, `Decimal`), `stop_loss` (optional, `Decimal`), `take_profit` (optional, `Decimal`), `timeframe` (str), `event_time_utc` (datetime). All fields needed for V0.1 validation are already present in the ORM model and in `WebhookSignalRequest`.
- **WebhookSignalRequest**: Pydantic schema that parses and coerces the inbound payload. Already has `@field_validator("price")` asserting `price > 0`, which overlaps with the new `invalid_price` rule (see Ambiguities). `stop_loss` and `take_profit` are `Optional[Decimal]` with no validators.
- **RejectionReason** (enum): Machine-readable rejection codes stored in `webhook_events` and `risk_decisions`. V0.1 adds 8 new values. The enum docstring explicitly lists V0-enforced vs. deferred reasons — V0.1 values must be marked enforced.
- **WebhookEventType** (enum): Audit event types for pre-engine pipeline rejections. Used by steps 1–5 in `signal_service.process_raw_payload`. V0.1 quality rejections need a new event type (or reuse an existing one — see Decisions).
- **signal_service.process_raw_payload**: 10-step pipeline. Steps 1–5 are pre-persistence guards that produce `WebhookEvent` records but no `Signal`. Steps 6–10 persist the `Signal` and produce a `RiskDecision`. New quality checks must be positioned in this pipeline.
- **Risk Engine (`engine.evaluate`)**: Pure function. Receives `RiskSignalSnapshot`, `TradingContext`, `Settings`. Currently evaluates only TradingContext-based limits (kill switch, daily trade count, PnL, consecutive losses). Declared pure with "no I/O, no side effects" guarantee.
- **RiskSignalSnapshot**: Immutable value object passed to the engine. Contains `price`, `stop_loss`, `take_profit` — but not `timeframe` or `event_time`.
- **Settings**: `pydantic-settings` class backed by `.env`. Already has `ALLOWED_TICKERS` with a `parse_allowed_tickers` validator that handles comma-separated strings. V0.1 adds `MIN_RISK_REWARD`, `ALLOWED_TIMEFRAMES`, and `MAX_SIGNAL_AGE_SECONDS`.
- **TradingContext**: Snapshot of account/market state passed to the engine. V0.1 quality checks do not require TradingContext — they depend only on signal values and settings.

### New Concepts Required

- **Signal Quality Validation**: A new validation stage that evaluates signal-intrinsic properties (price, stop_loss, take_profit, risk_reward ratio, timeframe, staleness) independent of trading context. It is purely functional: inputs are `WebhookSignalRequest` + `Settings`, output is pass or (reason_code, detail).
- **Risk/Reward Ratio**: Derived value calculated as `(take_profit - price) / (price - stop_loss)`. Not currently modeled anywhere. Must guard against division by zero when `stop_loss == price`.
- **Stale Signal**: A signal whose `event_time` is older than `MAX_SIGNAL_AGE_SECONDS` relative to the moment of processing. Not currently modeled. Requires wall-clock comparison in the service layer.

### Key Business Rules

- **stop_loss and take_profit are implicitly required for BUY signals in V0.1**: Rules 2–7 only make sense if both fields are present. If either is `None` for a BUY signal, the quality check cannot complete. The requirement doesn't state what to do when they're absent — this must be resolved (see Ambiguities).
- **Quality checks apply to BUY signals only**: The requirement scopes all new validations to `side=buy`. SELL signals are already rejected in step 3 (UNSUPPORTED_SIDE), so in practice all signals reaching quality checks are BUY — but this ordering must be maintained.
- **Price positivity partially overlaps with the schema validator**: `WebhookSignalRequest.price_must_be_positive` already rejects `price <= 0` with `schema_invalid`. A service-layer `invalid_price` check would be unreachable for price ≤ 0 (schema catches it first). This overlap must be addressed (see Decisions).
- **Risk/reward must satisfy a configurable floor**: `risk_reward >= MIN_RISK_REWARD` (default 1.5). A ratio below this means the potential reward doesn't justify the risk.
- **Timeframe must be in an operator-configured allowlist**: Default `["5m", "15m", "1h"]`. Unlike `ALLOWED_TICKERS`, the default is non-empty and prescriptive.
- **Signals older than `MAX_SIGNAL_AGE_SECONDS` must be rejected**: Default 900 seconds (15 minutes). Prevents the system from acting on delayed/replayed alerts.
- **Quality rejections do not persist a Signal row**: Consistent with how `UNSUPPORTED_SIDE` and `UNSUPPORTED_ASSET_CLASS` work — only a `WebhookEvent` audit record is written.

---

## Strategic Approach

### Solution Direction

Add a new **Signal Quality Validation** step into the `signal_service.process_raw_payload` pipeline between the existing asset class check (step 4) and the idempotency check (step 5). This step:
- Evaluates the parsed signal against quality rules using only `WebhookSignalRequest` fields and `Settings`
- On failure, creates a `WebhookEvent` audit record and returns a rejection response — no `Signal` is persisted
- On pass, the pipeline continues unchanged to idempotency, persistence, and the Risk Engine

The validation logic is extracted to a dedicated module (`app/services/signal_quality.py`) to keep the purity guarantee of `engine.py` intact and prevent `signal_service.py` from accumulating unbounded complexity.

New settings (`MIN_RISK_REWARD`, `ALLOWED_TIMEFRAMES`, `MAX_SIGNAL_AGE_SECONDS`) are added to `Settings` in `app/config.py` following the exact pattern used for `ALLOWED_TICKERS` (including a comma-string validator for `ALLOWED_TIMEFRAMES`).

Eight new `RejectionReason` values and one new `WebhookEventType` value are added to `app/schemas/enums.py`.

### Key Design Decisions

- **Pipeline step vs. Risk Engine**: Quality checks go in the service pipeline (pre-persistence step 4.5), not in the Risk Engine — because the engine is declared pure with no signal-value logic, and because quality-rejected signals should not produce a Signal or RiskDecision row, only a WebhookEvent. Adding them to the engine would require changing `RiskSignalSnapshot` (adding `timeframe`, `event_time`) and would break the engine's TradingContext-only evaluation pattern. → **Service pipeline step wins.**

- **Separate module vs. inline in signal_service**: Extract to `app/services/signal_quality.py`. Keeps `signal_service.py` focused on orchestration, enables isolated unit testing of the quality logic without a DB, and mirrors the existing split between `engine.py` (pure logic) and `signal_service.py` (orchestration). → **Separate module wins.**

- **`invalid_price` overlap with schema validator**: `WebhookSignalRequest` already has `price_must_be_positive` which produces `schema_invalid` before any service-layer check can fire. Two options: (a) remove the schema validator and add `invalid_price` as a service-layer check so it produces the intended reason code; (b) keep the schema validator and accept that `price <= 0` will always yield `schema_invalid`, not `invalid_price`. Option (a) is semantically correct per the requirement — `invalid_price` is a distinct business rule, not a structural schema error. → **Remove schema validator, add service-layer `invalid_price` check.**

- **`stop_loss` and `take_profit` optionality**: Currently `Optional[Decimal]` in the schema. For BUY signals in V0.1, both are required for quality validation. Rather than making them required in the Pydantic schema (which would change the existing API contract), enforce their presence at the quality-validation step with `invalid_stop_loss` / `invalid_take_profit` reason codes when `None`. This preserves schema backward compatibility. → **Remain Optional in schema; required at quality-validation step for BUY.**

- **`WebhookEventType` for quality rejections**: Add a single new value `SIGNAL_QUALITY_REJECTED` to cover all 8 new reason codes rather than 8 new event types. The `reason_code` field on `WebhookEvent` already carries the fine-grained code. This avoids enum explosion. → **Single `SIGNAL_QUALITY_REJECTED` event type.**

- **Validation order within the quality step**: Run checks in dependency order to surface the most fundamental error first: (1) price validity, (2) stop_loss validity, (3) take_profit validity, (4) stop_loss vs. price relationship, (5) take_profit vs. price relationship, (6) risk_reward ratio, (7) timeframe, (8) staleness. First failure returns immediately. → **Fail-fast, single rejection per signal.**

- **`ALLOWED_TIMEFRAMES` with non-empty default**: Unlike `ALLOWED_TICKERS` (empty = allow all), `ALLOWED_TIMEFRAMES` defaults to `["5m", "15m", "1h"]` and is prescriptive. An empty list should mean "allow all timeframes" for operator flexibility, consistent with the `ALLOWED_TICKERS` convention. This must be enforced in the validator.

### Alternatives Considered

- **Add checks to `WebhookSignalRequest` via Pydantic cross-field validators (`model_validator`)**: Rejected because (a) cross-field validators in Pydantic v2 require `model_validator(mode="after")` which complicates error message extraction, (b) producing distinct `reason_code` values from Pydantic errors requires wrapping logic that is better expressed in a service function, and (c) schema-level rejection bypasses the `WebhookEvent` audit trail.
- **Extend the Risk Engine to evaluate signal quality**: Rejected because it breaks the engine's purity guarantee (engine would need signal-value logic independent of TradingContext), requires extending `RiskSignalSnapshot` with new fields (`timeframe`, `event_time`), and would cause quality-rejected signals to be persisted before rejection — inconsistent with the pre-persistence pattern for similar checks.

---

## Risk & Gap Analysis

### Requirement Ambiguities

- **`stop_loss = None` for BUY signal**: Rules 2, 4, 6 require `stop_loss`, but the field is Optional in the schema. The requirement doesn't say whether `None` should yield `invalid_stop_loss` or be silently skipped. **Recommended resolution**: `None` → `invalid_stop_loss` for BUY signals (field is effectively required in V0.1 for quality approval).
- **`take_profit = None` for BUY signal**: Same ambiguity as above. **Recommended resolution**: `None` → `invalid_take_profit` for BUY signals.
- **`price > 0` reason code collision**: The existing schema validator produces `schema_invalid` for `price <= 0`. The requirement expects `invalid_price`. **Recommended resolution**: Remove `price_must_be_positive` from `WebhookSignalRequest` and add an `invalid_price` check at the quality-validation step (see Design Decisions).
- **Scope of `stale_signal` and `unsupported_timeframe`**: The requirement frames all new rules as "signal quality before approving a BUY." Since SELL signals are rejected before reaching quality checks, these rules are de facto BUY-only. However, logically `stale_signal` and `unsupported_timeframe` could apply to any side. **Recommended resolution**: Apply all quality checks only after the side=BUY gate, consistent with the requirement's framing.
- **`ALLOWED_TIMEFRAMES = []` semantics**: Not specified. **Recommended resolution**: Empty list = allow all timeframes (consistent with `ALLOWED_TICKERS` convention).
- **`event_time` in the future**: Not addressed by the requirement. A signal from the future could pass the `MAX_SIGNAL_AGE_SECONDS` check trivially. **Recommended resolution**: Accept future-dated signals in V0.1; add future-date guard only if operationally needed.

### Edge Cases

- **`stop_loss == price`**: Risk calculation `risk = price - stop_loss = 0` → division by zero in `risk_reward = reward / risk`. Must guard against this explicitly — yield `stop_loss_above_entry` (or a dedicated `zero_risk` error, but `stop_loss_above_entry` covers the semantic meaning since stop_loss must be strictly below price for a BUY).
- **`MIN_RISK_REWARD = 0`**: Effectively disables the risk_reward check (any positive ratio passes). This is a valid operator choice and must not be treated as an error.
- **Negative `stop_loss` or `take_profit`**: `Decimal` fields have no lower bound in the schema. A negative value must be caught by the `> 0` checks (`invalid_stop_loss`, `invalid_take_profit`).
- **`MAX_SIGNAL_AGE_SECONDS = 0`**: Any signal that takes more than 0 seconds from TradingView to the server would be rejected as stale. Operators must set a realistic value. The service should guard against this (treat 0 as "disabled" or let it naturally pass/reject based on the value — this needs a decision).
- **Clock skew**: The stale-signal check compares `event_time` (from the TradingView alert, set by TradingView's clock) against `datetime.now(UTC)` (the server clock). Minor skew is acceptable but should be noted in validation docs.
- **`conftest.py` settings fixture**: The base test `settings` fixture in `tests/conftest.py` must be updated to pin the three new settings (`MIN_RISK_REWARD`, `ALLOWED_TIMEFRAMES`, `MAX_SIGNAL_AGE_SECONDS`) — same isolation pattern applied when Resend settings were added, to prevent `.env` leakage.

### Technical Risks

- **`price_must_be_positive` validator removal is a breaking schema change**: Any code or test that currently relies on `WebhookSignalRequest` raising `ValidationError` for `price <= 0` will break. All existing tests must be audited. **Mitigation**: grep for `price_must_be_positive` and `price.*must.*positive` in tests before removing.
- **`signal_service.py` pipeline ordering**: Inserting a new step between steps 4 and 5 must not break the idempotency invariant — a quality-rejected signal must not be counted as a seen `client_signal_id`. Since the new step fires before step 5 (idempotency) and before step 6 (persistence), this is safe by construction.
- **Decimal arithmetic precision**: `risk_reward = (take_profit - price) / (price - stop_loss)` uses `Decimal` division. Python's `Decimal` division is exact but requires context management for scale. The comparison `risk_reward < MIN_RISK_REWARD` (both `Decimal`) is safe. Guard: ensure `price - stop_loss != 0` before dividing.
- **Test fixture date sensitivity**: `stale_signal` tests depend on `datetime.now(UTC)`. Tests that use a fixed `event_time` will become flaky if they don't mock the clock. **Mitigation**: inject or mock `datetime.now` in the quality validator, or use a large enough offset in test fixtures.

### Acceptance Criteria Coverage

| AC# | Description | Addressable? | Gaps/Notes |
|-----|-------------|--------------|------------|
| 1 | `price > 0`, reason `invalid_price` | Yes | Requires removing schema-level `price_must_be_positive` validator |
| 2 | `stop_loss > 0`, reason `invalid_stop_loss` | Yes | `None` treated as missing → `invalid_stop_loss` for BUY |
| 3 | `take_profit > 0`, reason `invalid_take_profit` | Yes | `None` treated as missing → `invalid_take_profit` for BUY |
| 4 | BUY: `stop_loss < price`, reason `stop_loss_above_entry` | Yes | Also covers `stop_loss == price` (division-by-zero guard) |
| 5 | BUY: `take_profit > price`, reason `take_profit_below_entry` | Yes | Covers equality too (`take_profit == price`) |
| 6 | Calculate `risk_reward = (tp - price) / (price - sl)` | Yes | Must guard against zero denominator first |
| 7 | Reject if `risk_reward < MIN_RISK_REWARD` | Yes | |
| 8 | `MIN_RISK_REWARD` setting, default 1.5 | Yes | Same pattern as existing Decimal settings |
| 9 | `ALLOWED_TIMEFRAMES` setting, default `["5m","15m","1h"]` | Yes | Needs comma-string validator in `Settings` |
| 10 | Reject unsupported timeframe, reason `unsupported_timeframe` | Yes | Empty list = allow all |
| 11 | `MAX_SIGNAL_AGE_SECONDS` setting, default 900 | Yes | `MAX_SIGNAL_AGE_SECONDS=0` semantics unclear — needs resolution |
| 12 | Reject stale signals, reason `stale_signal` | Yes | Clock-dependent; test must mock or use large offset |
| 13 | Maintain V0 behavior | Yes | New step inserts before idempotency; no changes to steps 1–4 or 6–10 |
| 14 | No Alpaca | Yes | No changes to execution path |
| 15 | No orders | Yes | No changes to execution path |
| 16 | No Resend adapter changes except test fixtures | Yes | `conftest.py` settings fixture update only |
| 17 | Unit + integration tests | Yes | Unit tests for quality validator in isolation; integration tests via TestClient |
| D1 | `docs/validation/v0.1-validation.md` | Yes | Describe each rule, reason code, HTTP status, and example payloads |
