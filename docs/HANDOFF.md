# NCDEX Trading System — teammate handoff

## Repository

- GitHub: https://github.com/Soham-Prajapati/ncdex-trading-system
- Latest checkpoint: `6e0ab79`
- Neon project: `delicate-shape-82090352`
- Neon region: `aws-ap-southeast-1`

## Current implementation

- PostgreSQL schema is in `db/migrations/001_initial_schema.sql`.
- SCD Type 2 history is in `db/migrations/002_scd2_history.sql` and maintained by `db/migrations/003_scd2_maintenance.sql`.
- Synthetic data seeds are `db/seed.sql`, `db/demo_seed.sql`, and `db/rich_demo_seed.sql`.
- The rich seed currently provides 297 market prices, 70 trades, 69 daily summaries, 140 orders, and 9 portfolio rows.
- FastAPI backend: `backend/app/main.py`.
- React/Vite frontend: `frontend/src/main.jsx` and `frontend/src/styles.css`.

## Run locally

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
set -a; source ../.env.local; set +a
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Power BI

- Semantic model: `NCDEX Trading Analytics`.
- Report: `NCDEX Trading Analytics Report`.
- Report URL: https://app.powerbi.com/groups/82cf6b9e-a1b0-401f-a341-40b1c99117c1/reports/455db239-d0fb-4ee2-836e-c094fd96d94e
- The report is connected to Neon and has `analytics.v_market_prices` loaded with a multi-series price chart.
- Keep exactly one page named `NCDEX Market Overview`.
- Remaining work: add KPI cards, commodity comparison, traded-notional chart, order activity table, portfolio snapshot, and key-insights card; save and refresh the report.

Use `docs/POWER_BI_DASHBOARDS.md` for the intended visual plan.

