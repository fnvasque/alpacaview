#!/bin/zsh

PROJECT_DIR="/Users/felipevasquez/Documents/Claude/alpacaview"
LOG_FILE="$PROJECT_DIR/logs/forward_testing.log"

{
  echo ""
  echo "===== FORWARD TESTING START $(date) ====="
  cd "$PROJECT_DIR" || exit 1
  echo "pwd=$(pwd)"
  echo "python=$PROJECT_DIR/.venv/bin/python"

  "$PROJECT_DIR/.venv/bin/python" -m src.forward_testing.cli \
    --once \
    --tickers SPY,QQQ,AAPL,MSFT,NVDA \
    --timeframe 15m \
    --period 5d \
    --send \
    --market-hours-only

  EXIT_CODE=$?
  echo "exit_code=$EXIT_CODE"
  echo "===== FORWARD TESTING END $(date) ====="
  exit $EXIT_CODE
} >> "$LOG_FILE" 2>&1
