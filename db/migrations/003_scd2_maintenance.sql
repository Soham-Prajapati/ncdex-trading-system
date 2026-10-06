BEGIN;

CREATE OR REPLACE FUNCTION scd2_record_commodity()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    version_at TIMESTAMPTZ := clock_timestamp();
    actor UUID := NULLIF(current_setting('app.actor_user_id', true), '')::uuid;
    reason TEXT := COALESCE(NULLIF(current_setting('app.change_reason', true), ''), 'commodity update');
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO commodity_history (commodity_id, category_id, name, symbol, description, unit, tick_size, minimum_order_quantity, status, valid_from, changed_by, change_reason)
        VALUES (NEW.commodity_id, NEW.category_id, NEW.name, NEW.symbol, NEW.description, NEW.unit, NEW.tick_size, NEW.minimum_order_quantity, NEW.status, version_at, actor, 'initial version');
        RETURN NEW;
    END IF;
    IF ROW(OLD.category_id, OLD.name, OLD.symbol, OLD.description, OLD.unit, OLD.tick_size, OLD.minimum_order_quantity, OLD.status)
       IS NOT DISTINCT FROM ROW(NEW.category_id, NEW.name, NEW.symbol, NEW.description, NEW.unit, NEW.tick_size, NEW.minimum_order_quantity, NEW.status) THEN
        RETURN NEW;
    END IF;
    UPDATE commodity_history SET valid_to = version_at WHERE commodity_id = NEW.commodity_id AND valid_to IS NULL;
    INSERT INTO commodity_history (commodity_id, category_id, name, symbol, description, unit, tick_size, minimum_order_quantity, status, valid_from, changed_by, change_reason)
    VALUES (NEW.commodity_id, NEW.category_id, NEW.name, NEW.symbol, NEW.description, NEW.unit, NEW.tick_size, NEW.minimum_order_quantity, NEW.status, version_at, actor, reason);
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
        INSERT INTO user_history (user_id, email, phone, full_name, role, status, valid_from, changed_by, change_reason)
        VALUES (NEW.user_id, NEW.email, NEW.phone, NEW.full_name, NEW.role, NEW.status, version_at, actor, 'initial version');
        RETURN NEW;
    END IF;
    IF ROW(OLD.email, OLD.phone, OLD.full_name, OLD.role, OLD.status)
       IS NOT DISTINCT FROM ROW(NEW.email, NEW.phone, NEW.full_name, NEW.role, NEW.status) THEN
        RETURN NEW;
    END IF;
    UPDATE user_history SET valid_to = version_at WHERE user_id = NEW.user_id AND valid_to IS NULL;
    INSERT INTO user_history (user_id, email, phone, full_name, role, status, valid_from, changed_by, change_reason)
    VALUES (NEW.user_id, NEW.email, NEW.phone, NEW.full_name, NEW.role, NEW.status, version_at, actor, reason);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_scd2_commodity ON commodities;
CREATE TRIGGER trg_scd2_commodity
AFTER INSERT OR UPDATE OF category_id, name, symbol, description, unit, tick_size, minimum_order_quantity, status ON commodities
FOR EACH ROW EXECUTE FUNCTION scd2_record_commodity();

DROP TRIGGER IF EXISTS trg_scd2_user ON users;
CREATE TRIGGER trg_scd2_user
AFTER INSERT OR UPDATE OF email, phone, full_name, role, status ON users
FOR EACH ROW EXECUTE FUNCTION scd2_record_user();

COMMIT;

