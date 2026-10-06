BEGIN;

WITH participants AS (
    SELECT
        (SELECT trader_id FROM traders tr JOIN users u ON u.user_id = tr.user_id WHERE u.email = 'yash@ncdex-sim.local') AS buyer_trader_id,
        (SELECT trader_id FROM traders tr JOIN users u ON u.user_id = tr.user_id WHERE u.email = 'soham@ncdex-sim.local') AS seller_trader_id,
        (SELECT commodity_id FROM commodities WHERE symbol = 'COTTON') AS commodity_id
),
buy_order AS (
    INSERT INTO orders (trader_id, commodity_id, side, order_type, price, quantity, filled_quantity, status)
    SELECT buyer_trader_id, commodity_id, 'buy', 'limit', 7260, 10, 10, 'filled' FROM participants
    RETURNING order_id, trader_id, commodity_id
),
sell_order AS (
    INSERT INTO orders (trader_id, commodity_id, side, order_type, price, quantity, filled_quantity, status)
    SELECT seller_trader_id, commodity_id, 'sell', 'limit', 7260, 10, 10, 'filled' FROM participants
    RETURNING order_id, trader_id, commodity_id
),
new_trade AS (
    INSERT INTO trades (buy_order_id, sell_order_id, commodity_id, price, quantity, status)
    SELECT b.order_id, s.order_id, b.commodity_id, 7260, 10, 'settled'
    FROM buy_order b CROSS JOIN sell_order s
    RETURNING trade_id, commodity_id, price, quantity
)
INSERT INTO transactions (trade_id, trader_id, transaction_type, amount, reference)
SELECT nt.trade_id, b.trader_id, 'trade_debit'::transaction_type, nt.price * nt.quantity, 'demo-trade-buy'
FROM new_trade nt CROSS JOIN buy_order b
UNION ALL
SELECT nt.trade_id, s.trader_id, 'trade_credit'::transaction_type, nt.price * nt.quantity, 'demo-trade-sell'
FROM new_trade nt CROSS JOIN sell_order s;

INSERT INTO portfolio (trader_id, commodity_id, quantity, average_price, current_price)
SELECT tr.trader_id, c.commodity_id, 10, 7260, 7280
FROM traders tr
JOIN users u ON u.user_id = tr.user_id AND u.email = 'yash@ncdex-sim.local'
CROSS JOIN commodities c
WHERE c.symbol = 'COTTON'
ON CONFLICT (trader_id, commodity_id)
DO UPDATE SET quantity = EXCLUDED.quantity, average_price = EXCLUDED.average_price,
              current_price = EXCLUDED.current_price, updated_at = now();

INSERT INTO events (event_type, actor_user_id, entity_type, entity_id, data)
SELECT 'trade_executed', u.user_id, 'trade', t.trade_id,
       jsonb_build_object('symbol', c.symbol, 'price', t.price, 'quantity', t.quantity)
FROM trades t
JOIN commodities c ON c.commodity_id = t.commodity_id
JOIN users u ON u.email = 'admin@ncdex-sim.local'
WHERE t.status = 'settled'
  AND NOT EXISTS (
      SELECT 1 FROM events e WHERE e.entity_type = 'trade' AND e.entity_id = t.trade_id
  );

COMMIT;
