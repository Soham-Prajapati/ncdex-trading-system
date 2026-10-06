BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TYPE user_role AS ENUM ('trader', 'administrator');
CREATE TYPE account_status AS ENUM ('active', 'suspended', 'pending');
CREATE TYPE order_side AS ENUM ('buy', 'sell');
CREATE TYPE order_type AS ENUM ('market', 'limit');
CREATE TYPE order_status AS ENUM ('open', 'partially_filled', 'filled', 'cancelled', 'rejected');
CREATE TYPE trade_status AS ENUM ('executed', 'settled', 'reversed');
CREATE TYPE transaction_type AS ENUM ('deposit', 'withdrawal', 'trade_debit', 'trade_credit', 'fee', 'adjustment');
CREATE TYPE event_type AS ENUM ('order_submitted', 'order_matched', 'trade_executed', 'portfolio_updated', 'user_created', 'commodity_updated');

CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    phone TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role user_role NOT NULL DEFAULT 'trader',
    status account_status NOT NULL DEFAULT 'active',
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE brokers (
    broker_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    logo_url TEXT,
    contact_info JSONB NOT NULL DEFAULT '{}'::jsonb,
    status account_status NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE traders (
    trader_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL UNIQUE REFERENCES users(user_id),
    broker_id UUID REFERENCES brokers(broker_id),
    experience_level TEXT,
    status account_status NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE categories (
    category_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id UUID REFERENCES categories(category_id),
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE commodities (
    commodity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id UUID NOT NULL REFERENCES categories(category_id),
    name TEXT NOT NULL,
    symbol TEXT NOT NULL UNIQUE,
    description TEXT,
    unit TEXT NOT NULL,
    tick_size NUMERIC(18, 6) NOT NULL CHECK (tick_size > 0),
    minimum_order_quantity NUMERIC(18, 6) NOT NULL CHECK (minimum_order_quantity > 0),
    status account_status NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE orders (
    order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trader_id UUID NOT NULL REFERENCES traders(trader_id),
    commodity_id UUID NOT NULL REFERENCES commodities(commodity_id),
    side order_side NOT NULL,
    order_type order_type NOT NULL,
    price NUMERIC(18, 6) CHECK (price IS NULL OR price > 0),
    quantity NUMERIC(18, 6) NOT NULL CHECK (quantity > 0),
    filled_quantity NUMERIC(18, 6) NOT NULL DEFAULT 0 CHECK (filled_quantity >= 0 AND filled_quantity <= quantity),
    status order_status NOT NULL DEFAULT 'open',
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((order_type = 'market' AND price IS NULL) OR (order_type = 'limit' AND price IS NOT NULL))
);

CREATE TABLE trades (
    trade_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    buy_order_id UUID NOT NULL REFERENCES orders(order_id),
    sell_order_id UUID NOT NULL REFERENCES orders(order_id),
    commodity_id UUID NOT NULL REFERENCES commodities(commodity_id),
    price NUMERIC(18, 6) NOT NULL CHECK (price > 0),
    quantity NUMERIC(18, 6) NOT NULL CHECK (quantity > 0),
    status trade_status NOT NULL DEFAULT 'executed',
    trade_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (buy_order_id <> sell_order_id)
);

CREATE TABLE portfolio (
    portfolio_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trader_id UUID NOT NULL REFERENCES traders(trader_id),
    commodity_id UUID NOT NULL REFERENCES commodities(commodity_id),
    quantity NUMERIC(18, 6) NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    average_price NUMERIC(18, 6) NOT NULL DEFAULT 0 CHECK (average_price >= 0),
    current_price NUMERIC(18, 6) NOT NULL DEFAULT 0 CHECK (current_price >= 0),
    current_value NUMERIC(20, 6) GENERATED ALWAYS AS (quantity * current_price) STORED,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (trader_id, commodity_id)
);

CREATE TABLE transactions (
    transaction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trade_id UUID REFERENCES trades(trade_id),
    trader_id UUID NOT NULL REFERENCES traders(trader_id),
    transaction_type transaction_type NOT NULL,
    amount NUMERIC(20, 6) NOT NULL CHECK (amount >= 0),
    reference TEXT,
    transaction_time TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE market_prices (
    market_price_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    commodity_id UUID NOT NULL REFERENCES commodities(commodity_id),
    price_date DATE NOT NULL,
    open_price NUMERIC(18, 6) NOT NULL CHECK (open_price > 0),
    high_price NUMERIC(18, 6) NOT NULL CHECK (high_price >= open_price),
    low_price NUMERIC(18, 6) NOT NULL CHECK (low_price > 0 AND low_price <= open_price),
    close_price NUMERIC(18, 6) NOT NULL CHECK (close_price > 0),
    volume NUMERIC(20, 6) NOT NULL DEFAULT 0 CHECK (volume >= 0),
    source TEXT NOT NULL DEFAULT 'seed',
    UNIQUE (commodity_id, price_date)
);

CREATE TABLE events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type event_type NOT NULL,
    actor_user_id UUID REFERENCES users(user_id),
    entity_type TEXT NOT NULL,
    entity_id UUID,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE reports (
    report_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reporter_user_id UUID NOT NULL REFERENCES users(user_id),
    admin_user_id UUID REFERENCES users(user_id),
    target_type TEXT NOT NULL,
    target_id UUID,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'reviewing', 'resolved', 'dismissed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX idx_orders_book ON orders (commodity_id, side, status, price, submitted_at);
CREATE INDEX idx_orders_trader ON orders (trader_id, submitted_at DESC);
CREATE INDEX idx_trades_commodity_time ON trades (commodity_id, trade_time DESC);
CREATE INDEX idx_trades_buy_order ON trades (buy_order_id);
CREATE INDEX idx_trades_sell_order ON trades (sell_order_id);
CREATE INDEX idx_transactions_trader_time ON transactions (trader_id, transaction_time DESC);
CREATE INDEX idx_market_prices_commodity_date ON market_prices (commodity_id, price_date DESC);
CREATE INDEX idx_events_created_at ON events (created_at DESC);

CREATE VIEW analytics.v_market_prices AS
SELECT
    mp.market_price_id,
    mp.price_date,
    c.commodity_id,
    c.symbol,
    c.name AS commodity_name,
    cat.name AS category_name,
    c.unit,
    mp.open_price,
    mp.high_price,
    mp.low_price,
    mp.close_price,
    mp.volume,
    mp.source,
    ROUND(((mp.close_price - mp.open_price) / NULLIF(mp.open_price, 0) * 100)::numeric, 4) AS daily_change_pct
FROM market_prices mp
JOIN commodities c ON c.commodity_id = mp.commodity_id
JOIN categories cat ON cat.category_id = c.category_id;

CREATE VIEW analytics.v_trade_facts AS
SELECT
    t.trade_id,
    t.trade_time::date AS trade_date,
    t.trade_time,
    c.symbol,
    c.name AS commodity_name,
    cat.name AS category_name,
    bu.user_id AS buyer_user_id,
    bu.full_name AS buyer_name,
    su.user_id AS seller_user_id,
    su.full_name AS seller_name,
    t.price,
    t.quantity,
    (t.price * t.quantity)::numeric(20, 6) AS notional_value,
    t.status
FROM trades t
JOIN commodities c ON c.commodity_id = t.commodity_id
JOIN categories cat ON cat.category_id = c.category_id
JOIN orders bo ON bo.order_id = t.buy_order_id
JOIN traders bt ON bt.trader_id = bo.trader_id
JOIN users bu ON bu.user_id = bt.user_id
JOIN orders so ON so.order_id = t.sell_order_id
JOIN traders st ON st.trader_id = so.trader_id
JOIN users su ON su.user_id = st.user_id;

CREATE VIEW analytics.v_daily_market_summary AS
SELECT
    trade_date,
    symbol,
    commodity_name,
    COUNT(*)::bigint AS trade_count,
    SUM(quantity)::numeric(20, 6) AS traded_quantity,
    SUM(notional_value)::numeric(20, 6) AS traded_notional,
    ROUND(MIN(price)::numeric, 6) AS low_trade_price,
    ROUND(MAX(price)::numeric, 6) AS high_trade_price,
    ROUND((SUM(price * quantity) / NULLIF(SUM(quantity), 0))::numeric, 6) AS volume_weighted_average_price
FROM analytics.v_trade_facts
WHERE status IN ('executed', 'settled')
GROUP BY trade_date, symbol, commodity_name;

CREATE VIEW analytics.v_portfolio_snapshot AS
SELECT
    p.portfolio_id,
    u.user_id,
    u.full_name AS trader_name,
    u.email,
    c.symbol,
    c.name AS commodity_name,
    p.quantity,
    p.average_price,
    p.current_price,
    p.current_value,
    ((p.current_price - p.average_price) * p.quantity)::numeric(20, 6) AS unrealized_pnl,
    p.updated_at
FROM portfolio p
JOIN traders tr ON tr.trader_id = p.trader_id
JOIN users u ON u.user_id = tr.user_id
JOIN commodities c ON c.commodity_id = p.commodity_id;

CREATE VIEW analytics.v_order_activity AS
SELECT
    o.order_id,
    o.submitted_at::date AS order_date,
    o.submitted_at,
    u.full_name AS trader_name,
    u.email,
    c.symbol,
    c.name AS commodity_name,
    o.side,
    o.order_type,
    o.price,
    o.quantity,
    o.filled_quantity,
    o.status,
    ROUND((o.filled_quantity / NULLIF(o.quantity, 0) * 100)::numeric, 4) AS fill_rate_pct
FROM orders o
JOIN traders tr ON tr.trader_id = o.trader_id
JOIN users u ON u.user_id = tr.user_id
JOIN commodities c ON c.commodity_id = o.commodity_id;

COMMIT;

