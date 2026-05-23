# SPDD Analysis: V0.4 — Streamlit Dashboard

## Original Business Requirement

Vamos a construir V0.4 del proyecto alpacaview usando OpenSPDD / REASONS Canvas.

Cambio de decisión:
No queremos un HTML estático como dashboard principal.

Objetivo V0.4:
Crear un dashboard interactivo local usando Streamlit para visualizar métricas reales del sistema.

Contexto:
V0 está cerrado:
- signal ingestion
- /webhook/signal
- Resend adapter
- Risk Engine
- SQLite
- no Alpaca
- no órdenes

V0.1 está cerrado:
- signal quality validation
- price > 0
- stop_loss > 0
- take_profit > 0
- risk_reward mínimo
- timeframe permitido
- stale_signal

V0.2b está cerrado:
- Python ATR Signal Generator
- yfinance
- EMA 21
- ATR 14
- price, stop_loss, take_profit dinámicos

V0.3 está cerrado:
- forward testing automático cada 15 minutos
- tabla forward_test_runs
- no_signal, risk_approved, risk_rejected, duplicate_signal, skipped_market_closed

V0.3b está cerrado:
- outcome evaluator
- tabla signal_outcomes
- outcomes: take_profit_hit, stop_loss_hit, ambiguous_same_bar, timeout, pending, no_data, error
- pnl_r, pnl_pct, MFE, MAE

Objetivo V0.4:
Crear un dashboard interactivo local en Streamlit.

El dashboard debe:
1. Leer datos desde SQLite.
2. Usar principalmente:
   - forward_test_runs
   - signal_outcomes
   - risk_decisions
   - signals
   - webhook_events cuando aplique
3. Mostrar métricas globales:
   - total_signals
   - evaluated_signals
   - pending_signals
   - take_profit_hits
   - stop_loss_hits
   - timeouts
   - ambiguous_same_bar
   - win_rate
   - avg_r
   - total_r
   - avg_pnl_pct
4. Mostrar métricas por ticker:
   - ticker
   - total_outcomes
   - take_profit_hit
   - stop_loss_hit
   - timeout
   - pending
   - win_rate
   - avg_r
   - total_r
5. Mostrar señales bloqueadas:
   - total risk_rejected
   - count por backend_reason_code
   - count por ticker
6. Mostrar evolución diaria:
   - date
   - signals_generated
   - signals_evaluated
   - take_profit_hit
   - stop_loss_hit
   - win_rate
   - avg_r
   - total_r
   - blocked_signals
7. Incluir filtros:
   - date range
   - ticker
   - outcome
   - status
8. Crear app Streamlit:
   streamlit run dashboard/streamlit_app.py
9. Crear páginas:
   - Overview
   - Outcomes by Ticker
   - Blocked Signals
   - Daily Evolution
   - Raw Data
10. Mantener lógica de métricas separada del dashboard.
11. No modificar /webhook/signal.
12. No agregar Alpaca.
13. No crear órdenes.
14. Agregar tests unitarios para las métricas.
15. Agregar documentación en docs/validation/v0.4-validation.md.

Reglas de cálculo:
- win_rate = take_profit_hit / (take_profit_hit + stop_loss_hit)
- avg_r = promedio de pnl_r solo cuando pnl_r no es null
- total_r = suma de pnl_r solo cuando pnl_r no es null
- pending, timeout, ambiguous_same_bar, no_data y error no entran al denominador de win_rate
- risk_rejected se considera señal bloqueada
- duplicate_signal no se considera nueva señal bloqueada

No usar React.
No usar frontend complejo.
No usar CDN obligatorio.
No usar Alpaca.
No crear órdenes.

Entrega:
1. REASONS Canvas.
2. Modelo de métricas.
3. Arquitectura del dashboard.
4. Archivos a crear/modificar.
5. Tests requeridos.
6. Riesgos.

---

## Domain Concept Identification

### Existing Concepts (from codebase)

- **ForwardTestRun** (`forward_test_runs`): records each ATR generator invocation per ticker. Status values observed in code: `no_signal`, `signal_candidate`, `risk_approved`, `risk_rejected`, `duplicate_signal`, `skipped_market_closed`, `insufficient_data`, `error`, `signal_sent`. Carries `backend_reason_code` for `risk_rejected` rows. Has `is_dry_run` flag. `client_signal_id` is nullable (only present when a signal was actually generated). One row per ticker per run, multiple rows may share the same `client_signal_id` (e.g., a re-run evaluating the same bar).

- **SignalOutcome** (`signal_outcomes`): persists evaluated outcome for each signal. `client_signal_id` is UNIQUE — exactly one row per signal regardless of how many `forward_test_runs` rows reference it. Outcome values in current implementation: `take_profit_hit`, `stop_loss_hit`, `ambiguous_same_bar`, `timeout`, `pending`. Carries `pnl_r` (4dp string, nullable), `pnl_pct` (6dp string, nullable), `max_favorable_excursion`, `max_adverse_excursion`. Has `is_dry_run_source` flag inherited from source row.

- **Signal** (`signals`): webhook-received signals that passed all pre-engine validation and were evaluated by the Risk Engine. Status is `RISK_APPROVED` or `RISK_REJECTED`. Has `client_signal_id` (UNIQUE), `ticker`, `strategy`, `version`, `side`. Distinct population from `forward_test_runs` — these come from real TradingView webhooks, not from the ATR generator.

- **RiskDecision** (`risk_decisions`): 1:1 with `Signal`. `approved=True/False`, `reason_code` (populated even for approved+deferred), `is_enforcement_deferred`. Foreign key `signal_id` → `signals.id`.

- **WebhookEvent** (`webhook_events`): audit log for pre-engine rejections (AUTH_FAILED, SCHEMA_INVALID, UNSUPPORTED_ASSET_CLASS, DUPLICATE_SIGNAL, UNSUPPORTED_SIDE). No foreign key to `signals`. `client_signal_id` nullable.

- **DatabaseSession** (`app/database.py`): SQLAlchemy engine + `SessionLocal` factory. `DATABASE_URL` env var controls the SQLite file path. The `Base` declarative base registers all models.

### New Concepts Required

- **DashboardSettings**: pydantic-settings class for the dashboard. Must tolerate the shared `.env` file (all other tools use `extra="ignore"`). Needs at minimum `DASHBOARD_DB_URL` (defaults to same SQLite path as the rest of the system). No secret required — the dashboard is read-only.

- **GlobalMetrics**: a dataclass (or typed dict) representing the 11 global summary metrics: `total_signals`, `evaluated_signals`, `pending_signals`, `take_profit_hits`, `stop_loss_hits`, `timeouts`, `ambiguous_signals`, `win_rate`, `avg_r`, `total_r`, `avg_pnl_pct`. Computed by the metrics layer, consumed by the UI.

- **TickerMetrics**: per-ticker row with `ticker`, `total_outcomes`, `take_profit_hit`, `stop_loss_hit`, `timeout`, `pending`, `win_rate`, `avg_r`, `total_r`.

- **BlockedSignalMetrics**: summary of `risk_rejected` rows: `total_rejected`, breakdown by `backend_reason_code`, breakdown by `ticker`.

- **DailyMetrics**: one row per calendar date: `date`, `signals_generated`, `signals_evaluated`, `take_profit_hit`, `stop_loss_hit`, `win_rate`, `avg_r`, `total_r`, `blocked_signals`.

- **MetricsService** (`dashboard/metrics.py`): pure functions that receive a SQLAlchemy session and filter parameters, query the DB, and return the metric structures above. No Streamlit imports. Fully unit-testable with injected sessions.

- **Streamlit app** (`dashboard/streamlit_app.py`): entry point. Multi-page navigation using Streamlit's `pages/` convention (supported in Streamlit 1.57.0 already in requirements). 5 pages.

### Key Business Rules

- **win_rate denominator is strictly binary**: only `take_profit_hit` and `stop_loss_hit` count. `pending`, `timeout`, `ambiguous_same_bar`, `no_data`, `error` are excluded from both numerator and denominator.

- **avg_r and total_r use only non-null pnl_r**: signals with null `pnl_r` (ambiguous, timeout, pending) are excluded from R-multiple calculations.

- **risk_rejected ≠ duplicate_signal**: `duplicate_signal` rows in `forward_test_runs` do not represent newly blocked signals — the signal had already been evaluated. Only `status == 'risk_rejected'` counts toward blocked signals.

- **UNIQUE client_signal_id in signal_outcomes**: every metric computed from `signal_outcomes` naturally deduplicates — one row per signal.

- **Dry-run isolation**: `is_dry_run_source` in `signal_outcomes` and `is_dry_run` in `forward_test_runs` distinguish synthetic test runs from production-equivalent runs. Mixing these without filtering produces misleading metrics.

- **pnl_r and pnl_pct are strings**: stored as `"2.0000"` and `"-0.006667"` respectively. The metrics layer must parse these to `float` or `Decimal` before averaging.

- **Two distinct signal pipelines**: `forward_test_runs` (ATR generator, automated) and `signals` + `risk_decisions` (webhook, TradingView-triggered). The dashboard must be explicit about which pipeline each metric comes from, or define a unified view.

---

## Strategic Approach

### Solution Direction

- **Greenfield `dashboard/` package** at the project root — parallel to `src/` and `app/`, following the same package-per-concern convention.
- **Pure metrics layer** (`dashboard/metrics.py`): functions that take a SQLAlchemy session + filter params, return typed Python objects. No Streamlit, no UI, fully testable with an in-memory SQLite fixture.
- **Streamlit multi-page app**: `dashboard/streamlit_app.py` as entry point + `dashboard/pages/` for each of the 5 pages. Streamlit 1.57.0 supports this natively. Each page imports from `metrics.py`.
- **Data flow**: `streamlit_app.py` → `DashboardSettings` → SQLAlchemy session → `MetricsService` → `GlobalMetrics / TickerMetrics / ...` → Streamlit widgets + Plotly charts.
- **Read-only access**: dashboard never writes to the DB. No `POST`, no `session.add()`, no `session.commit()`.
- **No FastAPI dependency**: dashboard connects directly to SQLite via its own SQLAlchemy engine. Does not call the FastAPI server.

### Key Design Decisions

- **D1 — Primary data source for `total_signals`**: The requirement references both `forward_test_runs` and `signal_outcomes` as data sources, but their populations differ. Recommended: define `total_signals` as the count of distinct `client_signal_id` values in `forward_test_runs` where `status IN ('signal_candidate', 'risk_approved', 'risk_rejected', 'duplicate_signal')` (i.e., rows where the ATR generator actually produced a signal, regardless of backend outcome). `evaluated_signals` and `pending_signals` come from `signal_outcomes`. This gives a clear funnel: generated → evaluated → pending/resolved.

- **D2 — Dry-run filter default**: `is_dry_run` and `is_dry_run_source` flags exist in both `forward_test_runs` and `signal_outcomes`. Default: exclude dry-run rows from all metrics. Add a sidebar toggle `"Include dry-run runs"` that re-queries with dry-run included. This prevents inadvertently misleading aggregations from test executions.

- **D3 — Blocked signals data source**: The requirement specifies `backend_reason_code` as the breakdown dimension for blocked signals. This field exists only in `forward_test_runs`. Therefore, the "Blocked Signals" page is sourced exclusively from `forward_test_runs` (status == `risk_rejected`). The webhook pipeline's rejected signals (via `risk_decisions.approved=False`) are a separate population and are NOT included in this view unless explicitly added later.

- **D4 — `no_data` and `error` outcome values**: The requirement's win_rate formula explicitly excludes `no_data` and `error`, but these outcome strings do not exist in the current `OutcomeStatus` enum (`take_profit_hit`, `stop_loss_hit`, `ambiguous_same_bar`, `timeout`, `pending` only). The metrics layer should exclude them by whitelist (only `take_profit_hit` and `stop_loss_hit` enter the win_rate denominator), making it naturally safe if these values are added to the model in a future version.

- **D5 — Multi-page Streamlit architecture**: Use `dashboard/streamlit_app.py` as the main entry point with `st.navigation()` (Streamlit 1.57.0 API) pointing to page functions. This keeps all pages in a single importable module tree under `dashboard/` and avoids the `pages/` magic-directory naming restrictions.

- **D6 — DB connection for dashboard**: Dashboard instantiates its own SQLAlchemy engine via `DashboardSettings.DASHBOARD_DB_URL` (defaults to `sqlite:///./alpacaview.db`, same as the rest of the system). Uses `extra="ignore"` to tolerate the shared `.env`. Does not reuse `app/database.py`'s global `engine` singleton (which belongs to the FastAPI server process).

- **D7 — Daily evolution date grouping**: `signal_outcomes.created_at_utc` and `forward_test_runs.created_at_utc` are stored in UTC. Daily bucketing must use `DATE(created_at_utc)` or equivalent. The daily evolution chart shows calendar dates, not trading sessions. This is consistent and does not require timezone conversion.

### Alternatives Considered

- **Single-file Streamlit app (no pages/)**: simpler but becomes unmaintainable past 200 lines. Rejected — the requirement specifies 5 distinct pages with separate concerns.
- **FastAPI endpoint that serves dashboard metrics**: would introduce an API dependency between dashboard and server. Rejected — the dashboard must be independently runnable, even when the server is down.
- **Use `app/database.py`'s global engine**: couples the dashboard to the FastAPI server's process startup. Rejected — dashboard needs its own connection lifecycle.
- **pandas-based metrics with raw SQL strings**: readable but harder to test, bypasses ORM type safety. Rejected — metrics layer should use SQLAlchemy ORM queries for consistency with the rest of the project.

---

## Risk & Gap Analysis

### Requirement Ambiguities

- **`total_signals` definition**: The requirement lists it under global metrics but does not specify whether it counts `forward_test_runs` rows, `signal_outcomes` rows, or `signals` (webhook) rows. These are three different numbers. Resolved via D1: count distinct `client_signal_id` in `forward_test_runs` where status indicates a signal was generated.

- **`no_data` and `error` as outcome values**: The requirement states these are valid `signal_outcomes` outcomes, but they are absent from the current `OutcomeStatus` enum in the implementation. The win_rate formula excludes them by name. The dashboard should handle them defensively (whitelist approach), but their absence from the DB means they won't appear in current data.

- **"Señales bloqueadas" pipeline scope**: The requirement says "total risk_rejected, count por backend_reason_code" — `backend_reason_code` only exists in `forward_test_runs`. But `risk_decisions` (webhook pipeline) also has a `reason_code` for rejections. The analysis resolves this as forward-testing pipeline only (D3), but this should be confirmed.

- **Filter `status` meaning**: The sidebar filter "status" is ambiguous — it could mean `forward_test_runs.status`, `signal_outcomes.outcome`, or `signals.status`. Clarification needed: each page should apply filters relevant to its own data source.

- **Raw Data page scope**: Which tables does the Raw Data page show? All 5 tables? Only `forward_test_runs` and `signal_outcomes`? The requirement does not specify.

### Edge Cases

- **Empty database**: No rows in any table. All metrics must return zero/null gracefully. Win_rate with 0 denominator must return `None` or `0.0`, not raise `ZeroDivisionError`.

- **All signals pending**: `evaluated_signals=0`, `win_rate=None`. The UI must render this state without errors.

- **DB file does not exist at startup**: SQLAlchemy will create the file on `create_engine()`. But if `DASHBOARD_DB_URL` points to the wrong path, all queries return empty results silently. The app should show a warning when all tables are empty.

- **`pnl_r` string parsing**: `pnl_r` can be `"2.0000"`, `"-1.0000"`, or `None`. Float conversion must handle the null case. The string `"-1.0000"` is valid and must round-trip correctly.

- **Date range filter with no data in range**: All metrics must return empty/zero without error when the selected date range contains no rows.

- **Duplicate `client_signal_id` in `forward_test_runs`**: Multiple rows can share the same `client_signal_id` (the generator may evaluate the same bar across multiple runs). `total_signals` must count distinct values, not row count.

- **Mixed dry-run and live data**: If `is_dry_run=True` rows are included accidentally, win_rate and avg_r will be skewed by synthetic runs that never actually reached the backend.

### Technical Risks

- **Streamlit session state with SQLAlchemy sessions**: SQLAlchemy sessions are not thread-safe across Streamlit reruns. The dashboard must create a new session per page render (or per button interaction), not cache sessions in `st.session_state`. Use `@st.cache_resource` for the engine only, create short-lived sessions per query.

- **Performance on growing SQLite**: As `forward_test_runs` and `signal_outcomes` accumulate rows over weeks/months, unindexed full-table scans in the metrics layer will slow down the dashboard. The metrics queries should always filter by `created_at_utc` (already indexed on `ticker`). Consider adding a `created_at_utc` index in the future.

- **Pandas / Streamlit DataFrame display of Decimal strings**: `pnl_r` and `pnl_pct` are stored as strings. When displayed in a Streamlit `st.dataframe()`, they sort lexicographically (so `"2.0000" > "10.0000"` is false lexicographically but `"-1.0000"` sorts before `"0"` correctly). The Raw Data page should cast these columns to float for display.

- **Streamlit's `st.navigation()` vs `pages/` in v1.57.0**: The `st.navigation()` API was introduced in Streamlit 1.36.0. Using it with `st.Page()` objects is the current recommended approach for Streamlit ≥ 1.36. The `pages/` magic directory is legacy. Either works; `st.navigation()` gives more control over page titles and URLs.

- **`requirements.txt` already includes Streamlit 1.57.0 and Plotly 6.7.0**: No new dependencies are required. However, `streamlit` is currently only imported by the dashboard — it must not be accidentally imported by `app/` or `src/` modules.

### Acceptance Criteria Coverage

| AC# | Description | Addressable? | Gaps/Notes |
|-----|-------------|--------------|------------|
| 1 | Read data from SQLite | Yes | Dashboard engine from `DASHBOARD_DB_URL` |
| 2 | Use forward_test_runs, signal_outcomes, risk_decisions, signals, webhook_events | Yes | All 5 tables present in ORM |
| 3 | Global metrics (11 fields) | Yes | `no_data`/`error` handled defensively |
| 4 | Metrics by ticker (9 columns) | Yes | From `signal_outcomes` grouped by `ticker` |
| 5 | Blocked signals (3 views) | Yes | From `forward_test_runs` where status=risk_rejected; D3 confirms scope |
| 6 | Daily evolution (8 columns) | Yes | DATE bucket on `created_at_utc` |
| 7 | Filters: date range, ticker, outcome, status | Yes | Status filter scope needs clarification per page |
| 8 | `streamlit run dashboard/streamlit_app.py` | Yes | New `dashboard/` package |
| 9 | 5 pages | Yes | st.navigation() or pages/ |
| 10 | Metrics logic separate from dashboard | Yes | `dashboard/metrics.py` pure functions |
| 11 | No /webhook/signal modification | Yes | Dashboard is read-only, no app/ router changes |
| 12 | No Alpaca | Yes | Guaranteed |
| 13 | No orders | Yes | Guaranteed |
| 14 | Unit tests for metrics | Yes | `tests/test_dashboard_metrics.py` with in-memory SQLite |
| 15 | docs/validation/v0.4-validation.md | Yes | |
