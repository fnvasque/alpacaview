# Streamlit Community Cloud — Dashboard Deployment

## Overview

Streamlit Community Cloud hosts the alpacaview dashboard for free. The app reads directly from Supabase Postgres via `DATABASE_URL`. No backend execution — the dashboard is read-only.

```
Streamlit Community Cloud
        │
        └── dashboard/streamlit_app.py
                │
                └── DATABASE_URL (Streamlit secret) ──► Supabase Postgres
```

---

## Prerequisites

- [Streamlit account](https://streamlit.io) (free)
- alpacaview repo on GitHub (public)
- Supabase project running (see `free-cloud-runner.md` Steps 1–2)

---

## Step 1 — Connect repo

1. Go to [app.streamlit.io](https://app.streamlit.io) → **New app**
2. Select your GitHub repo
3. Branch: `main`
4. Main file path: `dashboard/streamlit_app.py`
5. Click **Deploy**

---

## Step 2 — Set secrets

1. After deploying, go to your app → **⋮ (menu) → Settings → Secrets**
2. Add secrets in TOML format:

```toml
DATABASE_URL = "postgresql://postgres.<project>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres?sslmode=require"
```

> Note: `DASHBOARD_DB_URL` is optional — `DashboardSettings` automatically falls back to `DATABASE_URL`. You only need to set `DASHBOARD_DB_URL` if you want the dashboard to use a different database than the pipelines.

3. Click **Save** — the app will reboot automatically

---

## Step 3 — Deploy

Community Cloud installs dependencies from `requirements.txt` automatically on each deploy. `psycopg2-binary` is included, so Postgres connectivity works out of the box.

---

## Step 4 — Validate

1. Open the app URL (e.g., `https://yourname-alpacaview-dashboard.streamlit.app`)
2. The **Overview** page should load and show metrics from Supabase
3. Use the sidebar to refresh data or apply filters

---

## Notes

- **Free tier is public**: anyone with the URL can view the dashboard. Do not expose sensitive operational data (no API keys, no credentials visible in the UI).
- **Read-only**: the dashboard only reads from the database — it never writes.
- **Sleep on inactivity**: free Community Cloud apps sleep after ~7 days of no traffic. The app wakes on the next request (takes ~30 seconds).
- **Data freshness**: the dashboard uses `@st.cache_resource` for the engine and `@st.cache_data` for query results. Use the **Clear cache / refresh data** button in the sidebar to force a refresh.

---

## Local run

```bash
streamlit run dashboard/streamlit_app.py
```

The app reads `DASHBOARD_DB_URL` (or `DATABASE_URL`) from `.env`. With no env vars set, it defaults to `sqlite:///./alpacaview.db`.
