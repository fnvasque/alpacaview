# Risk Policy & Limits

## Position Sizing
- Max risk per trade: **0.35% of equity**
- Calculated as: (entry - stop_loss) * quantity / equity

## Daily Limits
- Max daily loss: **0.75% of equity**
- Max trades per day: **3**
- Stop trading after **2 consecutive losing trades**
- Stop trading after **reaching daily target**

## Weekly Limits
- Max weekly loss: **2.5% of equity**
- Reset at start of trading week

## Order Requirements
- **Every order must have a stop loss**
- **Every order must have a take profit**
- Client order ID required (deduplication at Alpaca level)

## Kill Switch
- Global override that halts all trading
- Must be checked before any execution
- Can be toggled via API endpoint or config

## Risk Engine Responsibility
- Evaluate every signal against all limits before approval
- Reject signals that exceed limits
- Store rejection reason for audit
- Maintain daily/weekly running totals
- Check kill switch status
