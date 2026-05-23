# SPDD Analysis: Resend Inbound Email Adapter

## Original Business Requirement

Agrega un adaptador Resend Inbound para recibir emails de TradingView.

Contexto:
V0 ya tiene signal_service.process_raw_payload(raw_payload, db, settings).
No quiero duplicar lógica de validación.
No quiero tocar /webhook/signal salvo que sea necesario.

Crear endpoint:
POST /integrations/resend/inbound

Flujo:
1. Recibir webhook de Resend.
2. Validar que event type sea email.received.
3. Extraer email_id desde el evento.
4. Llamar a la Resend Receiving API usando RESEND_API_KEY para obtener el contenido del email.
5. Extraer el primer bloque JSON del texto plano o HTML del email.
6. Parsear ese JSON.
7. Llamar internamente a signal_service.process_raw_payload(raw_payload, db, settings).
8. Retornar la respuesta de process_raw_payload.

Agregar settings:
- RESEND_API_KEY
- RESEND_RECEIVING_ENABLED=true
- RESEND_WEBHOOK_SECRET opcional para una versión posterior

Crear:
- app/routers/resend_inbound.py
- app/services/resend_inbound_service.py
- app/integrations/resend_client.py
- tests/test_resend_inbound.py

Reglas:
- No Alpaca.
- No órdenes.
- No execution.
- No loguear secrets.
- Si no encuentra JSON en el email, retornar 422.
- Si Resend no puede obtener el contenido, retornar 502.

---

## Domain Concept Identification

### Existing Concepts (from codebase)

- **signal_service.process_raw_payload**: The authoritative signal processing pipeline — validates secret, schema, side, asset class, idempotency, then runs the Risk Engine and persists a Signal + RiskDecision. Returns `(WebhookResponse, http_status_code)`. This is the single entry point all adapters must converge on.
- **Settings** (`app/config.py`): Pydantic `BaseSettings` loaded from `.env`. All configuration lives here. New settings (`RESEND_API_KEY`, `RESEND_RECEIVING_ENABLED`, `RESEND_WEBHOOK_SECRET`) must be added here.
- **WebhookResponse**: The unified response model returned by `process_raw_payload`. The Resend adapter will surface this directly to the caller.
- **webhook router** (`app/routers/webhook.py`): The established thin-router pattern — parses body, delegates to the service layer, returns a `Response` with the serialized result. The Resend router must follow this same pattern.
- **mask_payload / webhook_event_repo**: Existing secret-masking utilities. Any log or DB write involving the raw Resend payload or the API key must use these or equivalent mechanisms.

### New Concepts Required

- **ResendInboundEvent**: The webhook payload delivered by Resend to `POST /integrations/resend/inbound`. Contains at minimum an `event_type` discriminator and an identifier (`email_id` or equivalent) for fetching the email content. This is a new inbound schema, specific to the Resend integration.
- **ResendEmailContent**: The email object returned by the Resend Receiving API when fetched by `email_id`. Contains a plain-text body and/or an HTML body. This is a read-only DTO used only inside the adapter.
- **ResendClient** (`app/integrations/resend_client.py`): An HTTP adapter that encapsulates all communication with the Resend Receiving API. Owns the `RESEND_API_KEY` usage, timeout policy, and HTTP error mapping (e.g., non-2xx → 502). Isolates the external dependency from the service layer.
- **ResendInboundService** (`app/services/resend_inbound_service.py`): Owns the Resend-specific orchestration logic: validate event type, call `ResendClient`, extract the first JSON block from the email body, parse it as a `dict`, then delegate to `signal_service.process_raw_payload`. Contains no trading logic.
- **ResendInboundRouter** (`app/routers/resend_inbound.py`): A thin FastAPI router following the existing `webhook.py` pattern. Receives the HTTP request, delegates to `ResendInboundService`, returns a serialized `Response`.
- **integrations/ directory** (`app/integrations/`): A new package boundary for third-party API clients. Currently absent from the codebase — this feature introduces it.

### Key Business Rules

- **No validation duplication**: All signal validation (secret, schema, side, asset class, idempotency, risk) lives exclusively in `signal_service.process_raw_payload`. The Resend adapter must not replicate any of these checks.
- **Feature flag enforcement**: When `RESEND_RECEIVING_ENABLED=false`, the endpoint must be disabled and must not process any signals.
- **JSON extraction gate**: If no JSON block can be extracted from the email body (plain text or HTML), return 422 — do not attempt to call `process_raw_payload` with empty or malformed data.
- **External API failure gate**: If the Resend API is unreachable or returns an error, return 502 — do not attempt JSON extraction or signal processing.
- **No secrets in logs**: `RESEND_API_KEY` must never appear in structured logs or DB records. This extends the existing `_SecretFilter` / `mask_payload` discipline to the new integration layer.
- **No Alpaca, no orders, no execution**: The adapter is a pure signal intake path. It must not touch any execution or order-related code, consistent with V0 scope.
- **Event type gate**: Only `email.received` events are accepted. Any other event type must be rejected with a 422 before fetching the email.
- **Signal `secret` field implicit requirement**: The JSON extracted from the email must contain the `secret` field for `process_raw_payload` to pass Step 1 (HMAC comparison). This is implicit — TradingView alert configuration must include the secret in the email body.

---

## Strategic Approach

### Solution Direction

- Introduce a new integration package (`app/integrations/`) to house third-party HTTP clients. `ResendClient` lives there, wrapping `httpx` (already in `requirements.txt`) with Resend-specific behavior.
- `ResendInboundService` orchestrates the Resend-specific steps (event validation, email fetch, JSON extraction) and converges on `signal_service.process_raw_payload` as the single processing pipeline. No trading logic belongs in the service.
- `ResendInboundRouter` follows the exact pattern of `app/routers/webhook.py`: thin, async, parses body, delegates to service, returns serialized `Response`.
- `main.py` must be updated to register the new router (it currently only registers `webhook.router`).
- The feature flag `RESEND_RECEIVING_ENABLED` is checked at the router or service entry point. If `False`, return an appropriate non-2xx response without calling the pipeline.

### Key Design Decisions

- **Where to check the feature flag**: Router-level vs. service-level.
  - Router-level: simpler, early exit before any DB or external calls; consistent with the thin-router pattern.
  - Service-level: more testable in isolation.
  - → **Recommendation**: check in the service entry method so the router stays thin and the flag behavior is testable without a full HTTP stack.

- **How to make `ResendClient` testable**: Inject `ResendClient` as a dependency vs. instantiate inside the service.
  - Dependency injection (FastAPI `Depends`): aligns with the existing `get_db` / `get_settings` pattern; easy to mock in tests.
  - Direct instantiation: simpler for a single-use client.
  - → **Recommendation**: Inject `ResendClient` via FastAPI `Depends` so tests can swap it with a mock without patching. Follow the `get_settings` precedent.

- **JSON extraction strategy**: Plain-text first vs. HTML-first vs. try-both.
  - TradingView email alerts are plain text by default. The plain-text body is the primary extraction target.
  - HTML body may contain embedded JSON in `<script>` tags or other structures — scanning raw HTML for JSON blocks risks false positives.
  - → **Recommendation**: Attempt plain-text extraction first. If not found, strip HTML tags and attempt extraction on the resulting text. Raise 422 if both fail.

- **Error surface for unsupported event types**: 422 vs. 200 (accept-and-ignore).
  - Resend may send other event types (e.g., delivery, open) to the same endpoint in the future.
  - 422 makes the unsupported type visible as a configuration issue.
  - 200 silently discards, preventing Resend retry loops.
  - → **Recommendation**: Return 422 for now (consistent with requirement). If retry noise becomes an issue, revisit in a later version.

### Alternatives Considered

- **Embed Resend logic inside `webhook.py`**: Rejected — would violate the single-responsibility principle and force changes to a stable, tested module. The requirement explicitly forbids touching `/webhook/signal`.
- **Parse email at the router layer**: Rejected — business logic (event type validation, email fetch, JSON extraction) does not belong in route handlers. The existing pattern keeps handlers thin.
- **Use `requests` instead of `httpx`**: Rejected — `httpx` is already in `requirements.txt` and supports both sync and async calls; no new dependency needed.

---

## Risk & Gap Analysis

### Requirement Ambiguities

- **Resend webhook payload shape**: The requirement references `email_id` but does not specify the exact JSON structure of Resend's inbound webhook event. The Resend Receiving API sends a `type` field with the event name and a `data` or `email` sub-object. The exact field paths for `event_type` and `email_id` must be confirmed against the Resend documentation before coding the schema.
- **Resend email fetch endpoint**: The requirement says "Llamar a la Resend Receiving API" but does not specify the URL. Based on Resend's public API, this is likely `GET https://api.resend.com/emails/{id}`. This must be confirmed — the URL is not hardcoded in the requirement.

**Resolved decisions (confirmed by user 2026-05-19):**

- **`RESEND_RECEIVING_ENABLED=false` response**: Returns **404 Not Found**. Rationale: the endpoint should behave as if it does not exist when the adapter is disabled, reducing exposed surface area and avoiding revealing inactive integrations.
- **`RESEND_API_KEY` optionality**: `Optional[str] = None`. Resend is an optional adapter — the app must continue working with `/webhook/signal` even if Resend is not configured. Startup must not fail if the key is absent.
- **`RESEND_WEBHOOK_SECRET`**: `Optional[str] = None`. Field added to `Settings` now for forward compatibility; no enforcement logic in V0.

Authoritative Settings defaults:
```python
RESEND_RECEIVING_ENABLED: bool = False
RESEND_API_KEY: Optional[str] = None
RESEND_WEBHOOK_SECRET: Optional[str] = None
```

Full response matrix for the Resend endpoint:
| Condition | HTTP Status |
|-----------|-------------|
| `RESEND_RECEIVING_ENABLED=false` | 404 Not Found |
| `RESEND_RECEIVING_ENABLED=true`, `RESEND_API_KEY` missing | 503 Service Unavailable (`reason_code="resend_not_configured"`) |
| `RESEND_RECEIVING_ENABLED=true`, `event_type != email.received` | 200 OK (ignored) |
| `RESEND_RECEIVING_ENABLED=true`, Resend API unreachable/error | 502 Bad Gateway |
| `RESEND_RECEIVING_ENABLED=true`, no JSON in email | 422 Unprocessable Entity |
| `RESEND_RECEIVING_ENABLED=true`, JSON extracted successfully | Delegates to `process_raw_payload` → returns its response as-is |

### Edge Cases

- **Email with multiple JSON blocks**: The requirement says "first JSON block." This is well-defined for plain text (first complete `{...}` block). For HTML-stripped text, the order may differ from what the sender intended. The extraction logic must be deterministic.
- **Malformed JSON block**: A JSON block found in the email but failing `json.loads()` — the requirement covers "no JSON found" (422) but not "malformed JSON found." Should this also be a 422? Treating parse failure as a 422 is the most consistent interpretation.
- **`process_raw_payload` returns 401 (bad secret)**: The email JSON may not contain the `secret` field, or it may be wrong. `process_raw_payload` handles this correctly and returns 401. The Resend adapter should surface this response as-is.
- **Empty email body**: Both `text` and `html` fields from Resend may be null or empty. Must be handled before attempting JSON extraction — return 422 if both are empty.
- **Large email body**: TradingView alerts are typically small, but no size limit is specified. The JSON extraction regex should apply to a bounded content length to prevent memory issues.
- **`RESEND_RECEIVING_ENABLED` runtime toggle**: The flag is loaded via `@lru_cache` in `get_settings()`. Changing the env var at runtime won't take effect without restarting the process. This is consistent with how other settings work but should be noted.
- **Resend retries on 5xx**: Resend retries webhook delivery on non-2xx responses. A 502 response (Resend API down) will trigger Resend to retry — which is the desired behavior. A 422 (no JSON) will also trigger retries — this may cause noise if the email is legitimately not a signal. The requirement accepts this trade-off.

### Technical Risks

- **httpx sync vs async**: `signal_service.process_raw_payload` is synchronous. The router is async. The Resend API call is a blocking I/O operation. Using `httpx` in sync mode inside an async route will block the event loop unless run in a thread pool. → Mitigation: use `httpx.AsyncClient` for the Resend API call, keeping the entire path async. If the service layer is kept synchronous, use `asyncio.to_thread` or restructure the service as async.
- **Secret logging via httpx default headers**: `httpx` may log request headers (including `Authorization: Bearer <RESEND_API_KEY>`) if debug-level logging is enabled. → Mitigation: do not enable httpx debug logging; document this constraint in the integration layer.
- **`ResendClient` as a shared dependency**: If instantiated per request via `Depends`, a new `httpx.AsyncClient` is created for each request. For high-frequency use, a shared client with connection pooling would be better. For V0 (low-frequency paper trading), per-request instantiation is acceptable.
- **No authentication on the Resend endpoint in V0**: The requirement explicitly defers `RESEND_WEBHOOK_SECRET` to a later version. This means `POST /integrations/resend/inbound` has no authentication in V0 — any caller can trigger a Resend-flavored request. → Risk: limited in V0 because the signal pipeline still requires a valid `secret` in the extracted JSON. The exposure is primarily DDoS/noise, not unauthorized trading.

### Acceptance Criteria Coverage

| AC# | Description | Addressable? | Gaps/Notes |
|-----|-------------|--------------|------------|
| 1 | `POST /integrations/resend/inbound` endpoint exists and receives Resend webhook | Yes | Needs router registration in `main.py` |
| 2 | Reject events where `event_type != email.received` with 422 | Yes | Exact field name in Resend payload must be confirmed |
| 3 | Extract `email_id` from the event and call Resend API | Yes | Resend API URL must be confirmed |
| 4 | Return 502 if Resend API call fails | Yes | Covers HTTP errors and network timeouts |
| 5 | Extract first JSON block from plain text or HTML | Yes | Edge case: malformed JSON needs 422 treatment (see gaps) |
| 6 | Return 422 if no JSON found in email | Yes | Malformed JSON case also needs 422 (requirement is silent on this) |
| 7 | Delegate to `signal_service.process_raw_payload` and return its response | Yes | Signal validation, idempotency, and risk logic fully reused |
| 8 | Add `RESEND_API_KEY`, `RESEND_RECEIVING_ENABLED`, `RESEND_WEBHOOK_SECRET` to Settings | Yes | Resolved: all three are optional with `False`/`None` defaults; no startup failure if unset |
| 9 | Never log `RESEND_API_KEY` or `secret` from email JSON | Yes | Extends existing `_SecretFilter` and `mask_payload` discipline |
| 10 | No Alpaca, no orders, no execution | Yes | Adapter is purely a signal intake path |
| 11 | Tests in `tests/test_resend_inbound.py` covering the full path | Yes | Requires mocking `ResendClient`; test patterns follow existing `conftest.py` fixtures |
