BEGIN;

-- SCD Type 2 keeps every effective version of descriptive records. The current
-- row is identified by valid_to IS NULL; a new version closes the old row.
CREATE TABLE commodity_history (
    commodity_history_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    commodity_id UUID NOT NULL REFERENCES commodities(commodity_id),
    category_id UUID NOT NULL REFERENCES categories(category_id),
    name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    description TEXT,
    unit TEXT NOT NULL,
    tick_size NUMERIC(18, 6) NOT NULL,
    minimum_order_quantity NUMERIC(18, 6) NOT NULL,
    status account_status NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to TIMESTAMPTZ,
    is_current BOOLEAN GENERATED ALWAYS AS (valid_to IS NULL) STORED,
    changed_by UUID REFERENCES users(user_id),
    change_reason TEXT NOT NULL DEFAULT 'initial version',
    UNIQUE (commodity_id, valid_from)
);

CREATE UNIQUE INDEX uq_commodity_history_current
    ON commodity_history (commodity_id) WHERE valid_to IS NULL;

CREATE TABLE user_history (
    user_history_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(user_id),
    email TEXT NOT NULL,
    phone TEXT,
    full_name TEXT NOT NULL,
    role user_role NOT NULL,
    status account_status NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to TIMESTAMPTZ,
    is_current BOOLEAN GENERATED ALWAYS AS (valid_to IS NULL) STORED,
    changed_by UUID REFERENCES users(user_id),
    change_reason TEXT NOT NULL DEFAULT 'initial version',
    UNIQUE (user_id, valid_from)
);

CREATE UNIQUE INDEX uq_user_history_current
    ON user_history (user_id) WHERE valid_to IS NULL;

INSERT INTO commodity_history (
    commodity_id, category_id, name, symbol, description, unit,
    tick_size, minimum_order_quantity, status, valid_from, change_reason
)
SELECT commodity_id, category_id, name, symbol, description, unit,
       tick_size, minimum_order_quantity, status, created_at, 'initial version'
FROM commodities;

INSERT INTO user_history (user_id, email, phone, full_name, role, status, valid_from, change_reason)
SELECT user_id, email, phone, full_name, role, status, created_at, 'initial version'
FROM users;

CREATE OR REPLACE FUNCTION scd2_record_commodity()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    version_at TIMESTAMPTZ := clock_timestamp();
    actor UUID := NULLIF(current_setting('app.actor_user_id', true), '')::uuid;
    reason TEXT := COALESCE(NULLIF(current_setting('app.change_reason', true), ''), 'commodity update');
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO commodity_history (
            commodity_id, category_id, name, symbol, description, unit,
            tick_size, minimum_order_quantity, status, valid_from, changed_by, change_reason
        ) VALUES (
            NEW.commodity_id, NEW.category_id, NEW.name, NEW.symbol, NEW.description, NEW.unit,
            NEW.tick_size, NEW.minimum_order_quantity, NEW.status, version_at, actor, 'initial version'
        );
        RETURN NEW;
    END IF;

    IF ROW(OLD.category_id, OLD.name, OLD.symbol, OLD.description, OLD.unit,
           OLD.tick_size, OLD.minimum_order_quantity, OLD.status)
       IS NOT DISTINCT FROM
       ROW(NEW.category_id, NEW.name, NEW.symbol, NEW.description, NEW.unit,
           NEW.tick_size, NEW.minimum_order_quantity, NEW.status) THEN
        RETURN NEW;
    END IF;

    UPDATE commodity_history
    SET valid_to = version_at
    WHERE commodity_id = NEW.commodity_id AND valid_to IS NULL;

    INSERT INTO commodity_history (
        commodity_id, category_id, name, symbol, description, unit,
        tick_size, minimum_order_quantity, status, valid_from, changed_by, change_reason
    ) VALUES (
        NEW.commodity_id, NEW.category_id, NEW.name, NEW.symbol, NEW.description, NEW.unit,
        NEW.tick_size, NEW.minimum_order_quantity, NEW.status, version_at, actor, reason
    );
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION scd2_record_user()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    version_at TIMESTAMPTZ := clock_timestamp();
    actor UUID := NULLIF(current_setting('app.actor_user_id', true), '')::uuid;
    reason TEXT := COALESCE(NULLIF(current_setting('app.change_reason', true), ''), 'user update');
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO user_history (
            user_id, email, phone, full_name, role, status, valid_from, changed_by, change_reason
        ) VALUES (
            NEW.user_id, NEW.email, NEW.phone, NEW.full_name, NEW.role, NEW.status,
            version_at, actor, 'initial version'
        );
        RETURN NEW;
    END IF;

    IF ROW(OLD.email, OLD.phone, OLD.full_name, OLD.role, OLD.status)
       IS NOT DISTINCT FROM ROW(NEW.email, NEW.phone, NEW.full_name, NEW.role, NEW.status) THEN
        RETURN NEW;
    END IF;

    UPDATE user_history
    SET valid_to = version_at
    WHERE user_id = NEW.user_id AND valid_to IS NULL;

    INSERT INTO user_history (
        user_id, email, phone, full_name, role, status, valid_from, changed_by, change_reason
    ) VALUES (
        NEW.user_id, NEW.email, NEW.phone, NEW.full_name, NEW.role, NEW.status,
        version_at, actor, reason
    );
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_scd2_commodity
AFTER INSERT OR UPDATE OF category_id, name, symbol, description, unit,
    tick_size, minimum_order_quantity, status ON commodities
FOR EACH ROW EXECUTE FUNCTION scd2_record_commodity();

CREATE TRIGGER trg_scd2_user
AFTER INSERT OR UPDATE OF email, phone, full_name, role, status ON users
FOR EACH ROW EXECUTE FUNCTION scd2_record_user();

CREATE VIEW analytics.v_commodity_history AS
SELECT
    h.commodity_history_id,
    h.commodity_id,
    h.symbol,
    h.name AS commodity_name,
    cat.name AS category_name,
    h.unit,
    h.tick_size,
    h.minimum_order_quantity,
    h.status,
    h.valid_from,
    h.valid_to,
    h.is_current,
    h.change_reason
FROM commodity_history h
JOIN categories cat ON cat.category_id = h.category_id;

CREATE VIEW analytics.v_user_history AS
SELECT
    user_history_id,
    user_id,
    email,
    phone,
    full_name,
    role,
    status,
    valid_from,
    valid_to,
    is_current,
    change_reason
FROM user_history;

COMMIT;
