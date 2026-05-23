#!/bin/zsh

PROJECT_DIR="/Users/felipevasquez/Documents/Claude/alpacaview"
LOG_FILE="$PROJECT_DIR/logs/outcome_evaluator.log"

{
  echo ""
  echo "===== OUTCOME EVALUATOR START $(date) ====="
  cd "$PROJECT_DIR" || exit 1
  echo "pwd=$(pwd)"
  echo "python=$PROJECT_DIR/.venv/bin/python"

  "$PROJECT_DIR/.venv/bin/python" -m src.outcome_evaluator.cli \
    --once \
    --tickers SPY,QQQ,AAPL,MSFT,NVDA \
    --timeframe 15m \
    --period 5d \
    --lookahead-bars 26

  EXIT_CODE=$?
  echo "exit_code=$EXIT_CODE"
  echo "===== OUTCOME EVALUATOR END $(date) ====="
  exit $EXIT_CODE
} >> "$LOG_FILE" 2>&1
