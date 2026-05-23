# SPDD Analysis: V0.3 — Forward Testing Runner

## Original Business Requirement

Vamos a construir V0.3 del proyecto alpacaview usando OpenSPDD / REASONS Canvas.

Contexto:
V0 está cerrado:
- /webhook/signal
- /integrations/resend/inbound
- validación secret/schema/ticker/side
- Risk Engine
- SQLite auditado
- no Alpaca
- no órdenes

V0.1 está cerrado:
- signal quality validation
- price > 0
- stop_loss > 0
- take_profit > 0
- stop_loss < price para BUY
- take_profit > price para BUY
- risk_reward >= MIN_RISK_REWARD
- timeframe permitido
- stale_signal

V0.2b está cerrado:
- Python ATR Signal Generator
- descarga datos con yfinance
- calcula EMA 21
- calcula ATR 14
- genera price, stop_loss, take_profit dinámicos
- CLI soporta:
  --ticker
  --timeframe
  --period
  --dry-run
  --force
  --send
- manda señales a /webhook/signal
- no Alpaca
- no órdenes

Objetivo V0.3:
Crear forward testing automático cada 15 minutos.

El sistema debe:
1. Ejecutar el signal generator para una lista de tickers.
2. Usar modo real, sin --force.
3. Correr con timeframe 15m y period 5d por defecto.
4. Evaluar tickers: SPY, QQQ, AAPL, MSFT, NVDA.
5. Enviar al backend solo si hay señal real.
6. Registrar en SQLite cada evaluación, incluso cuando no hay señal.
7. Registrar estados:
   - no_signal
   - signal_sent
   - risk_approved
   - risk_rejected
   - duplicate_signal
   - skipped_market_closed
   - insufficient_data
   - error
8. Registrar datos relevantes:
   - run_id
   - ticker
   - timeframe
   - period
   - bar_time
   - client_signal_id
   - price
   - stop_loss
   - take_profit
   - risk_reward
   - backend_status_code
   - backend_signal_id
   - backend_approved
   - backend_reason_code
   - backend_reason_detail
   - error_message
   - created_at_utc
9. Agregar tabla SQLite forward_test_runs.
10. Crear un CLI para ejecutar una corrida:
   python -m src.forward_testing.cli --once --send
11. Permitir:
   --tickers SPY,QQQ,AAPL,MSFT,NVDA
   --timeframe 15m
   --period 5d
   --send
   --dry-run
   --market-hours-only
12. Si --dry-run, no debe llamar al backend, pero puede imprimir lo que habría hecho.
13. Si --send, debe llamar a /webhook/signal cuando hay señal.
14. Si no hay señal, debe guardar no_signal.
15. Si el backend devuelve duplicate_signal, debe guardar duplicate_signal y salir 0.
16. No modificar /webhook/signal.
17. No agregar Alpaca.
18. No crear órdenes.
19. Agregar tests unitarios e integración.
20. Agregar documentación en docs/validation/v0.3-validation.md.

Decisión recomendada:
- No usar scheduler dentro de FastAPI todavía.
- Crear CLI idempotente que corre una vez.
- La automatización cada 15 minutos se hace con cron o launchd.
- Esto evita correr múltiples schedulers si FastAPI se reinicia.

Entrega:
1. REASONS Canvas.
2. Lista de archivos nuevos/modificados.
3. Modelo de datos.
4. Criterios de aceptación.
5. Tests requeridos.
6. Riesgos.

---

## Domain Concept Identification

### Existing Concepts (from codebase)

- **Signal** (`app/models/signal.py`): Persisted outcome of a webhook call that passed all pre-engine checks and received a Risk Engine decision. Lifecycle: `RECEIVED → RISK_APPROVED | RISK_REJECTED`. Already captures `client_signal_id`, `ticker`, `price`, `stop_loss`, `take_profit`, `bar_time_utc`. — The `ForwardTestRun` correlates to a `Signal` via `client_signal_id` when a signal was actually sent and accepted by the server.

- **SignalGenerator** (`src/signal_generator/`): Standalone CLI that downloads OHLCV, computes EMA/ATR, detects crossover, and builds a `dict` payload compatible with `POST /webhook/signal`. Already exposes `fetch_ohlcv`, `compute_indicators`, `build_payload`, `build_client_signal_id` as importable pure functions. — Forward testing orchestrates these functions directly (not via subprocess) to capture intermediate results before any HTTP call.

- **SQLAlchemy Base / SessionLocal / init_db** (`app/database.py`): The project uses SQLAlchemy 2.0 declarative ORM. All models inherit from `Base`. `init_db()` calls `Base.metadata.create_all()` to create all registered tables at server startup. The `init_db()` function is also callable from a standalone CLI. — `ForwardTestRun` must be registered in `Base.metadata` so `init_db()` creates its table automatically.

- **WebhookResponse** (`app/schemas/signal.py`): The server's JSON response body from `POST /webhook/signal`. Contains `signal_id`, `approved`, `reason_code`, `reason_detail`. — Forward testing reads this response to determine and record the final status.

- **RejectionReason / SignalStatus enums** (`app/schemas/enums.py`): Machine-readable codes already used server-side. Forward testing introduces its own status taxonomy (8 states) that maps onto — but is not identical to — the server-side codes. Forward testing statuses are client-side labels, not server-side.

- **Settings / extra="ignore" pattern** (`app/config.py`, `src/signal_generator/config.py`): All config classes use pydantic-settings with `extra="ignore"` so that a shared `.env` file can serve both server and tools. `ForwardTestingSettings` must follow the same convention.

### New Concepts Required

- **ForwardTestRun**: A single-ticker evaluation record from one CLI invocation. Records everything from data fetch through backend response (or skip reason). One `run_id` groups all ticker evaluations from the same CLI call. This is the central new persistent entity. — Lives in `app/models/forward_test_run.py`; registered in `app/models/__init__.py`; written from `src/forward_testing/`.

- **RunStatus**: An 8-value enumeration for the outcome of one ForwardTestRun record: `no_signal`, `signal_sent`, `risk_approved`, `risk_rejected`, `duplicate_signal`, `skipped_market_closed`, `insufficient_data`, `error`. These are forward-testing–specific labels, not aliases for server-side codes.

- **ForwardTestingSettings**: pydantic-settings class in `src/forward_testing/config.py`. Configures the runner: `FORWARD_TESTING_ENABLED`, default tickers, timeframe, period, backend URL, EMA/ATR lengths, ATR multiplier, risk_reward. Follows `extra="ignore"` convention. No new `.env` variables needed for day-one operation — borrows `SIGNAL_GENERATOR_*` defaults where overlap exists.

- **ForwardTestRunner** (conceptual — implemented as a module `src/forward_testing/runner.py`): The orchestration logic. Calls `fetch_ohlcv → compute_indicators → build_payload`, decides whether to POST or record dry-run, interprets the server response, and returns a `RunResult` struct. Receives all dependencies (DB session, settings, HTTP client) as arguments — pure orchestration, no global state.

- **MarketHoursChecker** (conceptual — implemented as a pure function in `src/forward_testing/market_hours.py`): Determines whether the current UTC timestamp falls within US equity market hours (Mon–Fri 09:30–16:00 America/New_York). Receives `now: datetime` as argument for deterministic testing. `pytz` is already present in `requirements.txt`.

- **ForwardTestingCLI** (`src/forward_testing/cli.py`): click CLI entry point. Owns `run_id` generation (UUID4 at startup), iterates over tickers, calls the runner for each, handles exit codes. Designed to be called by cron/launchd — no scheduler, no daemon loop.

### Key Business Rules

- **RunStatus state machine**: One row per ticker per CLI invocation. A `run_id` groups all rows from the same call. Status transitions are terminal — no row is updated after creation.

- **no_signal is not an error**: When `compute_indicators` returns `None` (insufficient data) or crossover is not detected, the row is recorded with `insufficient_data` or `no_signal` respectively and the CLI exits 0.

- **duplicate_signal is not an error**: A 409 from the server is a valid outcome (same bar already processed). Record `duplicate_signal`, exit 0.

- **market-hours-only guard**: When `--market-hours-only` is active and the current time is outside 09:30–16:00 ET Mon–Fri, record `skipped_market_closed` for all tickers and exit 0. No data is fetched, no HTTP calls are made.

- **dry-run still writes to DB**: The requirement says "Registrar en SQLite cada evaluación, incluso cuando no hay señal." Dry-run evaluations go through the full local pipeline (fetch → compute → build) and record the result; they do not call the backend. Status recorded as `no_signal`, `insufficient_data`, or a dry-run variant of the signal statuses.

- **risk_reward is computed locally**: `risk_reward = (take_profit - price) / (price - stop_loss)`, computed from `IndicatorResult` values before any HTTP call. Stored as a Decimal string. Not obtained from the server response.

- **No cross-model FKs**: `ForwardTestRun` does not have a foreign key to `signals.id`. Correlation is via `client_signal_id` (natural key). This is necessary because `no_signal` and `insufficient_data` rows have no corresponding `Signal` row.

- **`FORWARD_TESTING_ENABLED` hard gate**: Same discipline as `PYTHON_SIGNAL_GENERATOR_ENABLED` in V0.2b. CLI checks this as first action. If false, echo message and exit 0.

---

## Strategic Approach

### Solution Direction

- New package `src/forward_testing/` mirrors the `src/signal_generator/` structure — isolated CLI tool with its own config, pure inner modules, and click entry point.
- The DB model (`ForwardTestRun`) lives in `app/models/` to reuse the existing SQLAlchemy `Base`, `SessionLocal`, and `init_db()` infrastructure. This is the single justified cross-boundary dependency: `src/forward_testing/` imports from `app/database.py` and `app/models/forward_test_run.py` only. No service, router, or schema imports.
- Data flow: `CLI → MarketHoursCheck → ForwardTestRunner(per ticker) → [fetch → compute → build_payload] → [HTTP POST if --send] → interpret response → persist ForwardTestRun row`.
- One `run_id` (UUID4) is generated at CLI startup and attached to every row in the batch.

### Key Design Decisions

- **Model location (app/models/ vs. src/forward_testing/own Base)**: Putting the model in `app/models/` reuses `init_db()` and keeps a single SQLite file. A separate Base in `src/` would require a second DB file and a separate migration path. → Recommendation: `app/models/forward_test_run.py` registered in `app/models/__init__.py`. Minimal coupling (DB layer only), maximum operational simplicity.

- **Direct function calls vs. subprocess for signal generator**: Calling `fetch_ohlcv`, `compute_indicators`, `build_payload` directly (as imports) is testable and gives access to intermediate results (e.g., recording `insufficient_data` when `compute_indicators` returns `None`). A subprocess call to `cli.py` would lose those intermediate states. → Recommendation: direct imports from `src.signal_generator.*`.

- **Dry-run DB behavior**: The requirement mandates recording all evaluations. Dry-run rows should be recorded with a status that makes clear no HTTP call was made. The cleanest approach is to add a boolean `is_dry_run` column to `forward_test_runs` rather than creating separate status values like `dry_run_no_signal`. → Raises a design choice for the REASONS Canvas: `is_dry_run` column vs. prefixed status strings.

- **`--once` flag semantics**: The CLI always runs once and exits. `--once` in the example is redundant but harmless. It can be accepted as a documentation flag (no-op) to make cron scripts self-documenting. → Recommendation: accept and ignore `--once` (or document it as the default and only mode).

- **`run_id` granularity**: One UUID per CLI invocation, shared across all tickers. This allows grouping all ticker evaluations from one cron tick for reporting. → Confirmed: generated in `main()` before the ticker loop.

- **`ForwardTestingSettings` vs. reusing `SignalGeneratorSettings`**: There is significant overlap (tickers, timeframe, period, EMA/ATR lengths, backend URL). However, forward testing has additional settings (`FORWARD_TESTING_ENABLED`, `FORWARD_TESTING_DB_URL`). A dedicated `ForwardTestingSettings` avoids silent coupling. → Recommendation: new class in `src/forward_testing/config.py` with `extra="ignore"`. Fields default to values consistent with `SignalGeneratorSettings` but are independently configurable.

### Alternatives Considered

- **In-process scheduler inside FastAPI**: Rejected per requirement. Adds restart risk (multiple scheduler instances), couples the server to the runner lifecycle, complicates testing.
- **Subprocess call to `src.signal_generator.cli`**: Rejected because intermediate states (`insufficient_data`, local payload values) are not accessible from process output. Also harder to test without mocking subprocess.
- **Separate SQLite file for forward testing**: Rejected in favor of shared DB. Two files add operational complexity without benefit at V0 scale.

---

## Risk & Gap Analysis

### Requirement Ambiguities

- **`--once` flag role**: The example shows `--once` but the requirement doesn't describe its effect separately from the default "run once and exit" behavior. Needs clarification: is it a required flag, a no-op documentation marker, or does it imply a future `--loop` mode?

- **Dry-run + DB writes**: Requirement 12 says "no debe llamar al backend, pero puede imprimir lo que habría hecho." Requirement 6 says "Registrar en SQLite cada evaluación." Does dry-run write to the DB? If yes, what status is recorded for a dry-run that produced a signal (never sent)? Needs explicit decision.

- **`signal_sent` vs. `risk_approved`/`risk_rejected` status**: When a signal is sent and the server responds 202 (`approved=True`), is the row status `signal_sent` or `risk_approved`? The requirement lists both. The semantic difference needs clarification: `signal_sent` could mean "we sent it, server hasn't responded yet," or it could be an alias for the post-response state. Recommendation: use `signal_sent` only as a transient state if the server returns an unexpected code; use `risk_approved`/`risk_rejected` for 202/200 responses.

- **`backend_approved` field for non-sent rows**: For `no_signal`, `insufficient_data`, `skipped_market_closed` — `backend_approved` is `NULL`. For `error` — may be `NULL` if the request never completed. Confirm all nullable fields.

- **`--market-hours-only` + weekend behavior**: US equity markets are closed on weekends. Should weekend be treated as `skipped_market_closed`? Recommendation: yes — include weekday check in the market hours function.

- **`period` field in `forward_test_runs`**: The requirement lists `period` as a recorded field. Since `period` is a yfinance lookback string (e.g., `"5d"`), it is a CLI input, not a bar-level concept. It should be stored as passed (string), not derived from bar data.

### Edge Cases

- **CLI invoked outside market hours without `--market-hours-only`**: The flag is opt-in. Without it, the runner proceeds regardless of market hours. yfinance may return stale or reduced data on weekends/after hours. This is a pre-existing behavior from V0.2b and is not a regression.

- **All tickers produce `no_signal` in one run**: Valid. Five rows with `no_signal`, exit 0. Nothing is sent. This should be the most common outcome.

- **One ticker causes a `DataFetchError` while others succeed**: The error should be isolated to that ticker's row (status=`error`, `error_message` populated). Other tickers should continue. The CLI should not exit 1 because of a single ticker failure unless all tickers fail.

- **DB write failure during a run**: If writing a `ForwardTestRun` row fails (e.g., DB locked), should the CLI continue with remaining tickers or abort? Recommendation: log the error, continue, exit 1 at the end.

- **First-run DB schema**: `forward_test_runs` is a new table. If the server has been run before and `alpacaview.db` exists, the table won't exist until `init_db()` is called again. The standalone CLI must call `init_db()` (or its equivalent) at startup before writing any rows.

- **`client_signal_id` uniqueness across dry-run rows**: `build_client_signal_id` is deterministic (same bar → same ID). If dry-run is called twice within the same 15-minute bar, both rows will have the same `client_signal_id`. `forward_test_runs` does NOT enforce uniqueness on `client_signal_id` (unlike `signals`), so this is safe.

- **`stop_loss <= 0` case**: `build_payload` returns `None` when `stop_loss <= 0`. Forward testing must record this as `no_signal` (or a specific status) — not as `error`. It mirrors V0.2b's behavior.

### Technical Risks

- **DB coupling from src/**: `src/forward_testing/` importing from `app/` breaks the "no app imports" invariant established in V0.2b. This is a deliberate, scoped exception (DB layer only). Risk: future refactors of `app/database.py` could affect the forward testing CLI. Mitigation: document the dependency explicitly in REASONS Canvas Norms.

- **yfinance rate limiting**: Multiple tickers (5) per invocation + cron every 15 minutes = up to 20 yfinance requests/hour. yfinance has undocumented rate limits. Mitigation: sequential ticker processing (no parallelism), no retry loop per ticker, existing `DataFetchError` isolation.

- **Market hours timezone handling**: `pytz` is installed, but `America/New_York` DST transitions happen twice yearly. Using `pytz.timezone("America/New_York")` with `localize()` handles this correctly. Risk: naive datetime comparison without proper localization produces incorrect results during DST weeks. Mitigation: enforce UTC input → `astimezone(nyc)` pattern in `market_hours.py`.

- **`init_db()` table creation race**: If two CLI invocations start simultaneously and both call `init_db()`, SQLAlchemy's `create_all()` is idempotent (`CREATE TABLE IF NOT EXISTS` semantics). No risk.

- **SQLite concurrent writes**: SQLite uses file-level locking. If the FastAPI server is writing (webhook processing) simultaneously with the forward testing CLI writing, there may be a brief lock contention. At V0 scale (one server, one CLI) this is a momentary retry handled by SQLite automatically. Not a real risk at this scale.

### Acceptance Criteria Coverage

| AC# | Description | Addressable? | Gaps/Notes |
|-----|-------------|--------------|------------|
| 1 | Execute signal generator for ticker list | Yes | Via direct imports from `src.signal_generator.*` |
| 2 | Real mode only (no --force) | Yes | `force=False` hardcoded in runner |
| 3 | Default timeframe 15m, period 5d | Yes | `ForwardTestingSettings` defaults |
| 4 | Default tickers: SPY, QQQ, AAPL, MSFT, NVDA | Yes | `ForwardTestingSettings` defaults |
| 5 | Send to backend only on real signal | Yes | Runner posts only when `crossover_detected=True` and `build_payload` returns non-None |
| 6 | Record in SQLite every evaluation | Yes | One `forward_test_runs` row per ticker per run |
| 7 | Record 8 status values | Yes | `RunStatus` enum with 8 values |
| 8 | Record 17 data fields | Yes | All fields in `ForwardTestRun` model; nullability to be specified in REASONS Canvas |
| 9 | Add `forward_test_runs` table | Yes | Model in `app/models/forward_test_run.py` |
| 10 | CLI: `python -m src.forward_testing.cli --once --send` | Yes | `--once` accepted as no-op (see ambiguity above) |
| 11 | CLI flags: --tickers, --timeframe, --period, --send, --dry-run, --market-hours-only | Yes | All implemented in click CLI |
| 12 | --dry-run: no backend call | Yes | Runner skips HTTP when dry_run=True |
| 13 | --send: call /webhook/signal on signal | Yes | Runner calls `_post_payload` when `send=True` |
| 14 | no_signal saved when no crossover | Yes | Runner records `no_signal` row |
| 15 | duplicate_signal on 409, exit 0 | Yes | Runner maps 409+duplicate_signal → status=`duplicate_signal`, exit 0 |
| 16 | No /webhook/signal modification | Yes | `app/routers/webhook.py` untouched |
| 17 | No Alpaca | Yes | No Alpaca imports anywhere in `src/forward_testing/` |
| 18 | No orders | Yes | Runner produces records only |
| 19 | Unit + integration tests | Yes | See test plan below |
| 20 | docs/validation/v0.3-validation.md | Yes | Operator guide |
| Gap | Dry-run DB write behavior | Partial | Needs explicit decision: write with `is_dry_run=True` column or not write at all |
| Gap | `--once` semantics | Partial | Needs explicit decision before REASONS Canvas |
| Gap | Single-ticker error isolation vs. batch exit code | Partial | Needs explicit decision: exit 0 if at least one ticker succeeds, or always exit 1 on any error? |
