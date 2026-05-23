# SPDD Analysis: V0.5 — Free Cloud Migration

## Original Business Requirement

Actúa como Senior Python Backend Engineer + DevOps Engineer.

Contexto:
Estoy trabajando en el proyecto alpacaview.

El sistema actual funciona localmente con:
- FastAPI backend
- SQLite local alpacaview.db
- forward testing
- outcome evaluator
- Streamlit dashboard
- Python signal generator
- sin Alpaca
- sin órdenes reales
- sin ejecución de dinero real

Decisión:
Quiero migrarlo a una arquitectura gratuita usando:
- GitHub Actions en repo público como scheduler
- Supabase Free como Postgres
- Streamlit Community Cloud para dashboard

Objetivo V0.5:
Migrar el sistema a Free Cloud Runner.

Restricciones:
- No agregar Alpaca.
- No crear órdenes.
- No ejecución real.
- No subir .env al repo.
- No subir alpacaview.db al repo.
- No subir logs al repo.
- Mantener compatibilidad local.
- Mantener SQLite local opcional para desarrollo si DATABASE_URL no está configurado.
- Agregar soporte Postgres vía DATABASE_URL.
- Todas las ejecuciones programadas deben funcionar desde GitHub Actions.
- Las credenciales deben usarse mediante GitHub Secrets.
- No hacer commit todavía.

Requisitos:

1. Base de datos
- Agregar soporte a Postgres usando DATABASE_URL.
- Mantener SQLite local si DATABASE_URL no está configurado.
- Crear script o comando de inicialización de DB para Postgres.
- Asegurar compatibilidad de tipos entre SQLite y Postgres.
- Revisar modelos SQLAlchemy actuales.
- Ajustar queries del dashboard si dependen de SQLite.
- Asegurar que forward_test_runs y signal_outcomes funcionen en Postgres.

2. GitHub Actions
Crear:
- .github/workflows/forward-testing.yml
- .github/workflows/outcome-evaluator.yml
- .github/workflows/init-db.yml opcional/manual
- .github/workflows/health-check.yml opcional

forward-testing.yml:
- workflow_dispatch manual
- schedule cada 15 minutos
- instalar dependencias
- usar secrets
- ejecutar:
  python -m src.forward_testing.cli --once --tickers SPY,QQQ,AAPL,MSFT,NVDA --timeframe 15m --period 5d --send --market-hours-only

outcome-evaluator.yml:
- workflow_dispatch manual
- schedule cada 15 minutos
- debe ser idempotente
- ejecutar:
  python -m src.outcome_evaluator.cli --once --tickers SPY,QQQ,AAPL,MSFT,NVDA --timeframe 15m --period 5d --lookahead-bars 26

3. Secrets esperados en GitHub
Documentar:
- DATABASE_URL
- DASHBOARD_DB_URL
- WEBHOOK_SECRET
- PYTHON_SIGNAL_GENERATOR_ENABLED
- FORWARD_TESTING_ENABLED
- OUTCOME_EVALUATOR_ENABLED

4. Dashboard
- Streamlit debe leer desde DASHBOARD_DB_URL o DATABASE_URL.
- Preparar despliegue para Streamlit Community Cloud.
- Crear docs/deployment/streamlit-community-cloud.md.

5. Documentación
Crear docs/deployment/free-cloud-runner.md con:
- crear proyecto en Supabase
- obtener connection string de Postgres
- configurar GitHub Secrets
- inicializar DB
- probar workflow manual
- activar scheduled workflows
- desplegar dashboard en Streamlit Community Cloud
- validar tablas
- validar logs de GitHub Actions
- validar dashboard

6. Seguridad
- Revisar .gitignore y asegurar:
  .env
  .venv/
  alpacaview.db
  logs/
  *.log
  __pycache__/
  .pytest_cache/

7. Tests
- Agregar tests para DATABASE_URL.
- Mantener SQLite local funcionando.
- Mantener todos los tests actuales pasando.
- Agregar verificación de no Alpaca / no órdenes.

8. Resultado esperado
Al final muéstrame:
- archivos creados/modificados
- comandos para correr local
- comandos para inicializar Postgres
- comandos para probar workflows manuales
- checklist de validación

Antes de modificar, inspecciona la estructura actual del proyecto.

---

## Domain Concept Identification

### Existing Concepts (from codebase)

- **DATABASE_URL**: Environment variable already read by `app/database.py` (line 7). Defaults to `sqlite:///./alpacaview.db`. The SQLAlchemy engine is created at module level on import, picking up whatever `DATABASE_URL` is in `os.environ` at that moment. The `connect_args={"check_same_thread": False}` guard is already conditioned on `"sqlite" in DATABASE_URL` — Postgres path already handled here.

- **ForwardTestingSettings**: `src/forward_testing/config.py` — owns `FORWARD_TESTING_DB_URL` (defaults to SQLite). The CLI's `_init_db()` already handles sqlite vs non-sqlite via the same `"sqlite" in db_url` guard. Schema creation via `Base.metadata.create_all(bind=engine)` is already called inside `_init_db()`.

- **OutcomeEvaluatorSettings**: `src/outcome_evaluator/config.py` — owns `OUTCOME_EVALUATOR_DB_URL` (defaults to SQLite). Same `_init_db()` pattern as forward testing.

- **DashboardSettings**: `src/reporting/config.py` — owns `DASHBOARD_DB_URL` (defaults to SQLite). Dashboard reads via `get_reporting_engine()` in `src/reporting/db.py`.

- **Base.metadata**: `app/database.py` — all 7 ORM models registered under a single metadata. `Base.metadata.create_all()` creates all tables in one call. Already used in both CLIs for schema initialization.

- **FORWARD_TESTING_ENABLED / OUTCOME_EVALUATOR_ENABLED guards**: Both CLIs have an early-exit guard (`sys.exit(0)`) when their `ENABLED` flag is false. These guards must be bypassed or set to `true` in GitHub Actions environment.

- **FORWARD_TESTING_SECRET / WEBHOOK_SECRET fallback**: `ForwardTestingSettings.resolve_secret()` tries `FORWARD_TESTING_SECRET` first, then `WEBHOOK_SECRET` as fallback. The secret must be present in GitHub Secrets for the forward-testing workflow.

- **SQLAlchemy column types**: All models use `String`, `Boolean`, `DateTime(timezone=True)`, `Integer` — all portable across SQLite and Postgres with no type changes needed.

- **`func.date()` in `compute_daily_evolution`**: `src/reporting/metrics.py` uses `func.date(col).label("d")` grouped by string label `"d"`. SQLAlchemy's `func.date()` calls SQL `DATE()` in SQLite and SQL `date_trunc('day', ...)` equivalent in Postgres. The Python-side `date.fromisoformat(str(row.d))` conversion handles both SQLite (returns string) and Postgres (returns `datetime.date` object).

- **`.cast(Integer)` on boolean expression**: `(ForwardTestRun.status == "risk_rejected").cast(Integer)` in `compute_daily_evolution`. SQLite returns 0/1 for boolean; Postgres supports `CAST(bool AS integer)`. This is portable.

- **`.gitignore`**: Already covers all required entries (`.env`, `*.db`, `alpacaview.db`, `__pycache__/`, `.pytest_cache/`, `.venv/`, `logs/`, `*.log`). Has duplicate blocks but no functional gaps.

- **`app/database.py` module-level engine**: The engine is created immediately on import. This works correctly for Postgres when `DATABASE_URL` is set in the process environment before any import of `app.models` or `app.database`. Both CLIs call `_init_db()` separately (not the module-level engine) so the CLIs are already fully decoupled from the module-level engine.

### New Concepts Required

- **`psycopg2-binary` dependency**: Python Postgres driver. Not present in `requirements.txt`. Required for any Postgres connection. Must be added before deploying to Supabase or GitHub Actions.

- **`DATABASE_URL` fallback in per-tool settings**: Currently each tool has its own DB URL env var with no cross-fallback. For production, a single `DATABASE_URL` pointing to Supabase should serve all tools. Each `BaseSettings` subclass should fall back to `DATABASE_URL` if its own URL is not set. This avoids requiring 4 separate Postgres connection strings as GitHub Secrets.

- **DB initialization command** (`scripts/init_db.py` or similar): A standalone script that imports all ORM models, instantiates an engine from `DATABASE_URL`, and calls `Base.metadata.create_all()`. Used as the body of `init-db.yml` and as a local setup command for Postgres. The CLIs already call `Base.metadata.create_all()` in `_init_db()` — the standalone script is an explicit, operator-visible entry point.

- **GitHub Actions workflows** (4 files, new directory `.github/workflows/`):
  - `forward-testing.yml`: `schedule: cron */15` + `workflow_dispatch`; installs deps; runs CLI with secrets injected as env vars
  - `outcome-evaluator.yml`: same pattern; idempotent by design (existing terminal-outcome guard)
  - `init-db.yml`: `workflow_dispatch` only; runs DB init script once; used for Supabase first-time setup
  - `health-check.yml`: optional; verifies DB connectivity; runs on demand

- **`requirements.txt` Streamlit Community Cloud compatibility**: Streamlit Community Cloud installs packages from `requirements.txt` directly. The file must include `psycopg2-binary` and all current dependencies must be installable on Ubuntu (Community Cloud runner). Already using `streamlit==1.57.0`, `plotly`, `sqlalchemy` — no changes except adding `psycopg2-binary`.

- **Deployment documentation** (`docs/deployment/`):
  - `docs/deployment/free-cloud-runner.md`: Supabase setup + GitHub Secrets + workflow activation + validation checklist
  - `docs/deployment/streamlit-community-cloud.md`: App deployment + secrets configuration + run command

### Key Business Rules

- **No Alpaca, no orders, no real execution**: Must be enforced by the absence of Alpaca imports and order-creation code. V0.5 does not change this boundary. Tests should verify no alpaca package imports.
- **Credential isolation**: `DATABASE_URL` (Postgres with credentials) must never appear in workflow logs, `click.echo()` output, or any committed file.
- **SQLite local parity**: `DATABASE_URL` absent → SQLite default. Must remain true after V0.5 so local development requires no Supabase account.
- **Idempotent schedulers**: Both CLIs are already idempotent (terminal-outcome guard, duplicate-signal deduplication). GitHub Actions retries or overlapping runs must not corrupt data.
- **Enabled-flag gate**: Both CLIs exit silently if `ENABLED=false`. In GitHub Actions, the workflows must set `ENABLED=true` (via secret or hardcoded env). The gate exists to protect against accidental local runs; in Actions, it is a deliberate opt-in.

---

## Strategic Approach

### Solution Direction

- **Add `psycopg2-binary` to `requirements.txt`** as the sole dependency change — all other SQLAlchemy code is already Postgres-compatible.
- **Add `DATABASE_URL` fallback** to each per-tool settings class (`ForwardTestingSettings`, `OutcomeEvaluatorSettings`, `DashboardSettings`) so a single Postgres connection string covers all tools.
- **Create `scripts/init_db.py`** as a minimal, operator-visible DB initialization entry point — wraps the existing `Base.metadata.create_all()` pattern already used in both CLIs.
- **Create 4 GitHub Actions workflow files** under `.github/workflows/`. Each workflow sets required env vars from secrets, installs deps, and runs the CLI command exactly as specified in the requirement.
- **Verify `func.date()` Postgres compatibility** in `compute_daily_evolution` — the analysis shows it is portable, but a targeted test against Postgres is advisable before production.
- **Clean up `.gitignore`** by deduplicating the repeated blocks (functional coverage is already complete).
- **Write deployment documentation** for Supabase + GitHub Actions + Streamlit Community Cloud.
- **Add targeted tests** for Postgres URL detection and no-Alpaca safeguards.

### Key Design Decisions

- **D1 — DATABASE_URL fallback strategy**: Each tool currently reads its own DB URL env var. For cloud deployment, all tools share one Postgres instance. Two options: (a) require operators to set 4 separate Postgres URLs as GitHub Secrets, or (b) add a `DATABASE_URL` fallback in each settings class so a single secret suffices. → **Recommendation: add `DATABASE_URL` as fallback**. Rationale: fewer secrets, less configuration drift, Supabase gives one connection string. Each tool's specific URL remains the override if needed for future multi-DB setups.

- **D2 — Postgres driver**: `psycopg2-binary` vs `psycopg[binary]` (psycopg3). → **Recommendation: `psycopg2-binary`**. Rationale: it's in the Supabase official docs, works with all existing SQLAlchemy sync code, zero migration cost. psycopg3 provides async benefits irrelevant to the synchronous CLI pattern used here.

- **D3 — Enabled-flag handling in workflows**: The `FORWARD_TESTING_ENABLED` and `OUTCOME_EVALUATOR_ENABLED` flags default to `false`. In GitHub Actions, the workflows need these as `true`. Two options: (a) set as GitHub Secrets (operator controls per-env), or (b) hardcode `true` in the workflow YAML env section. → **Recommendation: set as GitHub Secrets** (`FORWARD_TESTING_ENABLED=true`, `OUTCOME_EVALUATOR_ENABLED=true`). Rationale: maintains consistent pattern with other secrets; allows temporarily disabling a workflow without editing YAML; matches the documented secrets list in the requirement.

- **D4 — `init-db.yml` scope**: The CLIs already call `Base.metadata.create_all()` on first run. An explicit `init-db.yml` is redundant for automated runs but required as an operator-visible, documented step in the deployment guide. → **Recommendation: create `init-db.yml` as `workflow_dispatch` only** (no schedule). Runs `scripts/init_db.py` which imports all models and calls `create_all`. Safe to run multiple times (SQLAlchemy's `create_all` is idempotent — skips existing tables).

- **D5 — Supabase SSL requirement**: Supabase Postgres requires SSL. The connection string must include `?sslmode=require` or the engine must pass `connect_args={"sslmode": "require"}`. The current `_init_db()` in both CLIs and `get_reporting_engine()` in `src/reporting/db.py` only add `check_same_thread` for SQLite — they pass empty `connect_args` for non-SQLite. → **Recommendation: document `?sslmode=require` as part of `DATABASE_URL` format in the deployment guide**. Operators include it in the connection string itself rather than requiring code changes. This keeps the code free of Supabase-specific logic.

- **D6 — `func.date()` in Postgres**: `compute_daily_evolution` uses `func.date(col).label("d")` and groups by the string label `"d"`. In Postgres, `GROUP BY "d"` referencing an alias in the SELECT clause works in some contexts but not all — Postgres requires `GROUP BY 1` (positional) or repetition of the expression. SQLAlchemy's `group_by("d")` may not be portable. → **Recommendation: replace `group_by("d")` with `group_by(func.date(col))` (explicit expression)** in `compute_daily_evolution` for both FTR and SO queries. This is the only code change required for Postgres compatibility.

- **D7 — Health check workflow**: Optional but valuable. A simple workflow that connects to Postgres and runs `SELECT 1` confirms secrets are correctly configured. → **Recommendation: create `health-check.yml` as `workflow_dispatch` only**. Lightweight, does not require CLI invocation — just a Python one-liner.

### Alternatives Considered

- **GitHub Actions as the FastAPI host**: Running the FastAPI server on GitHub Actions is not viable — Actions runners are ephemeral (jobs end after workflow completes). The FastAPI server, if needed in the cloud, would require a persistent host. V0.5 only moves the scheduled CLIs (forward-testing, outcome-evaluator) to GitHub Actions, not the server. The FastAPI server remains local only in V0.5.
- **Using `asyncpg` instead of `psycopg2-binary`**: `asyncpg` only works with async SQLAlchemy. All current code is synchronous. Not viable without a larger async migration.
- **Hardcoding `ENABLED=true` in workflow YAML**: Simpler but less flexible — an operator cannot disable a workflow without editing YAML and pushing a commit. Rejected in favor of secrets.
- **Single unified DB URL env var replacing all per-tool URLs**: Would require removing existing env vars that are already documented and potentially in use. The fallback approach is backward-compatible and less disruptive.

---

## Risk & Gap Analysis

### Requirement Ambiguities

- **FastAPI server in V0.5**: The requirement says "all scheduled executions from GitHub Actions" but does not mention the FastAPI server. The server is not a scheduled CLI — it receives webhook requests. V0.5 does not deploy the FastAPI server to the cloud (that would require a persistent host). The analysis assumes V0.5 moves only the CLI schedulers (forward-testing, outcome-evaluator) to GitHub Actions. The FastAPI server continues to run locally.

- **`DASHBOARD_DB_URL` vs `DATABASE_URL`**: The requirement lists both as GitHub Secrets. If both point to the same Supabase instance, this is redundant. The fallback strategy (D1) resolves this — `DASHBOARD_DB_URL` falls back to `DATABASE_URL` if not set, so only `DATABASE_URL` is strictly required in Secrets.

- **GitHub Actions schedule behavior**: GitHub's cron scheduler for public repos can be delayed by up to 15–30 minutes during high-load periods. A `*/15 * * * *` schedule means the forward-testing CLI may run at irregular intervals. The system is already designed to be idempotent and tolerant of timing variation (bar-time is checked per signal, not per run). This is acceptable for a paper-trading system.

- **Streamlit Community Cloud repo visibility**: Community Cloud free tier requires a public GitHub repo. The requirement mentions "repo público" — confirming the repo will be public. All sensitive data must be in Secrets, not committed files. The existing `.gitignore` already covers this.

### Edge Cases

- **First run on fresh Postgres DB**: `Base.metadata.create_all()` is called inside both CLIs' `_init_db()`. A first run of `forward-testing.yml` against a new Supabase DB will create all tables automatically. However, if the forward-testing run fails before `_init_db()` completes, no tables are created. The `init-db.yml` workflow ensures tables are created explicitly before any scheduled run.

- **Concurrent GitHub Actions runs**: GitHub's `*/15 * * * *` schedule can occasionally produce overlapping runs if a run takes longer than 15 minutes. The outcome evaluator's terminal-outcome guard prevents double-writes. The forward-testing runner uses `ForwardTestRun` rows (append-only) — concurrent runs could write duplicate `signal_candidate` rows for the same bar time if deduplication doesn't cover this. The existing `client_signal_id` format (`strategy:version:ticker:timeframe:bar_time:side`) acts as a natural dedup key, but the `forward_test_runs` table has no UNIQUE constraint on `client_signal_id` — only `signal_outcomes` does. → Duplicate `forward_test_runs` rows are possible but harmless for reporting (metrics use `COUNT(DISTINCT client_signal_id)`).

- **Supabase free tier inactivity pause**: Supabase free projects pause after 7 days of inactivity. A `*/15 * * * *` schedule on weekdays keeps the project active. But during long market closures (holidays, weekends), `--market-hours-only` causes the forward-testing workflow to write `skipped_market_closed` rows and exit immediately — which still counts as DB activity. The outcome-evaluator also writes (or skips) — keeping the DB active. No pause risk in practice.

- **yfinance rate limiting in GitHub Actions**: Multiple parallel GitHub Actions workflows hitting Yahoo Finance could be rate-limited. With 5 tickers per run and a 15-minute interval, this is unlikely to trigger rate limits but worth monitoring. Not a V0.5 implementation concern.

- **`func.date()` group by alias portability**: As identified in D6, `group_by("d")` (string alias) may not be Postgres-portable. This is the only query-level code change required.

### Technical Risks

- **`psycopg2-binary` absent from `requirements.txt`**: Without it, any connection to Postgres will raise `ModuleNotFoundError: No module named 'psycopg2'`. This is a hard blocker for all Postgres-connected tools. Must be added before any test against Supabase. **Impact: blocker. Mitigation: add to `requirements.txt` in V0.5.**

- **Module-level engine in `app/database.py`**: The engine is created at import time. In GitHub Actions, `DATABASE_URL` is injected as an env var from secrets — it will be available in `os.environ` before any Python import. However, if the FastAPI `app.database` module is imported in a context where `DATABASE_URL` is not set (e.g., a test without the env var), it falls back to SQLite. This is intentional and already tested. No risk for V0.5.

- **`String` columns for numeric precision values (price, stop_loss, take_profit, pnl_r, etc.)**: All models store numeric values as `String` to preserve decimal precision. Postgres `VARCHAR` (what SQLAlchemy maps `String` to) handles this correctly. No data type migration needed.

- **`DateTime(timezone=True)` on Postgres**: Maps to `TIMESTAMPTZ` in Postgres, which stores UTC correctly. SQLite stores as ISO strings. On Postgres, existing `default=lambda: datetime.now(timezone.utc)` produces timezone-aware datetimes — correct for `TIMESTAMPTZ`. No risk.

- **Connection pooling on Supabase free tier**: Supabase free allows 60 direct connections. SQLAlchemy's default pool size is 5 + 10 overflow = 15 connections per engine. With forward-testing + outcome-evaluator potentially running concurrently on GitHub Actions, plus a Streamlit session, total active connections remain well under 60. No risk for V0.5.

- **Streamlit Community Cloud and `src/` imports**: `dashboard/streamlit_app.py` uses `sys.path.insert(0, PROJECT_ROOT)` for imports. Community Cloud installs the repo at a known path and runs `streamlit run dashboard/streamlit_app.py`. The path bootstrap handles this correctly. No risk.

### Acceptance Criteria Coverage

| AC# | Description | Addressable? | Gaps/Notes |
|-----|-------------|--------------|------------|
| 1 | Postgres support via DATABASE_URL | Yes | `app/database.py` already reads DATABASE_URL; add `psycopg2-binary`; add fallback in per-tool settings |
| 2 | SQLite local default when DATABASE_URL not set | Yes | Already implemented in all settings classes; no change needed |
| 3 | DB initialization script/command | Yes | New `scripts/init_db.py`; `init-db.yml` workflow |
| 4 | SQLite/Postgres type compatibility | Partial | Models already portable; `func.date()` group_by alias in `compute_daily_evolution` requires fix (D6) |
| 5 | forward-testing.yml workflow | Yes | New file; uses `workflow_dispatch` + `schedule: cron '*/15 * * * *'` |
| 6 | outcome-evaluator.yml workflow | Yes | New file; same structure; idempotent by existing design |
| 7 | init-db.yml (optional/manual) | Yes | New file; `workflow_dispatch` only; runs `scripts/init_db.py` |
| 8 | health-check.yml (optional) | Yes | New file; `workflow_dispatch` only; SELECT 1 connectivity check |
| 9 | GitHub Secrets documentation | Yes | In `docs/deployment/free-cloud-runner.md` |
| 10 | Dashboard reads from DASHBOARD_DB_URL or DATABASE_URL | Yes | Add fallback to `DashboardSettings`; document in deployment guide |
| 11 | Streamlit Community Cloud deployment prep | Yes | `docs/deployment/streamlit-community-cloud.md`; `requirements.txt` update |
| 12 | docs/deployment/free-cloud-runner.md | Yes | Full operator guide |
| 13 | .gitignore review and cleanup | Yes | Deduplication; all required entries already present |
| 14 | Tests for DATABASE_URL | Yes | New test verifying Postgres URL detection and engine creation; must not break existing 264 tests |
| 15 | No Alpaca / no orders verification | Yes | Test asserting no alpaca imports in any src/ or app/ file |
| 16 | Credentials not in logs | Yes | Existing `_SecretFilter` in `app/main.py`; CLIs never echo DB URLs; verify in workflow step definitions |
