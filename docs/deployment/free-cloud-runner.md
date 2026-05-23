# Free Cloud Runner — GitHub Actions + Supabase

## Overview

```
GitHub Actions (scheduled jobs)
        │
        ├── forward-testing.yml  ──┐
        └── outcome-evaluator.yml ─┤──► Supabase Postgres ◄── Streamlit Community Cloud
                                   │
                            DATABASE_URL (GitHub Secret)
```

Scheduled pipelines run on GitHub's free tier (ubuntu-latest). All writes go to Supabase Postgres. The Streamlit dashboard reads from the same database via `DATABASE_URL`.

---

## Prerequisites

- GitHub account with the alpacaview repo (public or private)
- Supabase account (free tier)
- Repository pushed to GitHub

---

## Step 1 — Create Supabase project

1. Go to [supabase.com](https://supabase.com) → New project
2. Choose a name (e.g., `alpacaview`), region closest to you, and a strong database password
3. Wait for provisioning (~2 minutes)

---

## Step 2 — Get connection string

1. In your project: **Settings → Database → Connection string → URI mode**
2. Copy the URI — it looks like:
   ```
   postgresql://postgres.<project>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
   ```
3. Append `?sslmode=require` at the end:
   ```
   postgresql://postgres.<project>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres?sslmode=require
   ```

---

## Step 3 — Configure GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret**. Add all 5 secrets:

| Secret name | Value |
|---|---|
| `DATABASE_URL` | Full Supabase connection string with `?sslmode=require` |
| `WEBHOOK_SECRET` | Same value as your local `.env` `WEBHOOK_SECRET` |
| `FORWARD_TESTING_ENABLED` | `true` |
| `OUTCOME_EVALUATOR_ENABLED` | `true` |

> `FORWARD_TESTING_BACKEND_URL` is **not** required as a secret — the workflow hardcodes `http://127.0.0.1:8000` and starts FastAPI in the background before running the forward tester.
> `DASHBOARD_DB_URL` is **not** required as a secret — `DashboardSettings` automatically falls back to `DATABASE_URL`.

---

## Step 4 — Initialize DB

Run `init-db.yml` once before the scheduled workflows activate:

1. Go to your repo → **Actions → Init DB → Run workflow**
2. Click **Run workflow** (branch: main)
3. Wait for the job to complete — it creates all 7 tables

> **Alternative**: `forward-testing.yml` starts FastAPI on every run. FastAPI's lifespan calls `init_db()` (idempotent `CREATE TABLE IF NOT EXISTS`), so tables will be created automatically on the first forward-testing run too. `init-db.yml` is most useful for initializing before running the outcome-evaluator in isolation.

---

## Step 5 — Validate tables

1. In Supabase → **Table Editor**
2. Confirm these 7 tables exist:
   - `signals`
   - `webhook_events`
   - `decisions`
   - `kill_switches`
   - `forward_test_runs`
   - `signal_outcomes`
   - *(any additional model tables)*

---

## Step 6 — Test workflows manually

1. **Actions → Forward Testing → Run workflow** — check logs for success
2. **Actions → Outcome Evaluator → Run workflow** — check logs for success
3. **Actions → Health Check → Run workflow** — should print `DB connection OK`

---

## Step 7 — Activate scheduled workflows

GitHub disables scheduled workflows on repos with no recent activity. To activate:

- Push any commit to main, **or**
- Trigger a manual run via `workflow_dispatch` (you already did this in Step 6)

Workflows will then run on schedule (`*/15 * * * *` — every 15 minutes).

---

## Step 8 — Monitor

- **GitHub** → Actions → workflow run history (success/failure per run)
- **Supabase** → Table Editor → row counts in `forward_test_runs` and `signal_outcomes`
- **Supabase** → Logs → Postgres query logs (advanced)

---

## Local development

When `DATABASE_URL` is not set in your local `.env`, all tools fall back to `sqlite:///./alpacaview.db`. No changes to your local setup are required.

To test Postgres locally, add to `.env`:
```
DATABASE_URL=postgresql://postgres.<project>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres?sslmode=require
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `connection refused` or SSL error | Missing `?sslmode=require` | Append `?sslmode=require` to `DATABASE_URL` |
| Job exits 0 with no data written | `ENABLED=false` or secret not set | Set `FORWARD_TESTING_ENABLED=true` and `OUTCOME_EVALUATOR_ENABLED=true` in GitHub Secrets |
| `no such table` | Tables not created | Run `init-db.yml` via workflow_dispatch |
| `--send` connection error | Backend not publicly accessible | Use `--dry-run` in `forward-testing.yml` run step instead of `--send` |
| Workflow not running on schedule | GitHub auto-disabled due to inactivity | Trigger once manually via workflow_dispatch |
