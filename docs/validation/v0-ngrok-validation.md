# V0 Ngrok Validation

Date: 2026-05-19

## Result

PASS.

## Validated Flow

curl
→ ngrok HTTPS public URL
→ FastAPI local backend
→ POST /webhook/signal
→ Signal validation
→ Risk Engine
→ SQLite persistence

## Evidence

Signal persisted:

```text
ngrok-test-001 | SPY | buy | risk_approved