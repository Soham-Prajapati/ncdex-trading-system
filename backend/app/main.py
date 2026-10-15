from threading import Lock
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import engine
from .db import connection, fetch_all, fetch_one
from .schemas import (Commodity, CommodityUpdate, MarketPrice, Order, OrderCreate, Overview, ProfileUpdate,
                      SimOrder, Trade)

app = FastAPI(title="NCDEX Trading System API", version="0.2.0")
# The demo is opened from a laptop and a phone/tablet on the same network, so any origin may read it.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

scenario_lock = Lock()
scenario_state = {"next": 0}


def run(fn, *args, **kwargs) -> Any:
    """Run an engine call in one transaction, turning engine rule violations into HTTP 400s."""
    with connection() as conn:
        try:
            with conn.cursor() as cur:
                result = fn(cur, *args, **kwargs)
            conn.commit()
            return result
        except engine.EngineError as exc:
            conn.rollback()
            raise HTTPException(400, str(exc)) from exc


@app.get("/health")
def health() -> dict:
    row = fetch_one("SELECT now() AS database_time")
    return {"status": "ok", "database_time": row["database_time"] if row else None}


@app.get("/api/overview", response_model=Overview)
def overview() -> Overview:
    return fetch_one("""
        SELECT
            (SELECT count(*)::int FROM trades WHERE status IN ('executed', 'settled')) AS total_trades,
            COALESCE((SELECT sum(quantity) FROM trades WHERE status IN ('executed', 'settled')), 0) AS traded_quantity,
            COALESCE((SELECT sum(price * quantity) FROM trades WHERE status IN ('executed', 'settled')), 0) AS traded_notional,
            (SELECT count(*)::int FROM traders WHERE status = 'active' AND NOT is_market_maker) AS active_traders,
            (SELECT count(*)::int FROM commodities WHERE status = 'active') AS listed_commodities,
            COALESCE((SELECT avg(daily_change_pct) FROM analytics.v_market_prices WHERE price_date = (SELECT max(price_date) FROM market_prices)), 0) AS market_change_pct
    """)


@app.get("/api/commodities", response_model=list[Commodity])
def commodities() -> list[dict]:
    return fetch_all("""
        SELECT c.commodity_id, c.symbol, c.name, cat.name AS category_name, c.unit,
               latest.close_price AS current_price, latest.daily_change_pct
        FROM commodities c
        JOIN categories cat ON cat.category_id = c.category_id
        LEFT JOIN LATERAL (
            SELECT close_price, daily_change_pct FROM analytics.v_market_prices
            WHERE commodity_id = c.commodity_id ORDER BY price_date DESC LIMIT 1
        ) latest ON true
        WHERE c.status = 'active'
        ORDER BY c.symbol
    """)


@app.get("/api/market/prices", response_model=list[MarketPrice])
def market_prices(symbol: str | None = None, limit: int = Query(default=100, le=500)) -> list[dict]:
    if symbol:
        return fetch_all("SELECT * FROM analytics.v_market_prices WHERE symbol = %s ORDER BY price_date DESC LIMIT %s",
                         (symbol.upper(), limit))
    return fetch_all("SELECT * FROM analytics.v_market_prices ORDER BY price_date DESC, symbol LIMIT %s", (limit,))


@app.get("/api/market/summary")
def market_summary(limit: int = Query(default=30, le=200)) -> list[dict]:
    return fetch_all("SELECT * FROM analytics.v_daily_market_summary ORDER BY trade_date DESC, symbol LIMIT %s", (limit,))


@app.get("/api/orders", response_model=list[Order])
def orders(limit: int = Query(default=30, le=200)) -> list[dict]:
    return fetch_all("""
        SELECT a.* FROM analytics.v_order_activity a
        WHERE a.email <> 'liquidity@ncdex-sim.local'
        ORDER BY a.submitted_at DESC LIMIT %s
    """, (limit,))


@app.get("/api/trades", response_model=list[Trade])
def trades(limit: int = Query(default=50, le=200)) -> list[dict]:
    return fetch_all("SELECT * FROM analytics.v_trade_facts ORDER BY trade_time DESC LIMIT %s", (limit,))


@app.get("/api/portfolio/{email}")
def portfolio(email: str) -> list[dict]:
    return fetch_all("SELECT * FROM analytics.v_portfolio_snapshot WHERE email = %s ORDER BY current_value DESC", (email,))


@app.post("/api/orders", response_model=Order, status_code=201)
def submit_order(payload: OrderCreate) -> dict:
    def go(cur):
        trader = engine.get_trader(cur, email=payload.trader_email)
        return engine.place_order(cur, trader["trader_id"], payload.symbol, payload.side, payload.order_type,
                                  payload.quantity, payload.price)
    result = run(go)
    return fetch_one("SELECT * FROM analytics.v_order_activity WHERE order_id = %s", (result["order_id"],))


# --- traders & SCD2 ------------------------------------------------------------------

@app.get("/api/traders")
def traders() -> list[dict]:
    return fetch_all("""
        SELECT p.*, u.full_name, u.phone, t.avatar_color, t.is_persona, b.name AS broker_name, t.broker_id
        FROM analytics.v_trader_profiles p
        JOIN traders t ON t.trader_id = p.trader_id
        JOIN users u ON u.user_id = t.user_id
        LEFT JOIN brokers b ON b.broker_id = t.broker_id
        ORDER BY t.is_market_maker, NOT t.is_persona, p.trader_name
    """)


@app.get("/api/brokers")
def brokers() -> list[dict]:
    return fetch_all("SELECT broker_id, name FROM brokers ORDER BY name")


@app.patch("/api/traders/{trader_id}")
def update_trader(trader_id: UUID, payload: ProfileUpdate) -> dict:
    changes = payload.model_dump(exclude_none=True, exclude={"reason"})
    if "broker_id" in changes:
        changes["broker_id"] = str(changes["broker_id"])
    return run(engine.update_trader_profile, trader_id, changes, payload.reason)


@app.get("/api/traders/{trader_id}/history")
def trader_history(trader_id: UUID) -> dict:
    profile = fetch_all("SELECT * FROM analytics.v_trader_history WHERE trader_id = %s ORDER BY valid_from", (trader_id,))
    account = fetch_all("""
        SELECT h.* FROM analytics.v_user_history h JOIN traders t ON t.user_id = h.user_id
        WHERE t.trader_id = %s ORDER BY h.valid_from
    """, (trader_id,))
    changes = fetch_all("""
        SELECT l.* FROM analytics.v_scd_change_log l
        WHERE l.entity_id = %s OR l.entity_id = (SELECT user_id FROM traders WHERE trader_id = %s)
        ORDER BY l.from_date DESC
    """, (trader_id, trader_id))
    return {"profile_versions": profile, "account_versions": account, "changes": changes}


@app.patch("/api/commodities/{symbol}")
def update_commodity(symbol: str, payload: CommodityUpdate) -> dict:
    return run(engine.update_commodity, symbol, payload.model_dump(exclude_none=True, exclude={"reason"}), payload.reason)


@app.get("/api/scd")
def scd_log(dimension: str | None = None, limit: int = Query(default=200, le=1000)) -> list[dict]:
    if dimension:
        return fetch_all("SELECT * FROM analytics.v_scd_change_log WHERE dimension = %s ORDER BY from_date DESC LIMIT %s",
                         (dimension, limit))
    return fetch_all("SELECT * FROM analytics.v_scd_change_log ORDER BY from_date DESC LIMIT %s", (limit,))


# --- live simulation -------------------------------------------------------------------

def scenario_status() -> dict:
    nxt = scenario_state["next"]
    steps = engine.SCENARIO
    return {"next": nxt, "total": len(steps), "done": nxt >= len(steps),
            "next_title": steps[nxt]["title"] if nxt < len(steps) else None,
            "steps": [s["title"] for s in steps]}


@app.get("/api/sim/scenario")
def scenario() -> dict:
    return scenario_status()


@app.post("/api/sim/step")
def scenario_step() -> dict:
    with scenario_lock:
        if scenario_state["next"] >= len(engine.SCENARIO):
            scenario_state["next"] = 0
        result = run(engine.run_step, scenario_state["next"])
        scenario_state["next"] += 1
    return {"result": result, "scenario": scenario_status()}


@app.post("/api/sim/restart")
def scenario_restart() -> dict:
    with scenario_lock:
        scenario_state["next"] = 0
    return scenario_status()


@app.post("/api/sim/random")
def random_flow(count: int = Query(default=1, ge=1, le=10)) -> list[dict]:
    return [run(engine.random_action) for _ in range(count)]


@app.post("/api/sim/reset-books")
def reset_books() -> dict:
    run(engine.reset_books)
    return {"status": "ok"}


@app.post("/api/sim/order")
def sim_order(payload: SimOrder) -> dict:
    def go(cur):
        price = payload.price
        if payload.order_type == "limit" and price is None:
            commodity = engine.get_commodity(cur, payload.symbol)
            ltp = engine.last_price(cur, commodity["commodity_id"])
            step = engine.quote_step(commodity, ltp)
            price = ltp - step if payload.side == "buy" else ltp + step
        return engine.place_order(cur, payload.trader_id, payload.symbol, payload.side, payload.order_type,
                                  payload.quantity, price, payload.motive)
    return run(go)


@app.get("/api/live")
def live(symbol: str = "COTTON", feed_limit: int = Query(default=30, le=100)) -> dict:
    with connection() as conn, conn.pipeline():
        cur = {name: conn.cursor() for name in ['tickers', 'levels', 'ticks', 'participants', 'feed', 'scd', 'stats']}
        cur["tickers"].execute(f"""
            SELECT c.commodity_id, c.symbol, c.name, c.unit, c.tick_size, c.minimum_order_quantity,
                   COALESCE(tick.price, latest.close_price) AS ltp,
                   prev.close_price AS prev_close,
                   COALESCE(today.volume, 0) AS today_volume,
                   today.high_price AS today_high, today.low_price AS today_low
            FROM commodities c
            LEFT JOIN LATERAL (SELECT price FROM price_ticks WHERE commodity_id = c.commodity_id ORDER BY tick_id DESC LIMIT 1) tick ON true
            LEFT JOIN LATERAL (SELECT close_price FROM market_prices WHERE commodity_id = c.commodity_id ORDER BY price_date DESC LIMIT 1) latest ON true
            LEFT JOIN LATERAL (SELECT close_price FROM market_prices WHERE commodity_id = c.commodity_id
                               AND price_date < {engine.IST_TODAY} ORDER BY price_date DESC LIMIT 1) prev ON true
            LEFT JOIN market_prices today ON today.commodity_id = c.commodity_id AND today.price_date = {engine.IST_TODAY}
            WHERE c.status = 'active' ORDER BY c.symbol
        """)

        cur["levels"].execute("""
            SELECT o.side, o.price, sum(o.quantity - o.filled_quantity) AS quantity,
                   array_agg(DISTINCT u.full_name) AS owners, bool_and(t.is_market_maker) AS market_maker_only
            FROM orders o JOIN traders t ON t.trader_id = o.trader_id JOIN users u ON u.user_id = t.user_id
            JOIN commodities c ON c.commodity_id = o.commodity_id
            WHERE c.symbol = %s AND o.status IN ('open', 'partially_filled') AND o.order_type = 'limit'
            GROUP BY o.side, o.price
        """, (symbol.upper(),))
        cur["ticks"].execute("""
            SELECT * FROM (
                SELECT pt.tick_id, pt.tick_time, pt.price, pt.quantity, pt.aggressor_side, u.full_name AS aggressor
                FROM price_ticks pt JOIN commodities c ON c.commodity_id = pt.commodity_id
                LEFT JOIN traders t ON t.trader_id = pt.aggressor_trader_id LEFT JOIN users u ON u.user_id = t.user_id
                WHERE c.symbol = %s ORDER BY pt.tick_id DESC LIMIT 120
            ) recent ORDER BY tick_id
        """, (symbol.upper(),))

        cur["participants"].execute("""
            SELECT t.trader_id, u.full_name, u.email, u.phone, t.broker_id, t.trader_type, t.organisation, t.address_line, t.city, t.state,
                   t.pincode, t.risk_appetite, t.kyc_tier, t.experience_level, t.strategy, t.avatar_color, t.cash_balance,
                   t.is_persona, b.name AS broker_name,
                   (SELECT count(*) FROM trader_history h WHERE h.trader_id = t.trader_id) AS profile_versions,
                   COALESCE((SELECT json_agg(json_build_object(
                        'symbol', c.symbol, 'quantity', p.quantity, 'average_price', p.average_price,
                        'current_price', p.current_price, 'realized_pnl', p.realized_pnl,
                        'unrealized_pnl', (p.current_price - p.average_price) * p.quantity) ORDER BY c.symbol)
                     FROM portfolio p JOIN commodities c ON c.commodity_id = p.commodity_id
                     WHERE p.trader_id = t.trader_id AND (p.quantity <> 0 OR p.realized_pnl <> 0)), '[]') AS positions,
                   (SELECT json_build_object('type', e.event_type, 'narrative', e.data->>'narrative', 'at', e.created_at,
                                             'side', e.data->>'side', 'symbol', e.data->>'symbol')
                    FROM events e WHERE (e.data->>'trader_id' = t.trader_id::text OR e.entity_id = t.trader_id)
                    ORDER BY e.created_at DESC LIMIT 1) AS last_action
            FROM traders t JOIN users u ON u.user_id = t.user_id LEFT JOIN brokers b ON b.broker_id = t.broker_id
            WHERE NOT t.is_market_maker AND t.status = 'active'
            ORDER BY NOT t.is_persona, u.full_name
        """)

        cur["feed"].execute("""
            SELECT e.event_id, e.event_type, e.created_at, e.data->>'narrative' AS narrative, e.data->>'symbol' AS symbol,
                   e.data->>'side' AS side, e.data->>'trader_name' AS trader_name,
                   (e.data->>'price_before')::numeric AS price_before, (e.data->>'price_after')::numeric AS price_after
            FROM events e
            WHERE e.data ? 'narrative'
            ORDER BY e.created_at DESC LIMIT %s
        """, (feed_limit,))

        cur["scd"].execute("""
            SELECT dimension, entity_id, entity_name, version_no, from_date, to_date, current_flag, change_reason, changed_fields
            FROM analytics.v_scd_change_log ORDER BY from_date DESC, version_no DESC LIMIT 14
        """)

        cur["stats"].execute(f"""
            SELECT count(*)::int AS trades_today, COALESCE(sum(t.price * t.quantity), 0) AS notional_today,
                   (SELECT count(*)::int FROM trader_history) + (SELECT count(*)::int FROM user_history)
                     + (SELECT count(*)::int FROM commodity_history) AS scd_rows
            FROM trades t WHERE (t.trade_time AT TIME ZONE 'Asia/Kolkata')::date = {engine.IST_TODAY}
        """)
        rows = {name: c.fetchall() for name, c in cur.items()}

    levels = rows["levels"]
    bids = sorted((l for l in levels if l["side"] == "buy"), key=lambda l: -l["price"])[:6]
    asks = sorted((l for l in levels if l["side"] == "sell"), key=lambda l: l["price"])[:6]
    tickers, ticks, participants, feed, scd = rows["tickers"], rows["ticks"], rows["participants"], rows["feed"], rows["scd"]
    stats = rows["stats"][0]
    return {"symbol": symbol.upper(), "tickers": tickers, "book": {"bids": bids, "asks": asks}, "ticks": ticks,
            "participants": participants, "feed": feed, "scd": scd, "stats": stats, "scenario": scenario_status()}
