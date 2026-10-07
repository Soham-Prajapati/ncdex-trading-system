BEGIN;

-- Align the physical SCD2 representation with the project reference:
-- closed versions have a real to_date; the current version ends at infinity
-- and is explicitly marked with current_flag = 'Y'.
DROP VIEW IF EXISTS analytics.v_commodity_history;
DROP VIEW IF EXISTS analytics.v_user_history;

ALTER TABLE commodity_history DROP COLUMN is_current;
ALTER TABLE user_history DROP COLUMN is_current;

UPDATE commodity_history SET valid_to = 'infinity'::timestamptz WHERE valid_to IS NULL;
UPDATE user_history SET valid_to = 'infinity'::timestamptz WHERE valid_to IS NULL;

ALTER TABLE commodity_history ALTER COLUMN valid_to SET DEFAULT 'infinity'::timestamptz;
ALTER TABLE user_history ALTER COLUMN valid_to SET DEFAULT 'infinity'::timestamptz;

ALTER TABLE commodity_history
    ADD COLUMN is_current BOOLEAN GENERATED ALWAYS AS (valid_to = 'infinity'::timestamptz) STORED,
    ADD COLUMN current_flag CHAR(1) GENERATED ALWAYS AS (CASE WHEN valid_to = 'infinity'::timestamptz THEN 'Y' ELSE 'N' END) STORED;

ALTER TABLE user_history
    ADD COLUMN is_current BOOLEAN GENERATED ALWAYS AS (valid_to = 'infinity'::timestamptz) STORED,
    ADD COLUMN current_flag CHAR(1) GENERATED ALWAYS AS (CASE WHEN valid_to = 'infinity'::timestamptz THEN 'Y' ELSE 'N' END) STORED;

DROP INDEX IF EXISTS uq_commodity_history_current;
DROP INDEX IF EXISTS uq_user_history_current;
CREATE UNIQUE INDEX uq_commodity_history_current ON commodity_history (commodity_id) WHERE valid_to = 'infinity'::timestamptz;
CREATE UNIQUE INDEX uq_user_history_current ON user_history (user_id) WHERE valid_to = 'infinity'::timestamptz;

CREATE OR REPLACE FUNCTION scd2_record_commodity()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    version_at TIMESTAMPTZ := clock_timestamp();
    actor UUID := NULLIF(current_setting('app.actor_user_id', true), '')::uuid;
    reason TEXT := COALESCE(NULLIF(current_setting('app.change_reason', true), ''), 'commodity update');
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO commodity_history (commodity_id, category_id, name, symbol, description, unit, tick_size, minimum_order_quantity, status, valid_from, valid_to, changed_by, change_reason)
        VALUES (NEW.commodity_id, NEW.category_id, NEW.name, NEW.symbol, NEW.description, NEW.unit, NEW.tick_size, NEW.minimum_order_quantity, NEW.status, version_at, 'infinity'::timestamptz, actor, 'initial version');
        RETURN NEW;
    END IF;
    IF ROW(OLD.category_id, OLD.name, OLD.symbol, OLD.description, OLD.unit, OLD.tick_size, OLD.minimum_order_quantity, OLD.status)
       IS NOT DISTINCT FROM ROW(NEW.category_id, NEW.name, NEW.symbol, NEW.description, NEW.unit, NEW.tick_size, NEW.minimum_order_quantity, NEW.status) THEN
        RETURN NEW;
    END IF;
    UPDATE commodity_history SET valid_to = version_at WHERE commodity_id = NEW.commodity_id AND valid_to = 'infinity'::timestamptz;
    INSERT INTO commodity_history (commodity_id, category_id, name, symbol, description, unit, tick_size, minimum_order_quantity, status, valid_from, valid_to, changed_by, change_reason)
    VALUES (NEW.commodity_id, NEW.category_id, NEW.name, NEW.symbol, NEW.description, NEW.unit, NEW.tick_size, NEW.minimum_order_quantity, NEW.status, version_at, 'infinity'::timestamptz, actor, reason);
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION scd2_record_user()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    version_at TIMESTAMPTZ := clock_timestamp();
    actor UUID := NULLIF(current_setting('app.actor_user_id', true), '')::uuid;
    reason TEXT := COALESCE(NULLIF(current_setting('app.change_reason', true), ''), 'user update');
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO user_history (user_id, email, phone, full_name, role, status, valid_from, valid_to, changed_by, change_reason)
        VALUES (NEW.user_id, NEW.email, NEW.phone, NEW.full_name, NEW.role, NEW.status, version_at, 'infinity'::timestamptz, actor, 'initial version');
        RETURN NEW;
    END IF;
    IF ROW(OLD.email, OLD.phone, OLD.full_name, OLD.role, OLD.status)
       IS NOT DISTINCT FROM ROW(NEW.email, NEW.phone, NEW.full_name, NEW.role, NEW.status) THEN
        RETURN NEW;
    END IF;
    UPDATE user_history SET valid_to = version_at WHERE user_id = NEW.user_id AND valid_to = 'infinity'::timestamptz;
    INSERT INTO user_history (user_id, email, phone, full_name, role, status, valid_from, valid_to, changed_by, change_reason)
    VALUES (NEW.user_id, NEW.email, NEW.phone, NEW.full_name, NEW.role, NEW.status, version_at, 'infinity'::timestamptz, actor, reason);
    RETURN NEW;
END;
$$;

CREATE OR REPLACE VIEW analytics.v_commodity_history AS
SELECT h.commodity_history_id, h.commodity_id, h.symbol, h.name AS commodity_name,
       cat.name AS category_name, h.unit, h.tick_size, h.minimum_order_quantity,
       h.status, h.valid_from AS from_date, h.valid_to AS to_date,
       h.valid_from, h.valid_to, h.is_current, h.current_flag, h.change_reason
FROM commodity_history h JOIN categories cat ON cat.category_id = h.category_id;

CREATE OR REPLACE VIEW analytics.v_user_history AS
SELECT user_history_id, user_id, email, phone, full_name, role, status,
       valid_from AS from_date, valid_to AS to_date, valid_from, valid_to,
       is_current, current_flag, change_reason
FROM user_history;

COMMIT;
