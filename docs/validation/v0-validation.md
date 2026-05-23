# V0 Validation

## Scope

V0 validates signal ingestion and risk simulation only.

No Alpaca.
No orders.
No live trading.
No position sizing.
No fills.

## Validated flows

- Local `/webhook/signal`
- Public ngrok `/webhook/signal`
- Resend inbound `/integrations/resend/inbound`
- Manual email → Resend → Backend
- Duplicate detection
- Invalid secret
- Unsupported side
- Unsupported asset class
- Kill switch
- Max daily trades

## Result

V0 direct webhook local: PASS  
V0 ngrok public endpoint: PASS  
V0 Resend manual email adapter: PASS  

## Known constraints

- BUY only
- Stocks/ETFs only
- Allowlist: SPY, QQQ, AAPL, MSFT, NVDA
- SQLite local
- No execution
- No broker integration