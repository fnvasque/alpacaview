# SPDD Analysis: V0.2b — Python Signal Generator

## Original Business Requirement

Vamos a construir V0.2b del proyecto alpacaview usando OpenSPDD / REASONS Canvas.

Contexto:
V0 ya está cerrado.
V0.1 ya está cerrado.
El backend ya recibe señales por /webhook/signal y /integrations/resend/inbound.
V0.1 valida:
- secret
- schema
- ticker allowlist
- side buy only
- duplicate_signal
- unsupported asset class
- kill switch
- max daily trades
- price > 0
- stop_loss > 0
- take_profit > 0
- BUY stop_loss < price
- BUY take_profit > price
- risk_reward >= MIN_RISK_REWARD
- timeframe permitido
- stale_signal

Objetivo V0.2b:
Crear un generador local en Python que reemplace temporalmente TradingView para evitar pagar alertas técnicas.

El generador debe:
1. Descargar datos OHLCV usando yfinance.
2. Soportar tickers permitidos: SPY, QQQ, AAPL, MSFT, NVDA.
3. Usar timeframe 15m por defecto.
4. Calcular EMA 21.
5. Calcular ATR 14.
6. Detectar señal BUY simple:
   previous_close <= previous_ema AND current_close > current_ema
7. Calcular:
   price = current close
   stop_loss = price - ATR * ATR_MULTIPLIER
   risk = price - stop_loss
   take_profit = price + risk * RISK_REWARD
8. Armar payload compatible con /webhook/signal.
9. Generar client_signal_id determinístico:
   python_atr_generator:0.2b.0:{ticker}:{timeframe}:{bar_time}:buy
10. Incluir modo dry-run que solo imprime el payload.
11. Incluir modo force que genera señal aunque no haya crossover, para pruebas.
12. Incluir modo send que hace POST a BACKEND_URL/webhook/signal.
13. No conectar Alpaca.
14. No crear órdenes.
15. No modificar /webhook/signal.
16. No modificar Risk Engine salvo que sea estrictamente necesario.
17. Agregar tests unitarios para EMA, ATR, crossover y payload.
18. Agregar documentación en docs/validation/v0.2b-validation.md.

Settings esperados:
- PYTHON_SIGNAL_GENERATOR_ENABLED=false
- SIGNAL_GENERATOR_BACKEND_URL=http://127.0.0.1:8000
- SIGNAL_GENERATOR_SECRET=test-secret
- SIGNAL_GENERATOR_TICKERS=["SPY","QQQ","AAPL","MSFT","NVDA"]
- SIGNAL_GENERATOR_TIMEFRAME=15m
- SIGNAL_GENERATOR_PERIOD=5d
- EMA_LENGTH=21
- ATR_LENGTH=14
- ATR_MULTIPLIER=1.5
- RISK_REWARD=2.0

Entrega:
1. REASONS Canvas.
2. Lista de archivos nuevos/modificados.
3. Decisiones técnicas.
4. Criterios de aceptación.
5. Tests requeridos.

---

## Domain Concept Identification

### Existing Concepts (from codebase)

- **WebhookSignalRequest**: The payload contract for `POST /webhook/signal`. Required fields: `secret`, `strategy`, `version`, `ticker`, `side`, `price`, `timeframe`, `bar_time`, `event_time`, `client_signal_id`. Optional: `stop_loss`, `take_profit`. All price fields are `Decimal`. Timestamps are UTC-normalised. The generator must produce a dict matching this schema exactly.
- **Settings (app/config.py)**: pydantic-settings `BaseSettings` pattern with `.env` loading. `ALLOWED_TICKERS`, `ALLOWED_TIMEFRAMES`, `MIN_RISK_REWARD` are already present. The generator introduces its own settings namespace; it must not extend or import `app/config.py` settings to preserve standalone operation.
- **Validation pipeline (signal_service.py)**: The existing 10-step pipeline accepts the generated payload as-is. No changes needed. The `client_signal_id` determinism guarantees idempotency without any generator-side deduplication logic.
- **RejectionReason / WebhookResponse**: The server returns structured JSON on rejection. The generator's "send" mode must parse the response and log the reason code for observability.

### New Concepts Required

- **SignalGeneratorSettings**: A standalone pydantic-settings config class in `src/signal_generator/config.py`. Holds all `SIGNAL_GENERATOR_*` and indicator settings. Completely decoupled from `app/config.py`. The `PYTHON_SIGNAL_GENERATOR_ENABLED` flag is checked at CLI entry, not inside the webhook server.
- **OHLCV DataFrame**: The unit of data downloaded from yfinance. Columns: `Open`, `High`, `Low`, `Close`, `Volume`. Index: timezone-aware `DatetimeIndex`. Serves as the input to all indicator calculations.
- **IndicatorSet**: The computed output from indicator functions for the latest two bars (previous and current). Holds: `current_close`, `current_ema`, `current_atr`, `previous_close`, `previous_ema`, `bar_time` (UTC timestamp of the current bar). This is the direct input to crossover detection and payload construction.
- **CrossoverSignal**: A boolean + metadata struct indicating whether a BUY crossover was detected on the most recent completed bar. The signal is: `previous_close <= previous_ema AND current_close > current_ema`.
- **GeneratedPayload**: A dict (compatible with `WebhookSignalRequest`) assembled from the crossover context. Fields computed: `price` = current close, `stop_loss` = price − ATR × ATR_MULTIPLIER, `take_profit` = price + (price − stop_loss) × RISK_REWARD, `client_signal_id` = deterministic string.
- **CLI (dry-run / force / send)**: The generator's three operating modes. They share the same indicator and payload logic; only the final action differs (print, print+bypass-check, HTTP POST).

### Key Business Rules

- **Generator is a client, not a server extension**: The generator is a standalone CLI tool in `src/`. It must never be imported by the FastAPI application. Adding it must not affect the webhook server's startup, tests, or behaviour.
- **Deterministic `client_signal_id`**: `python_atr_generator:0.2b.0:{ticker}:{timeframe}:{bar_time}:buy` — the bar_time component must be the UTC ISO 8601 timestamp of the completed bar (not the current wall-clock time). Same bar → same ID → idempotency protection from the server's duplicate check.
- **Only completed bars**: The generator must use only the bar that is fully completed at the time of execution — never the in-progress (live) bar. yfinance may include a partial current bar; the generator must discard it.
- **`PYTHON_SIGNAL_GENERATOR_ENABLED=false` as a hard gate**: If the flag is false, the CLI must exit before making any network calls or printing any payload. This prevents accidental signal injection.
- **No Alpaca, no order creation, no Risk Engine modification**: The generator's output is a payload. What the server does with it is governed by the existing pipeline. No V0 invariants are touched.
- **`strategy="python_atr_generator"`, `version="0.2b.0"`**: These are fixed constants in the payload, not configurable settings.

---

## Strategic Approach

### Solution Direction

- Build a **standalone Python CLI tool** in `src/signal_generator/`, using `click` (already installed). The tool is not a FastAPI module and is not imported by the server.
- Structure the generator into three pure-function modules (data, indicators, payload) plus a CLI entry point and a config module — mirroring the server's purity pattern (`app/risk/engine.py`).
- All indicator calculations use **pandas operations on the OHLCV DataFrame**; no custom loop-based implementations. `yfinance` already in `requirements.txt`; `pandas` and `numpy` already present.
- Settings follow the **same pydantic-settings pattern** as the server (`BaseSettings` + `.env` loading), but in a separate class to preserve decoupling.
- The generator iterates over `SIGNAL_GENERATOR_TICKERS` and for each ticker: fetch → compute indicators → evaluate crossover → (optionally) build and dispatch payload.

### Key Design Decisions

- **`src/signal_generator/` as the home directory** vs. `app/generators/`: The `src/` directory already exists and is empty — it is structurally designated for standalone tools separate from the FastAPI app. Placing the generator there preserves `app/` as server-only code. → **Recommendation: `src/signal_generator/`**.

- **Separate `SignalGeneratorSettings` class** vs. extending `app/config.py`: The generator must be runnable without the FastAPI server, without a database URL, and with its own `.env` variables. Extending the server's `Settings` would introduce server-side dependencies and complicate the server's test fixtures. → **Recommendation: separate class**.

- **`bar_time` in `client_signal_id`**: The timestamp must be the **UTC ISO 8601 string of the completed bar's start time** (e.g., `2026-05-20T14:30:00+00:00` or `2026-05-20T14:30:00Z`). Using the bar's open time (index) ensures consistency across runs and matches TradingView's `bar_time` semantics. → **Recommendation: bar start time, UTC, ISO 8601**.

- **"send" mode HTTP error handling**: On non-2xx response, the generator should log the full response body (which contains `reason_code`) and exit with a non-zero code. No retries in V0.2b. → **Recommendation: log + exit(1) on failure**.

- **"force" mode semantics**: Force mode bypasses the crossover check and uses the last completed bar's data to build and submit the payload regardless. Useful for testing the full pipeline end-to-end. → **Recommendation: skip crossover check, all other logic identical**.

- **Only one bar evaluated per run** vs. scanning all bars for crossovers: The generator is designed to be run periodically (e.g., cron at 15m intervals). Each run evaluates the most recent completed bar only. Scanning history for multiple crossovers is out of scope. → **Recommendation: evaluate last completed bar only**.

### Alternatives Considered

- **pandas-ta or TA-Lib for indicators**: More comprehensive but adds a dependency. EMA and ATR are simple enough to implement directly with pandas — `ewm(span=N, adjust=False).mean()` for EMA; true-range rolling mean for ATR. No extra dependency needed. → **Rejected: unnecessary dependency**.
- **Placing generator inside `app/generators/`**: Would require updating the server's import graph, risking accidental coupling. `src/` is the right isolation boundary. → **Rejected: breaks server/tool separation**.
- **`typer` for CLI**: More ergonomic but adds a dependency. `click` is already installed. → **Rejected: unnecessary dependency**.

---

## Risk & Gap Analysis

### Requirement Ambiguities

- **`bar_time` format in `client_signal_id`**: The requirement says `{bar_time}` but doesn't specify the format. The server's `normalize_to_utc` validator accepts any ISO 8601 with timezone. For the ID, the format must be consistent across runs (same bar → same string). Recommend: `bar.name.isoformat()` after converting to UTC, producing `2026-05-20T14:30:00+00:00`.

- **`event_time` vs. `bar_time` in the payload**: The server requires both. `bar_time` = timestamp of the bar that produced the signal. `event_time` = timestamp of when the signal was generated (wall-clock `datetime.now(UTC)`). The requirement doesn't distinguish — this must be explicit in the REASONS Canvas.

- **"5d" period and 15m timeframe**: yfinance's `1m`–`60m` intraday data has a rolling availability window. For `interval="15m"`, yfinance supports up to 60 days of history. "5d" is well within that window. However, intraday data is only available on trading days; weekend/holiday runs will use Friday's last bar.

- **`PYTHON_SIGNAL_GENERATOR_ENABLED` scope**: The flag name implies it lives in the server's `app/config.py`. However, the generator is a standalone tool. If the flag is only in the generator's own settings, the server is unaware of it. The requirement should clarify: the flag is a generator-side guard only, not a server-side feature flag.

- **Decimal precision for price/stop_loss/take_profit in the payload**: The server expects `Decimal`-compatible strings. yfinance returns `float` for OHLCV prices. The generator must convert to `str` with sufficient decimal places before building the payload. Recommend: `f"{value:.4f}"`.

- **`RISK_REWARD` setting name collides with server-side `MIN_RISK_REWARD`**: The generator uses `RISK_REWARD` to compute `take_profit = price + risk * RISK_REWARD`. This is a multiplier (e.g., 2.0 = 2× the risk distance). The server uses `MIN_RISK_REWARD` as a floor for the ratio. These are different values with different semantics. The REASONS Canvas must name them clearly to avoid confusion.

### Edge Cases

- **ATR period not satisfied**: If fewer than `ATR_LENGTH` bars are available (e.g., generator run on a short history), ATR will be NaN. The generator must validate that indicators are non-NaN before building the payload and exit with a clear error message.

- **No crossover in normal mode**: The most common case. The generator must exit cleanly with a logged "no crossover" message. This is not an error — it is the expected case most of the time.

- **Intraday partial bar**: yfinance's intraday download may include an in-progress bar as the last row. The generator must drop it and use the second-to-last bar as "current" and third-to-last as "previous". Alternatively, use all rows and rely on the fact that data is fetched only after a bar close (cron timing). The safer approach is to always skip the last row.

- **stop_loss <= 0**: If `ATR_MULTIPLIER` is very high or the price is very low, `stop_loss = price - ATR * multiplier` could be negative. The generator must validate `stop_loss > 0` before sending and exit with an error.

- **risk_reward ratio check**: The server validates `risk_reward >= MIN_RISK_REWARD`. The generator's `RISK_REWARD` setting (default 2.0) must be set such that the computed ratio matches `MIN_RISK_REWARD` (default 1.5). At default settings, ratio = 2.0 ≥ 1.5 — passes. But if a user sets `RISK_REWARD=1.0` and `MIN_RISK_REWARD=1.5`, the server will reject the payload. The generator can optionally warn but must not duplicate server validation.

- **Market holiday / pre-market run**: If the generator is run before market open, yfinance may return no 15m bars for the current day. The generator must handle an empty or insufficient DataFrame gracefully.

- **Duplicate signal on retry**: If the generator runs again for the same bar (e.g., cron overlap), the server's idempotency check will return 409. The generator must handle this as a non-error case (signal already processed).

### Technical Risks

- **yfinance rate limits and flakiness**: yfinance is an unofficial Yahoo Finance scraper. It can fail with HTTP 429 or return malformed data. The generator must wrap fetches with error handling and exit with a clear error (not a traceback) on failure. → Mitigation: catch exceptions from `yfinance.download()` and log a structured error before exiting.

- **Timezone handling**: yfinance returns intraday data with `America/New_York` timezone on the index (for US equities). The generator must convert to UTC before using timestamps in the payload or the `client_signal_id`. Failure to do so will cause mismatched IDs across time zones and may cause the server's stale signal check to reject valid signals.

- **Test isolation**: Unit tests for indicators must not call yfinance. They must use pre-built synthetic DataFrames (pandas fixtures). The `data_fetcher` module must be mockable. → Mitigation: separate the fetcher from the indicator logic; test indicators with synthetic data only.

- **`requirements.txt` is frozen**: `yfinance`, `pandas`, `numpy`, `requests`, and `click` are already in `requirements.txt`. No new runtime dependencies are needed. Tests need no additional libraries. This is confirmed by the current `requirements.txt`.

### Acceptance Criteria Coverage

| AC# | Description | Addressable? | Gaps/Notes |
|-----|-------------|--------------|------------|
| 1 | Download OHLCV via yfinance | Yes | Must handle empty/insufficient data gracefully |
| 2 | Support SPY, QQQ, AAPL, MSFT, NVDA | Yes | Via `SIGNAL_GENERATOR_TICKERS` list |
| 3 | Default timeframe 15m | Yes | Mapped to yfinance `interval="15m"` |
| 4 | Calculate EMA 21 | Yes | pandas `ewm(span=21, adjust=False).mean()` |
| 5 | Calculate ATR 14 | Yes | True range rolling mean over 14 bars |
| 6 | Detect BUY crossover | Yes | `prev_close <= prev_ema AND curr_close > curr_ema` |
| 7 | Calculate price/stop_loss/take_profit | Yes | Must validate `stop_loss > 0` before building payload |
| 8 | Build compatible payload | Yes | Must match `WebhookSignalRequest` field names exactly |
| 9 | Deterministic `client_signal_id` | Yes | Format must use UTC bar_time string consistently |
| 10 | dry-run mode | Yes | Print payload JSON; no HTTP call |
| 11 | force mode | Yes | Skip crossover check; use last completed bar |
| 12 | send mode | Yes | POST to BACKEND_URL; log response including error reason_code |
| 13 | No Alpaca | Yes | No Alpaca imports anywhere in generator |
| 14 | No orders | Yes | Generator is payload-only |
| 15 | No webhook/signal changes | Yes | Server untouched |
| 16 | No Risk Engine changes | Yes | Risk Engine untouched |
| 17 | Unit tests for EMA, ATR, crossover, payload | Yes | Synthetic DataFrames; no network in tests |
| 18 | docs/validation/v0.2b-validation.md | Yes | Operator guide: settings, modes, output format |
| S1 | `PYTHON_SIGNAL_GENERATOR_ENABLED` flag | Yes | Generator-side guard only; clarify it is NOT a server setting |
| S2 | event_time vs bar_time distinction | Partial | Requirement doesn't distinguish; must be explicit in Canvas |
| S3 | Partial bar handling | Partial | Must drop last bar; requirement is silent on this |
| S4 | 409 duplicate handling in send mode | Partial | Requirement doesn't specify; recommend treat as non-error |
