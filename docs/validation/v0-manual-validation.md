# V0 Manual Validation

Date: 2026-05-18

## Validated Scenarios

- Valid BUY signal returns risk_approved.
- Duplicate signal returns duplicate_signal.
- Invalid secret returns invalid_secret.
- SELL signal returns unsupported_side.
- Crypto ticker returns unsupported_asset_class.
- Missing ticker returns schema_invalid.
- Kill switch returns kill_switch_active.
- Fourth approved signal of the day returns max_daily_trades_reached.
- Pre-engine rejections are stored in webhook_events.
- Valid signals are stored in signals.
- Risk decisions are stored in risk_decisions.
- Secrets are masked as "***" in webhook_events.

## Result

V0 manual local validation: PASS.

## Notes

V0 does not execute orders.
V0 does not connect to Alpaca.
V0 is ready for automated test validation.