# Operations & Deployment

## Development Setup

### Prerequisites
- Python 3.9+
- pip/poetry for dependency management
- SQLite (included in Python)
- pytest for testing

### Local Development
1. Clone repository
2. Create virtual environment
3. Install dependencies
4. Set environment variables (.env file, local only)
5. Run tests: `pytest`
6. Start server: `uvicorn main:app --reload`

### Required Environment Variables
- `TRADINGVIEW_SECRET` - Shared secret for webhook authentication
- `DATABASE_URL` - SQLite or PostgreSQL connection string
- `LOG_LEVEL` - Logging verbosity (DEBUG, INFO, WARNING, ERROR)
- `KILL_SWITCH` - Boolean to enable/disable trading globally

## Deployment (Future)

### V1 Deployment
- Docker containerization
- CI/CD pipeline (GitHub Actions)
- Staging environment for testing
- Monitoring and alerting
- Secrets management (Vault or similar)

### Production Checklist
- All tests passing
- Code review completed
- Risk rules verified in staging
- Monitoring configured
- Rollback plan documented

## Monitoring & Observability

### Metrics to Track
- Signal received count (per endpoint)
- Signal validation failures (by reason)
- Risk Engine rejections (by limit)
- Idempotency hits (duplicate detection)
- Response latency (webhook to response)
- Database performance

### Logs to Review
- All rejected signals (audit trail)
- Risk Engine decisions (decision log)
- System errors and exceptions
- Performance anomalies

### Alerts to Set Up
- High webhook error rate
- Risk Engine latency spike
- Database connection failures
- Unexpected rejections
- Kill switch activated

## Operational Procedures

### Adding New Risk Limits
1. Update risk-policy.md
2. Implement limit in Risk Engine
3. Add unit tests for new limit
4. Add integration tests with sample signals
5. Document decision in CLAUDE.md

### Responding to Kill Switch
- Kill switch can be toggled via API or config
- Logs which user triggered it
- All trading halted immediately
- Manual review before re-enabling

### Incident Response
- Review logs of rejected signals
- Check Risk Engine decisions
- Verify database state
- Audit trail of all signals
