BEGIN;

INSERT INTO users (email, phone, password_hash, full_name, role)
VALUES
    ('admin@ncdex-sim.local', '+919999000001', 'seed-only-replace-before-use', 'NCDEX Administrator', 'administrator'),
    ('yash@ncdex-sim.local', '+919999000002', 'seed-only-replace-before-use', 'Yash Patel', 'trader'),
    ('soham@ncdex-sim.local', '+919999000003', 'seed-only-replace-before-use', 'Soham Prajapati', 'trader'),
    ('bhumit@ncdex-sim.local', '+919999000004', 'seed-only-replace-before-use', 'Bhumit Sethi', 'trader');

INSERT INTO brokers (name, logo_url, contact_info)
VALUES ('NCDEX Simulation Desk', NULL, '{"email":"desk@ncdex-sim.local"}');

INSERT INTO traders (user_id, broker_id, experience_level)
SELECT u.user_id, b.broker_id, 'student'
FROM users u CROSS JOIN brokers b
WHERE u.role = 'trader';

INSERT INTO categories (name, slug) VALUES
    ('Agriculture', 'agriculture'),
    ('Spices', 'spices'),
    ('Oilseeds', 'oilseeds');

INSERT INTO commodities (category_id, name, symbol, description, unit, tick_size, minimum_order_quantity)
SELECT c.category_id, x.name, x.symbol, x.description, x.unit, x.tick_size, x.minimum_order_quantity
FROM (VALUES
    ('agriculture', 'Cotton', 'COTTON', 'Cotton futures simulation contract', 'bale', 0.05::numeric, 1::numeric),
    ('spices', 'Jeera', 'JEERA', 'Cumin seed futures simulation contract', 'quintal', 0.25::numeric, 1::numeric),
    ('oilseeds', 'Soybean', 'SOYBEAN', 'Soybean futures simulation contract', 'quintal', 0.10::numeric, 1::numeric)
) AS x(slug, name, symbol, description, unit, tick_size, minimum_order_quantity)
JOIN categories c ON c.slug = x.slug;

-- Small, deterministic starter series for local development and Power BI smoke tests.
INSERT INTO market_prices (commodity_id, price_date, open_price, high_price, low_price, close_price, volume, source)
SELECT c.commodity_id, d::date,
       base + ((EXTRACT(DOY FROM d)::int % 5) * 2),
       base + ((EXTRACT(DOY FROM d)::int % 5) * 2) + 9,
       base - 4 + ((EXTRACT(DOY FROM d)::int % 5) * 2),
       base + ((EXTRACT(DOY FROM d)::int % 5) * 2) + 4,
       100 + (EXTRACT(DOY FROM d)::int % 7) * 25,
       'seed'
FROM (VALUES ('COTTON', 7200::numeric), ('JEERA', 24500::numeric), ('SOYBEAN', 4600::numeric)) AS x(symbol, base)
JOIN commodities c ON c.symbol = x.symbol
CROSS JOIN generate_series(date '2026-09-01', date '2026-09-14', interval '1 day') AS d;

COMMIT;

