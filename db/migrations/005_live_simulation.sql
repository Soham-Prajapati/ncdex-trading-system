-- Live simulation: trader profiles with SCD2 history, intraday price ticks,
-- futures-style net positions, and analytics views for the faculty demo.

ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'profile_updated';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'market_news';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'order_cancelled';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'price_moved';

BEGIN;

-- Descriptive trader profile attributes (tracked by SCD2) plus a cash balance
-- (a fast-changing fact, deliberately NOT versioned).
ALTER TABLE traders
    ADD COLUMN IF NOT EXISTS trader_type TEXT NOT NULL DEFAULT 'Student trader',
    ADD COLUMN IF NOT EXISTS organisation TEXT,
    ADD COLUMN IF NOT EXISTS address_line TEXT,
    ADD COLUMN IF NOT EXISTS city TEXT,
    ADD COLUMN IF NOT EXISTS state TEXT,
    ADD COLUMN IF NOT EXISTS pincode TEXT,
    ADD COLUMN IF NOT EXISTS risk_appetite TEXT NOT NULL DEFAULT 'Moderate',
    ADD COLUMN IF NOT EXISTS kyc_tier TEXT NOT NULL DEFAULT 'Basic',
    ADD COLUMN IF NOT EXISTS strategy TEXT,
    ADD COLUMN IF NOT EXISTS avatar_color TEXT NOT NULL DEFAULT '#14a78b',
    ADD COLUMN IF NOT EXISTS is_persona BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS is_market_maker BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS cash_balance NUMERIC(20, 6) NOT NULL DEFAULT 1000000,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Futures positions may be short; track realised P&L alongside the open position.
ALTER TABLE portfolio DROP CONSTRAINT IF EXISTS portfolio_quantity_check;
ALTER TABLE portfolio ADD COLUMN IF NOT EXISTS realized_pnl NUMERIC(20, 6) NOT NULL DEFAULT 0;

-- SCD Type 2 history of the trader profile. Same contract as user_history:
-- current row has valid_to = infinity and current_flag = 'Y'.
CREATE TABLE IF NOT EXISTS trader_history (
    trader_history_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    trader_id UUID NOT NULL REFERENCES traders(trader_id),
    broker_id UUID REFERENCES brokers(broker_id),
    trader_type TEXT NOT NULL,
    organisation TEXT,
    address_line TEXT,
    city TEXT,
    state TEXT,
    pincode TEXT,
    risk_appetite TEXT NOT NULL,
    kyc_tier TEXT NOT NULL,
    experience_level TEXT,
    status account_status NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to TIMESTAMPTZ NOT NULL DEFAULT 'infinity'::timestamptz,
    is_current BOOLEAN GENERATED ALWAYS AS (valid_to = 'infinity'::timestamptz) STORED,
    current_flag CHAR(1) GENERATED ALWAYS AS (CASE WHEN valid_to = 'infinity'::timestamptz THEN 'Y' ELSE 'N' END) STORED,
    changed_by UUID REFERENCES users(user_id),
    change_reason TEXT NOT NULL DEFAULT 'initial version',
    UNIQUE (trader_id, valid_from)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_trader_history_current
    ON trader_history (trader_id) WHERE valid_to = 'infinity'::timestamptz;

CREATE OR REPLACE FUNCTION scd2_record_trader()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    version_at TIMESTAMPTZ := clock_timestamp();
    actor UUID := NULLIF(current_setting('app.actor_user_id', true), '')::uuid;
    reason TEXT := COALESCE(NULLIF(current_setting('app.change_reason', true), ''), 'trader profile update');
BEGIN
    IF TG_OP = 'UPDATE' AND
       ROW(OLD.broker_id, OLD.trader_type, OLD.organisation, OLD.address_line, OLD.city, OLD.state, OLD.pincode,
           OLD.risk_appetite, OLD.kyc_tier, OLD.experience_level, OLD.status)
       IS NOT DISTINCT FROM
       ROW(NEW.broker_id, NEW.trader_type, NEW.organisation, NEW.address_line, NEW.city, NEW.state, NEW.pincode,
           NEW.risk_appetite, NEW.kyc_tier, NEW.experience_level, NEW.status) THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        UPDATE trader_history SET valid_to = version_at
        WHERE trader_id = NEW.trader_id AND valid_to = 'infinity'::timestamptz;
    END IF;
    INSERT INTO trader_history (trader_id, broker_id, trader_type, organisation, address_line, city, state, pincode,
                                risk_appetite, kyc_tier, experience_level, status, valid_from, valid_to, changed_by, change_reason)
    VALUES (NEW.trader_id, NEW.broker_id, NEW.trader_type, NEW.organisation, NEW.address_line, NEW.city, NEW.state, NEW.pincode,
            NEW.risk_appetite, NEW.kyc_tier, NEW.experience_level, NEW.status, version_at, 'infinity'::timestamptz, actor,
            CASE WHEN TG_OP = 'INSERT' THEN 'initial version' ELSE reason END);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_scd2_trader ON traders;
CREATE TRIGGER trg_scd2_trader
AFTER INSERT OR UPDATE OF broker_id, trader_type, organisation, address_line, city, state, pincode,
    risk_appetite, kyc_tier, experience_level, status ON traders
FOR EACH ROW EXECUTE FUNCTION scd2_record_trader();

-- Initial versions for traders that existed before this migration.
INSERT INTO trader_history (trader_id, broker_id, trader_type, organisation, address_line, city, state, pincode,
                            risk_appetite, kyc_tier, experience_level, status, valid_from, change_reason)
SELECT t.trader_id, t.broker_id, t.trader_type, t.organisation, t.address_line, t.city, t.state, t.pincode,
       t.risk_appetite, t.kyc_tier, t.experience_level, t.status, t.created_at, 'initial version'
FROM traders t
WHERE NOT EXISTS (SELECT 1 FROM trader_history h WHERE h.trader_id = t.trader_id);

-- Every execution leaves an intraday tick with the reason the price moved.
CREATE TABLE IF NOT EXISTS price_ticks (
    tick_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    commodity_id UUID NOT NULL REFERENCES commodities(commodity_id),
    trade_id UUID REFERENCES trades(trade_id),
    aggressor_trader_id UUID REFERENCES traders(trader_id),
    aggressor_side order_side,
    previous_price NUMERIC(18, 6),
    price NUMERIC(18, 6) NOT NULL CHECK (price > 0),
    quantity NUMERIC(18, 6) NOT NULL DEFAULT 0,
    narrative TEXT,
    tick_time TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS idx_price_ticks_commodity_time ON price_ticks (commodity_id, tick_time DESC);
CREATE INDEX IF NOT EXISTS idx_events_created_at_id ON events (created_at DESC, event_id);

-- Analytics views -----------------------------------------------------------

CREATE OR REPLACE VIEW analytics.v_trader_history AS
SELECT h.trader_history_id, h.trader_id, u.full_name AS trader_name, u.email,
       h.trader_type, h.organisation, h.address_line, h.city, h.state, h.pincode,
       h.risk_appetite, h.kyc_tier, h.experience_level, h.status, b.name AS broker_name,
       h.valid_from AS from_date, h.valid_to AS to_date, h.valid_from, h.valid_to,
       h.is_current, h.current_flag, h.change_reason,
       ROW_NUMBER() OVER (PARTITION BY h.trader_id ORDER BY h.valid_from) AS version_no
FROM trader_history h
JOIN traders t ON t.trader_id = h.trader_id
JOIN users u ON u.user_id = t.user_id
LEFT JOIN brokers b ON b.broker_id = h.broker_id;

-- One row per SCD2 version across every tracked dimension, with a readable
-- "field: old → new" description of what that version changed.
CREATE OR REPLACE VIEW analytics.v_scd_change_log AS
WITH versions AS (
    SELECT 'Trader profile'::text AS dimension, h.trader_id AS entity_id, u.full_name AS entity_name,
           h.valid_from, h.valid_to, h.current_flag, h.change_reason,
           jsonb_build_object('address', h.address_line, 'city', h.city, 'state', h.state, 'pincode', h.pincode,
                              'trader_type', h.trader_type, 'organisation', h.organisation,
                              'risk_appetite', h.risk_appetite, 'kyc_tier', h.kyc_tier,
                              'experience', h.experience_level, 'status', h.status, 'broker', b.name) AS attrs
    FROM trader_history h
    JOIN traders t ON t.trader_id = h.trader_id
    JOIN users u ON u.user_id = t.user_id
    LEFT JOIN brokers b ON b.broker_id = h.broker_id
    UNION ALL
    SELECT 'User account', h.user_id, h.full_name, h.valid_from, h.valid_to, h.current_flag, h.change_reason,
           jsonb_build_object('email', h.email, 'phone', h.phone, 'full_name', h.full_name,
                              'role', h.role, 'status', h.status)
    FROM user_history h
    UNION ALL
    SELECT 'Commodity', h.commodity_id, h.symbol, h.valid_from, h.valid_to, h.current_flag, h.change_reason,
           jsonb_build_object('name', h.name, 'description', h.description, 'unit', h.unit,
                              'tick_size', trim_scale(h.tick_size), 'min_order_qty', trim_scale(h.minimum_order_quantity), 'status', h.status)
    FROM commodity_history h
), sequenced AS (
    SELECT v.*,
           ROW_NUMBER() OVER w AS version_no,
           LAG(attrs) OVER w AS previous_attrs
    FROM versions v
    WINDOW w AS (PARTITION BY dimension, entity_id ORDER BY valid_from)
)
SELECT dimension, entity_id, entity_name, version_no,
       valid_from AS from_date, valid_to AS to_date, current_flag, change_reason,
       COALESCE((
           SELECT string_agg(a.key || ': ' || COALESCE(previous_attrs ->> a.key, '∅') || ' → ' || COALESCE(a.value #>> '{}', '∅'), '; ' ORDER BY a.key)
           FROM jsonb_each(attrs) a
           WHERE previous_attrs IS NOT NULL AND previous_attrs -> a.key IS DISTINCT FROM a.value
       ), 'initial version') AS changed_fields,
       attrs::text AS snapshot
FROM sequenced;

CREATE OR REPLACE VIEW analytics.v_price_ticks AS
SELECT pt.tick_id, pt.tick_time, pt.tick_time::date AS tick_date, c.symbol, c.name AS commodity_name,
       u.full_name AS aggressor_name, t.trader_type AS aggressor_type, pt.aggressor_side,
       pt.previous_price, pt.price, pt.quantity,
       (pt.price - pt.previous_price) AS price_change,
       ROUND(((pt.price - pt.previous_price) / NULLIF(pt.previous_price, 0) * 100)::numeric, 4) AS price_change_pct,
       pt.narrative
FROM price_ticks pt
JOIN commodities c ON c.commodity_id = pt.commodity_id
LEFT JOIN traders t ON t.trader_id = pt.aggressor_trader_id
LEFT JOIN users u ON u.user_id = t.user_id;

CREATE OR REPLACE VIEW analytics.v_trader_profiles AS
SELECT t.trader_id, u.full_name AS trader_name, u.email, t.trader_type, t.organisation,
       t.address_line, t.city, t.state, t.pincode, t.risk_appetite, t.kyc_tier, t.experience_level,
       t.strategy, t.status, t.is_market_maker, t.cash_balance,
       COALESCE(SUM(p.current_value), 0) AS position_value,
       COALESCE(SUM((p.current_price - p.average_price) * p.quantity), 0) AS unrealized_pnl,
       COALESCE(SUM(p.realized_pnl), 0) AS realized_pnl,
       (SELECT COUNT(*) FROM trader_history h WHERE h.trader_id = t.trader_id) AS profile_versions
FROM traders t
JOIN users u ON u.user_id = t.user_id
LEFT JOIN portfolio p ON p.trader_id = t.trader_id
GROUP BY t.trader_id, u.full_name, u.email;

CREATE OR REPLACE VIEW analytics.v_portfolio_snapshot AS
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
    p.updated_at,
    p.realized_pnl,
    tr.trader_type
FROM portfolio p
JOIN traders tr ON tr.trader_id = p.trader_id
JOIN users u ON u.user_id = tr.user_id
JOIN commodities c ON c.commodity_id = p.commodity_id;

COMMIT;
