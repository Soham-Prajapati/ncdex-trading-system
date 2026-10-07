from decimal import Decimal
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .db import connection, fetch_all, fetch_one
from .schemas import Commodity, MarketPrice, Order, OrderCreate, Overview, Trade

app = FastAPI(title="NCDEX Trading System API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    row = fetch_one("SELECT now() AS database_time")
    return {"status": "ok", "database_time": row["database_time"] if row else None}


@app.get("/api/overview", response_model=Overview)
def overview() -> Overview:
    row = fetch_one("""
        SELECT
            (SELECT count(*)::int FROM trades WHERE status IN ('executed', 'settled')) AS total_trades,
            COALESCE((SELECT sum(quantity) FROM trades WHERE status IN ('executed', 'settled')), 0) AS traded_quantity,
            COALESCE((SELECT sum(price * quantity) FROM trades WHERE status IN ('executed', 'settled')), 0) AS traded_notional,
            (SELECT count(*)::int FROM traders WHERE status = 'active') AS active_traders,
            (SELECT count(*)::int FROM commodities WHERE status = 'active') AS listed_commodities,
            COALESCE((SELECT avg(daily_change_pct) FROM analytics.v_market_prices WHERE price_date = (SELECT max(price_date) FROM market_prices)), 0) AS market_change_pct
    """)
    return row


@app.get("/api/commodities", response_model=list[Commodity])
def commodities() -> list[dict]:
    return fetch_all("""
        SELECT c.commodity_id, c.symbol, c.name, cat.name AS category_name, c.unit,
               latest.close_price AS current_price, latest.daily_change_pct
        FROM commodities c
        JOIN categories cat ON cat.category_id = c.category_id
        LEFT JOIN LATERAL (
            SELECT close_price, daily_change_pct
            FROM analytics.v_market_prices
            WHERE commodity_id = c.commodity_id
            ORDER BY price_date DESC LIMIT 1
        ) latest ON true
        WHERE c.status = 'active'
        ORDER BY c.symbol
    """)


@app.get("/api/market/prices", response_model=list[MarketPrice])
def market_prices(symbol: str | None = None, limit: int = Query(default=100, le=500)) -> list[dict]:
    if symbol:
        return fetch_all("""
            SELECT * FROM analytics.v_market_prices WHERE symbol = %s ORDER BY price_date DESC LIMIT %s
        """, (symbol.upper(), limit))
    return fetch_all("SELECT * FROM analytics.v_market_prices ORDER BY price_date DESC, symbol LIMIT %s", (limit,))


@app.get("/api/market/summary")
def market_summary(limit: int = Query(default=30, le=200)) -> list[dict]:
    return fetch_all("SELECT * FROM analytics.v_daily_market_summary ORDER BY trade_date DESC, symbol LIMIT %s", (limit,))


@app.get("/api/orders", response_model=list[Order])
def orders(limit: int = Query(default=30, le=200)) -> list[dict]:
    return fetch_all("SELECT * FROM analytics.v_order_activity ORDER BY submitted_at DESC LIMIT %s", (limit,))


@app.get("/api/trades", response_model=list[Trade])
def trades(limit: int = Query(default=50, le=200)) -> list[dict]:
    return fetch_all("SELECT * FROM analytics.v_trade_facts ORDER BY trade_time DESC LIMIT %s", (limit,))


@app.get("/api/portfolio/{email}")
def portfolio(email: str) -> list[dict]:
    return fetch_all("SELECT * FROM analytics.v_portfolio_snapshot WHERE email = %s ORDER BY current_value DESC", (email,))


@app.post("/api/orders", response_model=Order, status_code=201)
def submit_order(payload: OrderCreate) -> dict:
    if payload.order_type == "market":
        raise HTTPException(400, "Market orders are reserved for the matching engine phase; use a limit order in this prototype.")
    if payload.price is None:
        raise HTTPException(400, "Limit orders require a price.")
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT trader_id FROM traders tr JOIN users u ON u.user_id = tr.user_id WHERE u.email = %s AND tr.status = 'active'", (payload.trader_email,))
            trader = cur.fetchone()
            cur.execute("SELECT commodity_id, minimum_order_quantity FROM commodities WHERE symbol = %s AND status = 'active'", (payload.symbol.upper(),))
            commodity = cur.fetchone()
            if not trader or not commodity:
                raise HTTPException(404, "Active trader or commodity not found")
            if payload.quantity < commodity["minimum_order_quantity"]:
                raise HTTPException(400, "Quantity is below the commodity minimum")

            cur.execute("""
                INSERT INTO orders (trader_id, commodity_id, side, order_type, price, quantity)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING order_id
            """, (trader["trader_id"], commodity["commodity_id"], payload.side, payload.order_type, payload.price, payload.quantity))
            order_id = cur.fetchone()["order_id"]
            cur.execute("""
                INSERT INTO events (event_type, actor_user_id, entity_type, entity_id, data)
                SELECT 'order_submitted', u.user_id, 'order', %s,
                       jsonb_build_object('symbol', %s, 'side', %s, 'price', %s, 'quantity', %s)
                FROM users u WHERE u.email = %s
            """, (order_id, payload.symbol.upper(), payload.side, payload.price, payload.quantity, payload.trader_email))

            # Price-time priority matching for the newly submitted limit order.
            opposite = "sell" if payload.side == "buy" else "buy"
            comparator = "<=" if payload.side == "buy" else ">="
            cur.execute(f"""
                SELECT order_id, trader_id, price, quantity, filled_quantity
                FROM orders
                WHERE commodity_id = %s AND side = %s AND status IN ('open', 'partially_filled')
                  AND order_id <> %s AND price {comparator} %s
                ORDER BY price {'ASC' if payload.side == 'buy' else 'DESC'}, submitted_at
                FOR UPDATE
            """, (commodity["commodity_id"], opposite, order_id, payload.price))
            remaining = payload.quantity
            for resting in cur.fetchall():
                if remaining <= 0:
                    break
                available = resting["quantity"] - resting["filled_quantity"]
                fill = min(remaining, available)
                cur.execute("""
                    INSERT INTO trades (buy_order_id, sell_order_id, commodity_id, price, quantity)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING trade_id
                """, (order_id if payload.side == "buy" else resting["order_id"], resting["order_id"] if payload.side == "buy" else order_id, commodity["commodity_id"], resting["price"], fill))
                trade_id = cur.fetchone()["trade_id"]
                buy_trader_id = trader["trader_id"] if payload.side == "buy" else resting["trader_id"]
                sell_trader_id = resting["trader_id"] if payload.side == "buy" else trader["trader_id"]
                execution_price = resting["price"]
                cur.execute("""
                    INSERT INTO portfolio (trader_id, commodity_id, quantity, average_price, current_price)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (trader_id, commodity_id) DO UPDATE SET
                        average_price = CASE WHEN portfolio.quantity + EXCLUDED.quantity = 0 THEN 0
                            ELSE ((portfolio.quantity * portfolio.average_price) + (EXCLUDED.quantity * EXCLUDED.average_price)) /
                                 (portfolio.quantity + EXCLUDED.quantity) END,
                        quantity = portfolio.quantity + EXCLUDED.quantity,
                        current_price = EXCLUDED.current_price,
                        updated_at = now()
                """, (buy_trader_id, commodity["commodity_id"], fill, execution_price, execution_price))
                cur.execute("""
                    UPDATE portfolio SET quantity = GREATEST(0, quantity - %s), current_price = %s, updated_at = now()
                    WHERE trader_id = %s AND commodity_id = %s
                """, (fill, execution_price, sell_trader_id, commodity["commodity_id"]))
                cur.execute("""
                    INSERT INTO transactions (trade_id, trader_id, transaction_type, amount, reference)
                    VALUES (%s, %s, 'trade_debit', %s, 'api-order-match-buy'),
                           (%s, %s, 'trade_credit', %s, 'api-order-match-sell')
                """, (trade_id, buy_trader_id, execution_price * fill, trade_id, sell_trader_id, execution_price * fill))
                cur.execute("""
                    INSERT INTO events (event_type, actor_user_id, entity_type, entity_id, data)
                    SELECT 'trade_executed', u.user_id, 'trade', %s,
                           jsonb_build_object('symbol', %s, 'price', %s, 'quantity', %s)
                    FROM users u WHERE u.email = %s
                """, (trade_id, payload.symbol.upper(), execution_price, fill, payload.trader_email))
                cur.execute("UPDATE orders SET filled_quantity = filled_quantity + %s, status = CASE WHEN filled_quantity + %s >= quantity THEN 'filled' ELSE 'partially_filled' END, updated_at = now() WHERE order_id = %s", (fill, fill, resting["order_id"]))
                remaining -= fill
            cur.execute("UPDATE orders SET filled_quantity = quantity - %s, status = CASE WHEN quantity - %s >= quantity THEN 'filled' WHEN quantity - %s > 0 THEN 'partially_filled' ELSE 'open' END, updated_at = now() WHERE order_id = %s", (remaining, remaining, remaining, order_id))
        conn.commit()
    result = fetch_one("SELECT * FROM analytics.v_order_activity WHERE order_id = %s", (order_id,))
    return result
