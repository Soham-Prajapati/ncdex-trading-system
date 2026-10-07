BEGIN;

-- Rich, repeatable demo data for the single-page Power BI report.
-- It is intentionally synthetic: NCDEX production trading APIs are not assumed.

INSERT INTO market_prices (
    commodity_id, price_date, open_price, high_price, low_price, close_price, volume, source
)
SELECT
    c.commodity_id,
    d::date,
    ROUND((x.base + (((EXTRACT(DOY FROM d)::int * 7 + x.seed) % 31) - 15) * x.step)::numeric, 6),
    ROUND((x.base + (((EXTRACT(DOY FROM d)::int * 7 + x.seed) % 31) - 15) * x.step + x.range)::numeric, 6),
    ROUND((x.base + (((EXTRACT(DOY FROM d)::int * 7 + x.seed) % 31) - 15) * x.step - x.range * 0.65)::numeric, 6),
    ROUND((x.base + (((EXTRACT(DOY FROM d)::int * 7 + x.seed) % 31) - 15) * x.step + (((EXTRACT(DOY FROM d)::int + x.seed) % 5) - 2) * x.step)::numeric, 6),
    (1800 + ((EXTRACT(DOY FROM d)::int * 113 + x.seed * 97) % 4200))::numeric,
    'synthetic-demo'
FROM generate_series(date '2026-07-01', date '2026-10-07', interval '1 day') AS d
CROSS JOIN (VALUES
    ('COTTON', 7200::numeric, 6::numeric, 28::numeric, 11),
    ('JEERA', 24500::numeric, 18::numeric, 90::numeric, 23),
    ('SOYBEAN', 4600::numeric, 4::numeric, 20::numeric, 37)
) AS x(symbol, base, step, range, seed)
JOIN commodities c ON c.symbol = x.symbol
ON CONFLICT (commodity_id, price_date) DO NOTHING;

WITH price_rows AS (
    SELECT
        mp.commodity_id,
        mp.price_date,
        mp.close_price,
        ROW_NUMBER() OVER (PARTITION BY mp.price_date ORDER BY mp.commodity_id) AS commodity_rank
    FROM market_prices mp
    WHERE mp.price_date BETWEEN date '2026-09-15' AND date '2026-10-07'
), trader_rows AS (
    SELECT trader_id, ROW_NUMBER() OVER (ORDER BY trader_id) AS trader_rank
    FROM traders
    WHERE status = 'active'
), pairs AS (
    SELECT
        p.commodity_id,
        p.price_date,
        p.close_price,
        buyer.trader_id AS buyer_trader_id,
        seller.trader_id AS seller_trader_id,
        (p.price_date::timestamp + interval '10 hours' + (p.commodity_rank * interval '1 minute')) AS submitted_at,
        (5 + ((EXTRACT(DOY FROM p.price_date)::int + p.commodity_rank * 3) % 20))::numeric AS quantity
    FROM price_rows p
    JOIN trader_rows buyer ON buyer.trader_rank = ((EXTRACT(DOY FROM p.price_date)::int + p.commodity_rank) % 3) + 1
    JOIN trader_rows seller ON seller.trader_rank = ((EXTRACT(DOY FROM p.price_date)::int + p.commodity_rank + 1) % 3) + 1
    WHERE buyer.trader_id <> seller.trader_id
), inserted_orders AS (
    INSERT INTO orders (
        trader_id, commodity_id, side, order_type, price, quantity, filled_quantity, status, submitted_at, updated_at
    )
    SELECT buyer_trader_id, commodity_id, 'buy'::order_side, 'limit'::order_type, close_price, quantity, quantity, 'filled'::order_status, submitted_at, submitted_at
    FROM pairs
    UNION ALL
    SELECT seller_trader_id, commodity_id, 'sell'::order_side, 'limit'::order_type, close_price, quantity, quantity, 'filled'::order_status, submitted_at, submitted_at
    FROM pairs
    RETURNING order_id, trader_id, commodity_id, side, price, quantity, submitted_at
)
INSERT INTO trades (buy_order_id, sell_order_id, commodity_id, price, quantity, status, trade_time)
SELECT b.order_id, s.order_id, b.commodity_id, b.price, b.quantity, 'settled'::trade_status, b.submitted_at + interval '30 seconds'
FROM inserted_orders b
JOIN inserted_orders s ON s.commodity_id = b.commodity_id AND s.submitted_at = b.submitted_at
WHERE b.side = 'buy' AND s.side = 'sell'
  AND NOT EXISTS (
      SELECT 1 FROM trades t WHERE t.buy_order_id = b.order_id AND t.sell_order_id = s.order_id
  );

INSERT INTO transactions (trade_id, trader_id, transaction_type, amount, reference, transaction_time)
SELECT t.trade_id, o.trader_id, CASE WHEN o.side = 'buy' THEN 'trade_debit'::transaction_type ELSE 'trade_credit'::transaction_type END,
       t.price * t.quantity, 'rich-demo-seed', t.trade_time
FROM trades t
JOIN orders o ON o.order_id IN (t.buy_order_id, t.sell_order_id)
WHERE NOT EXISTS (
    SELECT 1 FROM transactions x WHERE x.trade_id = t.trade_id AND x.trader_id = o.trader_id
);

INSERT INTO portfolio (trader_id, commodity_id, quantity, average_price, current_price)
SELECT
    tr.trader_id,
    c.commodity_id,
    (12 + ((ROW_NUMBER() OVER (ORDER BY tr.trader_id, c.commodity_id) * 7) % 95))::numeric,
    latest.close_price * (0.96 + ((ROW_NUMBER() OVER (ORDER BY tr.trader_id, c.commodity_id) % 9) * 0.01)),
    latest.close_price
FROM traders tr
CROSS JOIN commodities c
JOIN LATERAL (
    SELECT close_price FROM market_prices mp
    WHERE mp.commodity_id = c.commodity_id ORDER BY price_date DESC LIMIT 1
) latest ON true
ON CONFLICT (trader_id, commodity_id)
DO UPDATE SET
    quantity = EXCLUDED.quantity,
    average_price = EXCLUDED.average_price,
    current_price = EXCLUDED.current_price,
    updated_at = now();

INSERT INTO events (event_type, actor_user_id, entity_type, entity_id, data, created_at)
SELECT 'trade_executed'::event_type, admin.user_id, 'trade', t.trade_id,
       jsonb_build_object('source', 'rich-demo-seed', 'price', t.price, 'quantity', t.quantity), t.trade_time
FROM trades t
CROSS JOIN (SELECT user_id FROM users WHERE email = 'admin@ncdex-sim.local' LIMIT 1) admin
WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.entity_id = t.trade_id AND e.entity_type = 'trade');

COMMIT;

