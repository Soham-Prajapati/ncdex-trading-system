# NCDEX Trading System (Simulation)

Educational simulation of the National Commodity and Derivatives Exchange workflow for Group 100, Academic Year 2026–27.

The target architecture is:

- React + Vite frontend;
- FastAPI backend;
- Neon Postgres operational database;
- Python/Pandas analytics pipeline;
- Power BI dashboards over read-only `analytics` views.

Kafka from the earlier diagram is intentionally not part of the first implementation scope, matching the final architecture direction supplied for this project.

## Current phase

The schema foundation is in `db/migrations/001_initial_schema.sql`, with historical development seed data in `db/seed.sql` and a separate workflow demo dataset in `db/demo_seed.sql`. Run the migration with the direct connection string (`DATABASE_URL_UNPOOLED`) and seed only a development branch/database.

```bash
psql "$DATABASE_URL_UNPOOLED" -f db/migrations/001_initial_schema.sql
psql "$DATABASE_URL_UNPOOLED" -f db/seed.sql
psql "$DATABASE_URL_UNPOOLED" -f db/demo_seed.sql
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
uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

## Neon

The project is linked to Neon project `delicate-shape-82090352` in `aws-ap-southeast-1`. `.neon` and `.env.local` are ignored. Project-local Neon skills and an OAuth MCP configuration are included for future schema inspection and branch workflows.
