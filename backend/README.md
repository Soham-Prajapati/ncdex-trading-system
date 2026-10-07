# FastAPI backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
set -a; source ../.env.local; set +a
uvicorn app.main:app --reload --port 8000
```

The API uses the pooled `DATABASE_URL` for application traffic. Migrations use `DATABASE_URL_UNPOOLED`.

