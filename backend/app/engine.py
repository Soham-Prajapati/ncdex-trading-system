"""Exchange simulation engine: price-time matching, a market maker that keeps
the book two-sided, futures-style positions, SCD2-tracked profile changes, and
a scripted faculty demo scenario.

Every public function takes an open cursor and runs inside the caller's
transaction; the caller commits.
"""

from decimal import ROUND_HALF_UP, Decimal
import json
import random
from uuid import uuid4

from psycopg.types.json import Jsonb

D = Decimal
IST_TODAY = "(now() AT TIME ZONE 'Asia/Kolkata')::date"
MATCHING_LOCK = 7311
MM_LEVELS = (10, 15, 20, 25, 30)

TRADER_FIELDS = {
    "trader_type", "organisation", "address_line", "city", "state", "pincode",
    "risk_appetite", "kyc_tier", "experience_level", "status", "broker_id",
}
USER_FIELDS = {"full_name", "phone", "email"}
COMMODITY_FIELDS = {"name", "description", "unit", "tick_size", "minimum_order_quantity", "status"}


class EngineError(Exception):
    pass


def rupees(value) -> str:
    return f"₹{D(value):,.2f}"


def qty_text(value) -> str:
    value = D(value)
    return f"{value.normalize():f}" if value == value.to_integral() else f"{value:f}"


def round_tick(value, tick) -> Decimal:
    tick = D(tick)
    return ((D(value) / tick).quantize(D(1), ROUND_HALF_UP) * tick).quantize(D("0.01"))


# --- lookups -----------------------------------------------------------------

def get_commodity(cur, symbol: str) -> dict:
    cur.execute("""
        SELECT commodity_id, symbol, name, unit, tick_size, minimum_order_quantity
        FROM commodities WHERE symbol = %s AND status = 'active'
    """, (symbol.upper(),))
    row = cur.fetchone()
    if not row:
        raise EngineError(f"Active commodity {symbol} not found")
    return row


TRADER_SELECT = """
    SELECT t.trader_id, t.user_id, u.full_name, u.email, t.trader_type, t.cash_balance, t.is_market_maker
    FROM traders t JOIN users u ON u.user_id = t.user_id
"""


def get_trader(cur, *, trader_id=None, email=None, lock=False) -> dict:
    clause = "t.trader_id = %s" if trader_id else "u.email = %s"
    cur.execute(f"{TRADER_SELECT} WHERE {clause} AND t.status = 'active'{' FOR UPDATE OF t' if lock else ''}",
                (trader_id or email,))
    row = cur.fetchone()
    if not row:
        raise EngineError("Active trader not found")
    return row


def last_price(cur, commodity_id) -> Decimal:
    cur.execute("SELECT price FROM price_ticks WHERE commodity_id = %s ORDER BY tick_id DESC LIMIT 1", (commodity_id,))
    row = cur.fetchone()
    if row:
        return row["price"]
    cur.execute("SELECT close_price FROM market_prices WHERE commodity_id = %s ORDER BY price_date DESC LIMIT 1", (commodity_id,))
    row = cur.fetchone()
    return row["close_price"] if row else D(1)


def quote_step(commodity: dict, ltp: Decimal) -> Decimal:
    return max(D(commodity["tick_size"]), round_tick(ltp * D("0.0015"), commodity["tick_size"]))


def log_event(cur, event_type: str, actor_user_id, entity_type: str, entity_id, narrative: str, **data) -> None:
    data["narrative"] = narrative
    cur.execute("""
        INSERT INTO events (event_type, actor_user_id, entity_type, entity_id, data, created_at)
        VALUES (%s, %s, %s, %s, %s, clock_timestamp())
    """, (event_type, actor_user_id, entity_type, entity_id, Jsonb(json.loads(json.dumps(data, default=str)))))


# --- positions -----------------------------------------------------------------

def next_position(position: tuple, signed_qty: Decimal, price: Decimal) -> tuple:
    """Net futures position (long or short) with weighted average cost and realised P&L."""
    q0, avg0, realized = position
    q1 = q0 + signed_qty
    if q0 == 0 or (q0 > 0) == (signed_qty > 0):
        avg1 = (abs(q0) * avg0 + abs(signed_qty) * price) / abs(q1)
    else:
        closing = min(abs(signed_qty), abs(q0))
        realized += closing * (price - avg0) * (1 if q0 > 0 else -1)
        avg1 = D(0) if q1 == 0 else (avg0 if (q1 > 0) == (q0 > 0) else price)
    return q1, round(avg1, 6), realized


# --- matching ------------------------------------------------------------------
# Neon is ~100 ms away, so an order is two round trips: one locked read of the
# whole book and positions, matching in Python, then one pipelined write batch.

COMMODITY_LTP_SQL = """
    SELECT c.commodity_id, c.symbol, c.name, c.unit, c.tick_size, c.minimum_order_quantity,
           COALESCE((SELECT price FROM price_ticks pt WHERE pt.commodity_id = c.commodity_id ORDER BY tick_id DESC LIMIT 1),
                    (SELECT close_price FROM market_prices mp WHERE mp.commodity_id = c.commodity_id ORDER BY price_date DESC LIMIT 1),
                    1) AS ltp
    FROM commodities c WHERE c.symbol = %s AND c.status = 'active'
"""
BOOK_SQL = """
    SELECT o.order_id, o.trader_id, o.side, o.price, o.quantity, o.filled_quantity, o.submitted_at,
           u.full_name, t.is_market_maker
    FROM orders o JOIN traders t ON t.trader_id = o.trader_id JOIN users u ON u.user_id = t.user_id
    JOIN commodities c ON c.commodity_id = o.commodity_id
    WHERE c.symbol = %s AND o.order_type = 'limit' AND o.status IN ('open', 'partially_filled')
    FOR UPDATE OF o
"""
POSITIONS_SQL = """
    SELECT p.trader_id, p.quantity, p.average_price, p.realized_pnl
    FROM portfolio p JOIN commodities c ON c.commodity_id = p.commodity_id
    WHERE c.symbol = %s FOR UPDATE OF p
"""


def mm_quotes(commodity: dict, ltp: Decimal, mm_id, resting: list[tuple]) -> list[tuple]:
    """Five-level two-sided quote around the LTP that never crosses another participant's resting order."""
    step = quote_step(commodity, ltp)
    bids = [p for s, p in resting if s == "buy"]
    asks = [p for s, p in resting if s == "sell"]
    best_bid, best_ask = (max(bids) if bids else None), (min(asks) if asks else None)
    quotes = []
    for i, size in enumerate(MM_LEVELS, start=1):
        ask, bid = ltp + step * i, ltp - step * i
        if best_bid is None or ask > best_bid:
            quotes.append((mm_id, commodity["commodity_id"], "sell", "limit", ask, size))
        if bid > 0 and (best_ask is None or bid < best_ask):
            quotes.append((mm_id, commodity["commodity_id"], "buy", "limit", bid, size))
    return quotes


MM_WITHDRAW_SQL = [
    # Untouched quotes are simply withdrawn; partially-filled ones keep their trade history.
    "DELETE FROM orders WHERE trader_id = %s AND commodity_id = %s AND status = 'open' AND filled_quantity = 0",
    "UPDATE orders SET status = 'cancelled', updated_at = now() WHERE trader_id = %s AND commodity_id = %s AND status = 'partially_filled'",
]
INSERT_ORDER_SQL = """
    INSERT INTO orders (order_id, trader_id, commodity_id, side, order_type, price, quantity, filled_quantity, status, submitted_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, clock_timestamp())
"""


def place_order(cur, trader_id, symbol: str, side: str, order_type: str, quantity, price=None,
                motive: str | None = None, refresh_book: bool = True) -> dict:
    conn = cur.connection
    symbol, buy, quantity = symbol.upper(), side == "buy", D(quantity)
    c_trader, c_comm, c_book, c_pos, c_mm = (conn.cursor() for _ in range(5))
    with conn.pipeline():
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (MATCHING_LOCK,))
        c_trader.execute(f"{TRADER_SELECT} WHERE t.trader_id = %s AND t.status = 'active' FOR UPDATE OF t", (trader_id,))
        c_comm.execute(COMMODITY_LTP_SQL, (symbol,))
        c_book.execute(BOOK_SQL, (symbol,))
        c_pos.execute(POSITIONS_SQL, (symbol,))
        c_mm.execute("SELECT trader_id FROM traders WHERE is_market_maker LIMIT 1")
        trader, commodity, book = c_trader.fetchone(), c_comm.fetchone(), c_book.fetchall()
        positions = {r["trader_id"]: (r["quantity"], r["average_price"], r["realized_pnl"]) for r in c_pos.fetchall()}
        mm = c_mm.fetchone()
    if not trader:
        raise EngineError("Active trader not found")
    trader_id = trader["trader_id"]
    if not commodity:
        raise EngineError(f"Active commodity {symbol} not found")
    cid, unit, before = commodity["commodity_id"], commodity["unit"], commodity["ltp"]
    if quantity < commodity["minimum_order_quantity"]:
        raise EngineError(f"{symbol} minimum order is {qty_text(commodity['minimum_order_quantity'])} {unit}")
    if order_type == "limit":
        if price is None:
            raise EngineError("Limit orders require a price")
        price = round_tick(price, commodity["tick_size"])
    else:
        price = None
    if buy and not trader["is_market_maker"]:
        estimate = (price or before * D("1.02")) * quantity
        if estimate > trader["cash_balance"]:
            raise EngineError(f"{trader['full_name']} has {rupees(trader['cash_balance'])}, needs about {rupees(estimate)}")

    # Price-time priority: best price first, then earliest submission. No self-matching.
    opposite = sorted(
        (o for o in book if o["side"] != side and o["trader_id"] != trader_id
         and (price is None or (o["price"] <= price if buy else o["price"] >= price))),
        key=lambda o: (o["price"] if buy else -o["price"], o["submitted_at"], str(o["order_id"])))

    order_id = uuid4()
    remaining, previous, fills, writes = quantity, before, [], []
    cash = {}
    for resting in opposite:
        if remaining <= 0:
            break
        px = resting["price"]
        fill = min(remaining, resting["quantity"] - resting["filled_quantity"])
        trade_id = uuid4()
        buyer, seller = (trader_id, resting["trader_id"]) if buy else (resting["trader_id"], trader_id)
        writes.append(("""INSERT INTO trades (trade_id, buy_order_id, sell_order_id, commodity_id, price, quantity, trade_time)
                          VALUES (%s, %s, %s, %s, %s, %s, clock_timestamp())""",
                       (trade_id, order_id if buy else resting["order_id"], resting["order_id"] if buy else order_id, cid, px, fill)))
        resting["filled_quantity"] += fill
        writes.append(("UPDATE orders SET filled_quantity = %s, status = %s, updated_at = now() WHERE order_id = %s",
                       (resting["filled_quantity"], "filled" if resting["filled_quantity"] >= resting["quantity"] else "partially_filled",
                        resting["order_id"])))
        for who, signed_qty in ((buyer, fill), (seller, -fill)):
            positions[who] = next_position(positions.get(who, (D(0), D(0), D(0))), signed_qty, px)
        notional = px * fill
        cash[buyer] = cash.get(buyer, D(0)) - notional
        cash[seller] = cash.get(seller, D(0)) + notional
        writes.append(("""INSERT INTO transactions (trade_id, trader_id, transaction_type, amount, reference)
                          VALUES (%s, %s, 'trade_debit', %s, 'live-sim-buy'), (%s, %s, 'trade_credit', %s, 'live-sim-sell')""",
                       (trade_id, buyer, notional, trade_id, seller, notional)))
        writes.append(("""INSERT INTO price_ticks (commodity_id, trade_id, aggressor_trader_id, aggressor_side, previous_price, price, quantity, narrative)
                          VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                       (cid, trade_id, trader_id, side, previous, px, fill,
                        f"{trader['full_name']} {side} {qty_text(fill)} {unit} @ {rupees(px)} against {resting['full_name']}")))
        fills.append({"price": px, "quantity": fill, "counterparty": resting["full_name"],
                      "counterparty_is_mm": resting["is_market_maker"], "trade_id": trade_id})
        previous, remaining = px, remaining - fill

    filled = quantity - remaining
    if remaining == 0:
        status = "filled"
    elif order_type == "market":
        status = "cancelled"  # market orders are immediate-or-cancel
    else:
        status = "partially_filled" if filled > 0 else "open"
    after = previous
    # The aggressor's order must exist before the trades that reference it.
    writes.insert(0, (INSERT_ORDER_SQL, (order_id, trader_id, cid, side, order_type, price, quantity, filled, status)))

    if fills:
        for who in {f for f in cash}:
            q1, avg1, realized = positions[who]
            writes.append(("""INSERT INTO portfolio (trader_id, commodity_id, quantity, average_price, current_price, realized_pnl)
                              VALUES (%s, %s, %s, %s, %s, %s)
                              ON CONFLICT (trader_id, commodity_id) DO UPDATE SET
                                  quantity = EXCLUDED.quantity, average_price = EXCLUDED.average_price,
                                  realized_pnl = EXCLUDED.realized_pnl, updated_at = now()""",
                           (who, cid, q1, avg1, after, realized)))
            writes.append(("UPDATE traders SET cash_balance = cash_balance + %s WHERE trader_id = %s", (cash[who], who)))
        prices = [f["price"] for f in fills]
        writes.append((f"""
            INSERT INTO market_prices (commodity_id, price_date, open_price, high_price, low_price, close_price, volume, source)
            VALUES (%s, {IST_TODAY}, %s, %s, %s, %s, %s, 'live-simulation')
            ON CONFLICT (commodity_id, price_date) DO UPDATE SET
                high_price = GREATEST(market_prices.high_price, EXCLUDED.high_price),
                low_price = LEAST(market_prices.low_price, EXCLUDED.low_price),
                close_price = EXCLUDED.close_price,
                volume = market_prices.volume + EXCLUDED.volume,
                source = 'live-simulation'
        """, (cid, before, max(prices + [before]), min(prices + [before]), after, filled)))
        # Mark every open position in this contract to the new last traded price.
        writes.append(("UPDATE portfolio SET current_price = %s, updated_at = now() WHERE commodity_id = %s", (after, cid)))

    narrative = explain(trader, commodity, side, order_type, quantity, price, fills, before, after, status, motive)
    event = "trade_executed" if fills else ("order_submitted" if status == "open" else "order_cancelled")
    data = {"symbol": symbol, "side": side, "order_type": order_type, "quantity": quantity, "filled": filled,
            "price_before": before, "price_after": after, "trader_id": trader_id, "trader_name": trader["full_name"],
            "trader_type": trader["trader_type"], "motive": motive, "levels": len({f["price"] for f in fills}),
            "counterparties": sorted({f["counterparty"] for f in fills}), "narrative": narrative}
    writes.append(("""INSERT INTO events (event_type, actor_user_id, entity_type, entity_id, data, created_at)
                      VALUES (%s, %s, 'order', %s, %s, clock_timestamp())""",
                   (event, trader["user_id"], order_id, Jsonb(json.loads(json.dumps(data, default=str))))))

    if refresh_book and mm and not trader["is_market_maker"]:
        resting_after = [(o["side"], o["price"]) for o in book
                         if not o["is_market_maker"] and o["filled_quantity"] < o["quantity"]]
        if status in ("open", "partially_filled"):
            resting_after.append((side, price))
        writes += [(sql, (mm["trader_id"], cid)) for sql in MM_WITHDRAW_SQL]
        writes += [("""INSERT INTO orders (trader_id, commodity_id, side, order_type, price, quantity, submitted_at)
                       VALUES (%s, %s, %s, %s, %s, %s, clock_timestamp())""", q)
                   for q in mm_quotes(commodity, after, mm["trader_id"], resting_after)]

    with conn.pipeline():
        for sql, params in writes:
            cur.execute(sql, params)
    return {"order_id": order_id, "status": status, "filled": filled, "price_before": before, "price_after": after,
            "fills": fills, "narrative": narrative}


def explain(trader, commodity, side, order_type, quantity, price, fills, before, after, status, motive) -> str:
    who = f"{trader['full_name']} ({trader['trader_type']})"
    sym, unit = commodity["symbol"], commodity["unit"]
    verb = "BUY" if side == "buy" else "SELL"
    how = "at market" if order_type == "market" else f"limit {rupees(price)}"
    lead = f"{motive} → " if motive else ""
    if not fills:
        if status == "open":
            wall = "a new offer — extra supply that caps the rally" if side == "sell" else "a new bid — extra demand that props the price up"
            return f"{lead}{who} posted {verb} {qty_text(quantity)} {unit} {sym} {how}. No one matched yet, so it rests in the order book as {wall}."
        return f"{lead}{who} sent {verb} {qty_text(quantity)} {unit} {sym} {how}, but the book had no matching counterparty, so it was cancelled."
    filled = sum(f["quantity"] for f in fills)
    levels = sorted({f["price"] for f in fills})
    change = after - before
    pct = change / before * 100 if before else D(0)
    others = sorted({f["counterparty"] for f in fills if not f["counterparty_is_mm"]})
    against = f" Matched against {', '.join(others)}." if others else ""
    move = f"LTP {rupees(before)} → {rupees(after)} ({'+' if change >= 0 else ''}{pct:.2f}%)."
    if change > 0:
        why = f"Why up: the buyer was willing to pay more and consumed {len(levels)} offer level(s) up to {rupees(levels[-1])}, so the last traded price printed higher."
    elif change < 0:
        why = f"Why down: the seller accepted less and hit {len(levels)} bid level(s) down to {rupees(levels[0])}, so the last traded price printed lower."
    else:
        why = "Why flat: enough liquidity sat at the best price to absorb the order without moving it."
    return f"{lead}{who} {verb} {qty_text(filled)}/{qty_text(quantity)} {unit} {sym} {how}. {move} {why}{against}"


def refresh_market_maker(cur, commodity: dict) -> None:
    """Re-centre the liquidity desk's quote on the latest traded price (used when resetting the books)."""
    cid = commodity["commodity_id"]
    cur.execute("SELECT trader_id FROM traders WHERE is_market_maker LIMIT 1")
    mm = cur.fetchone()
    if not mm:
        return
    for sql in MM_WITHDRAW_SQL:
        cur.execute(sql, (mm["trader_id"], cid))
    cur.execute("""
        SELECT side, price FROM orders WHERE commodity_id = %s AND order_type = 'limit'
          AND status IN ('open', 'partially_filled') AND trader_id <> %s
    """, (cid, mm["trader_id"]))
    resting = [(r["side"], r["price"]) for r in cur.fetchall()]
    cur.executemany("""
        INSERT INTO orders (trader_id, commodity_id, side, order_type, price, quantity, submitted_at)
        VALUES (%s, %s, %s, %s, %s, %s, clock_timestamp())
    """, mm_quotes(commodity, last_price(cur, cid), mm["trader_id"], resting))


def reset_books(cur) -> None:
    """Cancel every resting participant order and re-quote all books around the last price."""
    cur.execute("SELECT pg_advisory_xact_lock(%s)", (MATCHING_LOCK,))
    cur.execute("""
        UPDATE orders o SET status = 'cancelled', updated_at = now()
        FROM traders t WHERE t.trader_id = o.trader_id AND NOT t.is_market_maker
          AND o.status IN ('open', 'partially_filled') AND o.order_type = 'limit'
    """)
    cur.execute("SELECT commodity_id, symbol, name, unit, tick_size, minimum_order_quantity FROM commodities WHERE status = 'active'")
    for commodity in cur.fetchall():
        refresh_market_maker(cur, commodity)


# --- SCD2 profile changes ----------------------------------------------------------

def _changes(old: dict, new: dict) -> dict:
    return {k: (old.get(k), v) for k, v in new.items() if str(old.get(k)) != str(v)}


def update_trader_profile(cur, trader_id, changes: dict, reason: str, actor_user_id=None) -> dict:
    trader_changes = {k: v for k, v in changes.items() if k in TRADER_FIELDS}
    user_changes = {k: v for k, v in changes.items() if k in USER_FIELDS}
    unknown = set(changes) - TRADER_FIELDS - USER_FIELDS
    if unknown:
        raise EngineError(f"Fields not editable: {', '.join(sorted(unknown))}")
    cur.execute("""
        SELECT t.*, u.full_name, u.phone, u.email FROM traders t JOIN users u ON u.user_id = t.user_id
        WHERE t.trader_id = %s FOR UPDATE OF t, u
    """, (trader_id,))
    current = cur.fetchone()
    if not current:
        raise EngineError("Trader not found")
    diff = _changes(current, trader_changes | user_changes)
    if not diff:
        raise EngineError("Nothing changed — SCD2 only creates a version when a tracked attribute changes")
    cur.execute("SELECT set_config('app.change_reason', %s, true), set_config('app.actor_user_id', %s, true)",
                (reason, str(actor_user_id or current["user_id"])))
    tc = {k: v for k, v in trader_changes.items() if k in diff}
    uc = {k: v for k, v in user_changes.items() if k in diff}
    if tc:
        cur.execute(f"UPDATE traders SET {', '.join(f'{k} = %({k})s' for k in tc)}, updated_at = now() WHERE trader_id = %(id)s",
                    tc | {"id": trader_id})
    if uc:
        cur.execute(f"UPDATE users SET {', '.join(f'{k} = %({k})s' for k in uc)}, updated_at = now() WHERE user_id = %(id)s",
                    uc | {"id": current["user_id"]})
    cur.execute("SELECT count(*) AS n FROM trader_history WHERE trader_id = %s", (trader_id,))
    versions = cur.fetchone()["n"]
    name = uc.get("full_name", current["full_name"])
    pretty = "; ".join(f"{k.replace('_', ' ')}: {old or '∅'} → {new}" for k, (old, new) in diff.items())
    narrative = (f"{name} updated profile — {pretty}. SCD2: the old version was closed (to_date = now, current_flag = N) "
                 f"and a new current version opened (to_date = ∞, current_flag = Y). Reason: {reason}.")
    log_event(cur, "profile_updated", current["user_id"], "trader", trader_id, narrative,
              trader_name=name, changes={k: [str(o), str(n)] for k, (o, n) in diff.items()}, versions=versions, reason=reason)
    return {"trader_id": trader_id, "changes": diff, "versions": versions, "narrative": narrative}


def update_commodity(cur, symbol: str, changes: dict, reason: str) -> dict:
    unknown = set(changes) - COMMODITY_FIELDS
    if unknown:
        raise EngineError(f"Fields not editable: {', '.join(sorted(unknown))}")
    cur.execute("SELECT * FROM commodities WHERE symbol = %s FOR UPDATE", (symbol.upper(),))
    current = cur.fetchone()
    if not current:
        raise EngineError("Commodity not found")
    diff = _changes(current, changes)
    if not diff:
        raise EngineError("Nothing changed")
    cur.execute("SELECT user_id FROM users WHERE role = 'administrator' LIMIT 1")
    admin = cur.fetchone()
    cur.execute("SELECT set_config('app.change_reason', %s, true), set_config('app.actor_user_id', %s, true)",
                (reason, str(admin["user_id"]) if admin else ""))
    cur.execute(f"UPDATE commodities SET {', '.join(f'{k} = %({k})s' for k in diff)}, updated_at = now() WHERE commodity_id = %(id)s",
                {k: v for k, (_, v) in diff.items()} | {"id": current["commodity_id"]})
    pretty = "; ".join(f"{k.replace('_', ' ')}: {qty_text(o) if isinstance(o, Decimal) else o} → {n}" for k, (o, n) in diff.items())
    narrative = (f"Exchange admin changed {current['symbol']} contract — {pretty}. SCD2 kept the old contract terms as a closed "
                 f"version in commodity_history. Reason: {reason}.")
    log_event(cur, "commodity_updated", admin["user_id"] if admin else None, "commodity", current["commodity_id"], narrative,
              symbol=current["symbol"], reason=reason)
    return {"symbol": current["symbol"], "changes": diff, "narrative": narrative}


def market_news(cur, headline: str, detail: str) -> dict:
    narrative = f"📰 {headline} — {detail}"
    log_event(cur, "market_news", None, "market", None, narrative, headline=headline)
    return {"narrative": narrative}


# --- scripted faculty scenario -------------------------------------------------------

SCENARIO = [
    {"title": "Opening bell", "kind": "reset",
     "text": "Market opens — liquidity desk quotes every contract around the last traded price"},
    {"title": "Monsoon shock", "kind": "news", "headline": "IMD: monsoon 18% below normal over Vidarbha & Marathwada",
     "text": "Cotton crop output at risk; mills and speculators expect higher prices"},
    {"title": "Mill hedges raw material", "kind": "order", "who": "ananya@ncdex-sim.local", "symbol": "COTTON", "side": "buy",
     "type": "market", "qty": 40, "motive": "Fearing costlier cotton, Kaveri Spinning Mills locks in raw material"},
    {"title": "Speculator chases momentum", "kind": "order", "who": "arjun@ncdex-sim.local", "symbol": "COTTON", "side": "buy",
     "type": "market", "qty": 30, "motive": "Seeing price rise, a speculator piles in"},
    {"title": "Farmer hedges harvest", "kind": "order", "who": "ramesh@ncdex-sim.local", "symbol": "COTTON", "side": "sell",
     "type": "limit", "offset": 2, "qty": 40, "motive": "Higher prices let the FPO lock in its harvest price"},
    {"title": "Farmer moves warehouse (SCD2)", "kind": "profile", "who": "ramesh@ncdex-sim.local",
     "options": [{"address_line": "Plot 3, Badnera Road Warehouse", "city": "Amravati", "pincode": "444605"},
                 {"address_line": "Plot 14, APMC Market Yard", "city": "Akola", "pincode": "444001"}],
     "reason": "Address change — FPO shifted stock to a new warehouse"},
    {"title": "Mill buys from the farmer", "kind": "order", "who": "ananya@ncdex-sim.local", "symbol": "COTTON", "side": "buy",
     "type": "market", "qty": 60, "motive": "Mill tops up its hedge"},
    {"title": "Speculator books profit", "kind": "order", "who": "arjun@ncdex-sim.local", "symbol": "COTTON", "side": "sell",
     "type": "market", "qty": 30, "motive": "Speculator sells to lock in the gain"},
    {"title": "Exchange tightens contract (SCD2)", "kind": "commodity", "symbol": "COTTON",
     "options": [{"minimum_order_quantity": 5}, {"minimum_order_quantity": 1}],
     "reason": "Volatility control — exchange revised minimum lot"},
    {"title": "Speculator upgraded to derivatives tier (SCD2)", "kind": "profile", "who": "arjun@ncdex-sim.local",
     "options": [{"risk_appetite": "Very aggressive", "kyc_tier": "Derivatives enabled"},
                 {"risk_appetite": "Aggressive", "kyc_tier": "Full KYC"}],
     "reason": "Profile upgrade after trading-limit review"},
    {"title": "Exporter hedges jeera", "kind": "order", "who": "farhan@ncdex-sim.local", "symbol": "JEERA", "side": "buy",
     "type": "market", "qty": 25, "motive": "A Dubai export order means Unjha Spice Exports must secure jeera"},
    {"title": "Crusher trims soybean", "kind": "order", "who": "meera@ncdex-sim.local", "symbol": "SOYBEAN", "side": "sell",
     "type": "market", "qty": 30, "motive": "Weak soy-meal demand — Malwa Agro sells to cut inventory risk"},
    {"title": "Rain returns", "kind": "news", "headline": "Rains revive over Vidarbha",
     "text": "Crop fears ease; sellers return to the cotton pit"},
    {"title": "Farmer adds to hedge", "kind": "order", "who": "ramesh@ncdex-sim.local", "symbol": "COTTON", "side": "sell",
     "type": "market", "qty": 35, "motive": "Expecting a bigger crop, the FPO sells more futures"},
]


def run_step(cur, index: int) -> dict:
    step = SCENARIO[index]
    kind = step["kind"]
    if kind == "reset":
        reset_books(cur)
        result = market_news(cur, step["title"], step["text"])
    elif kind == "news":
        result = market_news(cur, step["headline"], step["text"])
    elif kind == "order":
        trader = get_trader(cur, email=step["who"])
        price = None
        if step["type"] == "limit":
            commodity = get_commodity(cur, step["symbol"])
            ltp = last_price(cur, commodity["commodity_id"])
            sign = 1 if step["side"] == "sell" else -1
            price = ltp + sign * quote_step(commodity, ltp) * step["offset"]
        result = place_order(cur, trader["trader_id"], step["symbol"], step["side"], step["type"], step["qty"], price, step["motive"])
    elif kind == "profile":
        trader = get_trader(cur, email=step["who"])
        cur.execute("SELECT t.*, u.full_name FROM traders t JOIN users u ON u.user_id = t.user_id WHERE t.trader_id = %s", (trader["trader_id"],))
        current = cur.fetchone()
        first = step["options"][0]
        choice = step["options"][1] if all(str(current[k]) == str(v) for k, v in first.items()) else first
        result = update_trader_profile(cur, trader["trader_id"], choice, step["reason"])
    elif kind == "commodity":
        cur.execute("SELECT * FROM commodities WHERE symbol = %s", (step["symbol"],))
        current = cur.fetchone()
        first = step["options"][0]
        choice = step["options"][1] if all(D(str(current[k])) == D(str(v)) for k, v in first.items()) else first
        result = update_commodity(cur, step["symbol"], choice, step["reason"])
    else:
        raise EngineError(f"Unknown step kind {kind}")
    return {"index": index, "title": step["title"], "kind": kind, **result}


# --- random market flow ----------------------------------------------------------------

PERSONA_BIAS = {
    "ramesh@ncdex-sim.local": ("COTTON", 0.25),
    "ananya@ncdex-sim.local": ("COTTON", 0.75),
    "arjun@ncdex-sim.local": (None, 0.5),
    "farhan@ncdex-sim.local": ("JEERA", 0.6),
    "meera@ncdex-sim.local": ("SOYBEAN", 0.6),
}
RANDOM_MOVES = [
    ("Address change", [{"address_line": "Gala 9, Vashi APMC", "city": "Navi Mumbai", "state": "Maharashtra", "pincode": "400703"},
                        {"address_line": "Shop 21, Market Yard", "city": "Pune", "state": "Maharashtra", "pincode": "411037"},
                        {"address_line": "Godown 4, Gondal Road", "city": "Rajkot", "state": "Gujarat", "pincode": "360004"}]),
    ("Risk profile review", [{"risk_appetite": r} for r in ("Conservative", "Moderate", "Aggressive")]),
    ("Experience update", [{"experience_level": e} for e in ("1 year trading", "3 years trading", "5+ years trading")]),
]


def random_action(cur, rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    cur.execute(f"{TRADER_SELECT} WHERE t.status = 'active' AND NOT t.is_market_maker AND (t.is_persona OR t.trader_type = 'Student trader')")
    traders = cur.fetchall()
    trader = rng.choice(traders)
    if rng.random() < 0.1:
        label, options = rng.choice(RANDOM_MOVES)
        cur.execute("SELECT * FROM traders WHERE trader_id = %s", (trader["trader_id"],))
        current = cur.fetchone()
        fresh = [o for o in options if any(str(current[k]) != str(v) for k, v in o.items())]
        result = update_trader_profile(cur, trader["trader_id"], rng.choice(fresh), f"{label} (random flow)")
        return {"kind": "profile", **result}
    home, buy_bias = PERSONA_BIAS.get(trader["email"], (None, 0.5))
    symbol = home if home and rng.random() < 0.85 else rng.choice(["COTTON", "JEERA", "SOYBEAN"])
    side = "buy" if rng.random() < buy_bias else "sell"
    commodity = get_commodity(cur, symbol)
    qty = max(D(rng.choice([5, 10, 15, 20, 25])), commodity["minimum_order_quantity"])
    if side == "buy" and trader["cash_balance"] < last_price(cur, commodity["commodity_id"]) * qty * D("1.05"):
        side = "sell"
    if rng.random() < 0.7:
        result = place_order(cur, trader["trader_id"], symbol, side, "market", qty)
    else:
        ltp = last_price(cur, commodity["commodity_id"])
        offset = quote_step(commodity, ltp) * rng.choice([1, 2])
        price = ltp - offset if side == "buy" else ltp + offset
        result = place_order(cur, trader["trader_id"], symbol, side, "limit", qty, price)
    return {"kind": "order", **result}
