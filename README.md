# NCDEX Trading System (Simulation)

Educational simulation of the National Commodity and Derivatives Exchange workflow for Group 100, Academic Year 2026–27.

The target architecture is:

- React + Vite frontend;
- FastAPI backend;
- Neon Postgres operational database;
- PostgreSQL `analytics.*` views for aggregations (no Pandas pipeline);
- Power BI dashboards over read-only `analytics` views.

Kafka from the earlier diagram is intentionally not part of the first implementation scope, matching the final architecture direction supplied for this project.

## Current phase

The schema foundation is in `db/migrations/001_initial_schema.sql`, with historical development seed data in `db/seed.sql` and a separate workflow demo dataset in `db/demo_seed.sql`. Run the migration with the direct connection string (`DATABASE_URL_UNPOOLED`) and seed only a development branch/database.

```bash
psql "$DATABASE_URL_UNPOOLED" -f db/migrations/001_initial_schema.sql
psql "$DATABASE_URL_UNPOOLED" -f db/seed.sql
psql "$DATABASE_URL_UNPOOLED" -f db/demo_seed.sql
psql "$DATABASE_URL_UNPOOLED" -f db/rich_demo_seed.sql
psql "$DATABASE_URL_UNPOOLED" -f db/migrations/002_scd2_history.sql
psql "$DATABASE_URL_UNPOOLED" -f db/migrations/003_scd2_maintenance.sql
psql "$DATABASE_URL_UNPOOLED" -f db/migrations/004_scd2_infinity_dates.sql
psql "$DATABASE_URL_UNPOOLED" -f db/scd_demo_seed.sql
psql "$DATABASE_URL_UNPOOLED" -f db/migrations/005_live_simulation.sql
psql "$DATABASE_URL_UNPOOLED" -f db/persona_seed.sql
```

The application will later use the pooled `DATABASE_URL` from `.env.local`.

Power BI connection instructions are in [docs/POWER_BI.md](docs/POWER_BI.md), and the faculty dashboard plan is in [docs/POWER_BI_DASHBOARDS.md](docs/POWER_BI_DASHBOARDS.md). SCD Type 2 history is implemented in `db/migrations/002_scd2_history.sql` and maintained automatically by `db/migrations/003_scd2_maintenance.sql`.

## Run the application

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
set -a; source ../.env.local; set +a
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

## Live faculty demo

Open **Live simulation** (the default page) and press **Start live demo**. A 14-step scripted scenario plays every ~4.5 s:

1. Opening bell — the NCDEX Liquidity Desk (simulated market maker) quotes five price levels on each side of every contract.
2. Monsoon-deficit news → the textile mill buys cotton at market, consuming offer levels, so the last traded price (LTP) rises.
3. A speculator chases the move; the FPO farmer posts a resting sell limit above the market as a hedge.
4. **SCD2:** the farmer's address changes (new warehouse) — `trader_history` closes the old row (`to_date = now`, `current_flag = N`) and opens a new current row (`to_date = ∞`, `current_flag = Y`).
5. The mill buys again and fills against the farmer's resting offer; the speculator books profit and the price falls back.
6. **SCD2:** the exchange revises the cotton minimum lot (`commodity_history`), and the speculator's risk/KYC tier is upgraded.
7. Jeera and soybean hedges, then rain returns and the farmer sells more.

Each trader quadrant (2 × 2 grid, any participant selectable) glows green/red/purple when that person buys, sells or changes profile, and the rail explains *why* the price moved. **Buy/Sell** buttons on each quadrant place live market orders; the **SCD v… ✎** chip opens the profile editor. **Random market flow** adds continuous background orders and occasional profile changes. **Presenter mode** hides the navigation for projection.

Second device: `npm run dev` binds to the LAN (`vite --host`) and the API listens on `0.0.0.0:8000`, so a phone/tablet on the same Wi-Fi can open `http://<laptop-ip>:5173/#live` (or `#traders`) and see the same state.

The **Traders & SCD2** page shows every participant's physical `trader_history` and `user_history` rows, a cross-dimension change log (`analytics.v_scd_change_log`, with `field: old → new` diffs), and an admin form that versions commodity contract terms.

Every execution also lands in `price_ticks` (with its narrative) and updates today's OHLC row in `market_prices`, so Power BI picks up the simulation on refresh.

## Neon

The project is linked to Neon project `delicate-shape-82090352` in `aws-ap-southeast-1`. `.neon` and `.env.local` are ignored. Project-local Neon skills and an OAuth MCP configuration are included for future schema inspection and branch workflows.
