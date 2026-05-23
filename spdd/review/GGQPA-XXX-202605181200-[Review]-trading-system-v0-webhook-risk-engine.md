# SPDD Code Review: Trading System V0 — Webhook Receiver & Risk Engine

## Review Context

- **Prompt**: `spdd/prompt/GGQPA-XXX-202605181200-[Feat]-api-trading-system-v0-webhook-risk-engine.md`
- **Code Scope**: All 30 implementation files under `app/` and `tests/`
- **Review Date**: 2026-05-18

---

## Review Summary (Start Here)

| Dimension      | Status | Findings  | Priority |
|----------------|--------|-----------|----------|
| Requirements   | ✅     | 0 issues  | —        |
| Entities       | ✅     | 1 issue   | Low      |
| Approach       | ✅     | 0 issues  | —        |
| Structure      | ✅     | 0 issues  | —        |
| Operations     | ⚠️     | 3 issues  | Medium   |
| Norms          | ⚠️     | 2 issues  | Medium   |
| Safeguards     | ⚠️     | 1 issue   | Medium   |
| Intent Drift   | ✅     | 1 minor   | Low      |
| Scope Boundary | ✅     | 0 issues  | —        |

**Overall Assessment**: ✅ Ready to Merge

---

## 🔴 Must Review (Critical)

_None._

---

## 🟡 Should Review (Important)

- **Unused import in `signal_repo.py`**: `from decimal import Decimal` is imported but never used — `signal_repo.py:2`
- **`database.py` spec deviation**: Task 4 says `Settings().DATABASE_URL`; code uses `os.environ.get("DATABASE_URL", ...)` directly. This is an intentional design decision (to prevent requiring `WEBHOOK_SECRET` at import time in tests) but the spec doesn't document it. Should update Task 4 in the prompt to reflect this.
- **Safeguard 16 gap in infrastructure failure paths**: Context build failure (Step 7) and decision persist failure (Step 10) roll back the Signal and return 500 — producing neither a `Signal+RiskDecision` pair nor a `WebhookEvent`. Safeguard 16 states "every inbound request produces an audit record". Task 17 point 5 instructs `db.rollback() + log + 500` without creating a `WebhookEvent`, creating a contradiction in the spec. Needs resolution: either update Task 17 to also create a `WebhookEvent(SCHEMA_INVALID/internal_error)` on infrastructure failure, or scope Safeguard 16 to "every inbound request that passes JSON parsing".
- **`decision_repo.py` undocumented `db.flush()`**: Task 12 says "Inserts. No commit." Code also calls `db.flush()` after insert. Not harmful, but undocumented.

---

## 🟢 Informational (Low Risk)

- **`TradingContext.kill_switch_active` has a `= False` default**: Spec defines this as required `bool` with no default. The default allows accidentally omitting the kill switch state. Low risk since `context.py` always passes it explicitly.
- **`models/signal.py` — `decision: Mapped[Optional["RiskDecision"]]`**: Spec says `Mapped["RiskDecision"]`. `Optional` is semantically more accurate for `uselist=False` relationships (signal may not yet have a decision). No functional impact.
- **`main.py` — JSON log formatter produces pseudo-JSON string**: The format string uses `%(message)s` / `%(levelname)s` interpolation, not a proper JSON serializer. Log lines are JSON-like but not parseable JSON objects (e.g., message content could break JSON if it contains quotes). For production, replace with `python-json-logger` or a custom `logging.Formatter` that calls `json.dumps`. Acceptable for V0.
- **`engine.py` — internal helper renamed**: Spec names the deferred helper `_set_deferred`; code names it `_record_deferred`. Cosmetically different, functionally identical.
- **`context.py` — log message format**: Spec says `"pnl_tracking=deferred, v0_no_fills"` as the log message string. Code uses `"pnl_tracking_deferred"` as the event key with `extra` dict. Both communicate the same information.
- **`main.py` — side-effect model import**: `import app.models  # noqa: F401` is the mechanism used to register all ORM models with `Base.metadata` before `init_db()`. This is an implicit technique not described in the spec but is the standard SQLAlchemy pattern.

---

## Detailed Analysis

### Requirements Alignment

**Status**: ✅ Aligned

**Alignment**: The code implements exactly the V0 scope stated in Requirements: webhook receiver, 10-step fail-fast pipeline, Risk Engine simulation, SQLite persistence, structured audit trail via `webhook_events`, and structured responses. No Alpaca integration, no order execution, no live trading.

**Scope Expansion**: None.

**Scope Contraction**: None.

---

### Entities Alignment

**Status**: ✅ Aligned

**Matched Entities**:
- `Signal` — all 17 columns present, `UNIQUE` on `client_signal_id`, `DateTime(timezone=True)` throughout. ✅
- `RiskDecision` — all columns including `is_enforcement_deferred` and nullable `reason_code`. ✅
- `WebhookEvent` — all columns, no FK to signals. ✅
- `KillSwitchState` — singleton with `id: int`, `activated_at_utc`. ✅
- `TradingContext` — frozen Pydantic, all 8 fields, V0 zero defaults. ✅
- `RiskSignalSnapshot` — frozen Pydantic, 6 fields, ORM-isolated. ✅
- `RiskDecisionResult` — frozen Pydantic, 4 fields. ✅

**Entity Drift**:
- `TradingContext.kill_switch_active`: spec defines as required `bool`; code adds `= False` default. Low risk (see 🟢 above).
- `Signal.decision`: spec defines `Mapped["RiskDecision"]`; code uses `Mapped[Optional["RiskDecision"]]`. More correct semantically.

**Unauthorized Entities**: None.

**Conservative Constraint Violations**: None. No unnecessary refactoring of existing structures.

---

### Approach Alignment

**Status**: ✅ Aligned

**Followed Strategies**:
- Fail-fast pipeline with full audit trail — every inbound request writes either a `WebhookEvent` or a `Signal+RiskDecision` pair.
- Pure Risk Engine (`engine.py` imports nothing from `app.models.*`, verified by AST test).
- `RiskSignalSnapshot` isolates engine from ORM.
- `hmac.compare_digest` for constant-time secret comparison.
- `webhook_event_repo.create_event()` commits independently for audit durability.
- `datetime.now(timezone.utc)` everywhere; `ZoneInfo("America/New_York")` for ET boundaries.
- `Decimal` for all financial values.
- `ALLOWED_TICKERS` parsed to uppercase list in `Settings`.

**Approach Drift**: None.

**Unauthorized Decisions**: `database.py` uses `os.environ.get("DATABASE_URL", ...)` instead of `Settings().DATABASE_URL` — a sound architectural decision to prevent requiring `WEBHOOK_SECRET` at module import time, but not captured in the prompt.

---

### Structure Alignment

**Status**: ✅ Aligned

**Matched Structure**:
- Router → Service → Repos + Risk layers — respected throughout.
- `engine.py` depends only on `app.schemas.*` and `app.config`.
- `context.py` depends on `signal_repo` and `kill_switch_repo`.
- `signal_service.py` orchestrates all repos and risk layers.
- `webhook.py` router is thin — only JSON parsing and service delegation.
- `webhook_event_repo.create_event()` commits independently (exception to "caller owns transaction" rule, documented in spec).
- `models/__init__.py` imports all 4 models, enabling `Base.metadata.create_all`.

**Structure Drift**: None.

**Layer Violations**: None.

---

### Operations Alignment

**Status**: ⚠️ Partial Drift

All 22 operations were implemented. Deviations by task:

**Task 4 — `database.py`**:
- **Deviation**: Spec says engine from `Settings().DATABASE_URL`; code uses `os.environ.get("DATABASE_URL", ...)`. Intentional — avoids requiring `WEBHOOK_SECRET` at import time. SQLite `connect_args` is correctly conditioned on `"sqlite" in DATABASE_URL`.
- **Severity**: 🟡

**Task 11 — `signal_repo.py`**:
- `create()`: calls both `db.flush()` and `db.refresh()` — spec only specifies `db.flush()`. Harmless addition.
- **Unused import**: `from decimal import Decimal` imported but unused. 🟡

**Task 12 — `decision_repo.py`**:
- `create_decision()`: calls `db.flush()` after insert — not specified in Task 12 ("Inserts. No commit."). Harmless addition.

**Task 15 — `context.py`**:
- Log message format minor difference (see 🟢 above).

**Task 16 — `engine.py`**:
- Internal helper renamed from spec's `_set_deferred` to `_record_deferred`. Cosmetic.

**Task 17 — `signal_service.py`**:
- Infrastructure failure paths (Step 7 context build, Step 10 persist) do not create a `WebhookEvent` before returning 500. Aligned with Task 17 point 5 instructions but inconsistent with Safeguard 16. See 🟡 above.

**Task 18 — `webhook.py`**:
- Fully aligned. `except Exception` catches all JSON parse failures. Body preview correctly 500-byte limited. ✅

**Task 19 — `main.py`**:
- `_SecretFilter` strips `secret` key from `LogRecord` extra fields. ✅
- JSON formatter format string is pseudo-JSON (see 🟢 above).

**Tasks 20–22 — Tests**:
- All 14 engine tests and 28 webhook tests present. All risk rules covered (enforced + deferred). AST purity test included. `test_stop_after_daily_target_setting_has_no_effect_in_v0` verifies V1/V2 reserved flag is inert. ✅

---

### Norms Alignment

**Status**: ⚠️ Partial Drift

**Followed Norms**:
- All types annotated; no untyped parameters. ✅
- Pydantic v2: `ConfigDict`, `@field_validator` with explicit `mode`. ✅
- SQLAlchemy 2.x: `Mapped[T]` + `mapped_column()`. All `DateTime(timezone=True)`. ✅
- `datetime.now(timezone.utc)` everywhere; no `datetime.utcnow()`. ✅
- `Decimal` for all financial values; no `float`. ✅
- `hmac.compare_digest` for secret comparison. ✅
- `mask_payload()` called before any logging or audit write. ✅
- Structured logging with `extra` dict. ✅
- No `alpaca` in any import or URL. ✅
- In-memory SQLite for all tests; function-scope fixtures. ✅

**Norm Violations**:
- **Unused import**: `from decimal import Decimal` in `signal_repo.py:2` — Norm 2 (typed Python, clean imports). 🟡
- **Log formatter**: The JSON formatter in `main.py` produces string-interpolated output, not `json.dumps()`-based output — Norm 7 (JSON formatter). Functional for V0 but not production-grade. 🟢

---

### Safeguards Alignment

**Status**: ⚠️ Partial Violations

**Respected Safeguards**:
- **Safeguard 1**: Kill switch is first check in `engine.evaluate()`. ✅
- **Safeguard 2**: `STOP_AFTER_DAILY_TARGET` never read by engine. Test `test_stop_after_daily_target_setting_has_no_effect_in_v0` verifies. ✅
- **Safeguard 3**: "signal proceeds to execution" absent from all code, comments, log messages, and responses. Test `test_approved_true_message_no_execution_language` verifies. ✅
- **Safeguard 4**: `hmac.compare_digest` only. ✅
- **Safeguard 5**: `UNIQUE` constraint on `signals.client_signal_id`. `IntegrityError` caught as race-condition fallback. ✅
- **Safeguard 6**: Auth, schema, side, asset, and duplicate paths write only to `webhook_events`. Tests `test_*_no_signal_created` verify. ✅
- **Safeguard 7**: Duplicate produces exactly one `WebhookEvent`, returns 409. Tests verify 1 Signal, 1 RiskDecision. ✅
- **Safeguard 8**: Invalid JSON creates `WebhookEvent(SCHEMA_INVALID)` with body preview. Test verifies. ✅
- **Safeguard 9**: Deferred decisions: `approved=True`, `is_enforcement_deferred=True`, `reason_code` set. Persisted as `RiskDecision`. ✅
- **Safeguard 10**: SELL → `WebhookEvent(UNSUPPORTED_SIDE)` + 422. Test verifies. ✅
- **Safeguard 11**: Crypto (`/` in ticker) → `WebhookEvent(UNSUPPORTED_ASSET_CLASS)` + 422. Test verifies. ✅
- **Safeguard 12**: No `float(` in `risk/` or `services/`. All financial values use `Decimal`. ✅
- **Safeguard 13**: No `alpaca` in any import or URL. ✅
- **Safeguard 14**: All ORM columns use `DateTime(timezone=True)`. All defaults use `datetime.now(timezone.utc)`. ✅
- **Safeguard 15**: `engine.py` has no ORM imports. AST test verifies. ✅
- **Safeguard 17**: All 6 risk rules have tests. ✅

**Violations**:
- 🟡 **Safeguard 16 — Partial gap**: "Every inbound request produces an audit record" is not fully honored in infrastructure failure paths (context build failure at Step 7, decision persist failure at Step 10). Both paths call `db.rollback()` and return 500 without creating a `WebhookEvent`. These are rare infrastructure failures (DB errors mid-request), not business-logic rejections. The behavior is consistent with Task 17 point 5 instructions but contradicts the letter of Safeguard 16. Resolution options:
  1. Update Safeguard 16 to scope it to "every inbound request that passes JSON parsing and reaches the service layer without infrastructure failure".
  2. Add a `WebhookEvent(event_type=SCHEMA_INVALID, reason_code=SCHEMA_INVALID, reason_detail="internal_error")` creation step in the infrastructure failure handlers.

---

## Intent Drift Analysis

### Positive Drift (Unauthorized Additions)

| Finding | Severity | Location | Description |
|---------|----------|----------|-------------|
| Extra `db.flush()` in `decision_repo` | 🟢 | `decision_repo.py:20` | `create_decision()` calls `db.flush()` after insert; spec says "Inserts. No commit." Only. Not harmful. |
| Extra `db.refresh()` in `signal_repo` | 🟢 | `signal_repo.py:23` | `create()` calls `db.refresh(signal)` after `db.flush()`. Ensures ID is populated before return. Not harmful. |
| `_SecretFilter` logging filter | 🟢 | `main.py:10-16` | Added to strip `secret` key from log records. Not specified in Task 19 but aligns with Norm 7 and Safeguard intent. |

### Negative Drift (Missing Implementations)

| Finding | Severity | Location | Description |
|---------|----------|----------|-------------|
| No `WebhookEvent` on infrastructure failures | 🟡 | `signal_service.py:219,243` | Task 17 says log+500 on exceptions; Safeguard 16 says all requests produce audit records. The two instructions conflict. |

### Direction Drift (Divergent Approaches)

| Finding | Severity | Location | Description |
|---------|----------|----------|-------------|
| `database.py` — env var vs Settings | 🟡 | `database.py:7` | Expected: `Settings().DATABASE_URL`; Actual: `os.environ.get("DATABASE_URL", ...)`. Intentional design decision for test isolation. |

---

## Implicit Decisions (AI Judgment Points)

| Decision | Category | Location | AI's Choice | Risk |
|----------|----------|----------|-------------|------|
| `os.environ.get()` for DATABASE_URL | Architecture | `database.py:7` | Avoids requiring `WEBHOOK_SECRET` at import time; test `get_db` override is simpler. | Low |
| `kill_switch_active: bool = False` default | Schema | `schemas/risk.py:23` | Added default to allow easier test construction; spec defines it as required. | Low |
| `decision: Mapped[Optional["RiskDecision"]]` | ORM | `models/signal.py:45` | Added `Optional` for semantically accurate `uselist=False` relationship. | Low |
| JSON log formatter via format string | Logging | `main.py:25-30` | Used Python format string interpolation rather than a true JSON serializer. Produces readable but not strictly valid JSON logs. | Low (V0) |
| `_record_deferred` vs `_set_deferred` | Naming | `risk/engine.py:94` | Named internal helper `_record_deferred` instead of spec's `_set_deferred`. | Low |
| `db.refresh()` after `db.flush()` in `signal_repo` | Repository | `signal_repo.py:23` | Ensures SQLAlchemy returns server-generated values; safe addition. | Low |
| `import app.models` in `main.py` | Architecture | `main.py:7` | Side-effect import to register ORM models with `Base.metadata` before `init_db()`. Standard SQLAlchemy pattern; not described in spec. | Low |

---

## Scope Boundary Check

**Status**: ✅ Within Scope

**In-Scope Components**: 30 files — all within `app/` and `tests/`. No existing files outside the project's initial scaffolding were modified.

**Boundary Crossings**: None.

---

## Recommended Actions

1. **Update Task 4 in the prompt** to document the `os.environ.get("DATABASE_URL", ...)` approach and its rationale (avoids `WEBHOOK_SECRET` requirement at import time; enables clean test `get_db` override). Mark as an accepted architectural decision.

2. **Resolve Safeguard 16 vs Task 17 contradiction** — choose one of:
   - Scope Safeguard 16 to: "Every inbound request that passes JSON parsing produces an audit record (WebhookEvent or Signal+RiskDecision). Infrastructure failures (DB errors) are logged with full traceback."
   - Or update Task 17 point 5 to create a `WebhookEvent` on infrastructure failures before returning 500.

3. **Remove unused import** in `signal_repo.py:2`: `from decimal import Decimal`.

4. **For V1** — replace the pseudo-JSON log formatter in `main.py` with a real JSON-serializing formatter (e.g., `python-json-logger`). Not blocking for V0.

5. **No prompt update needed** for the remaining 🟢 informational findings. They represent sound judgment calls by the generator.
