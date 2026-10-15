BEGIN;

-- Market participants for the live simulation. All people and firms are fictitious.
INSERT INTO brokers (name, contact_info)
SELECT x.name, x.contact::jsonb
FROM (VALUES
    ('Kisan Commodity Brokers', '{"email":"desk@kisan-sim.local"}'),
    ('Malabar Futures Desk', '{"email":"desk@malabar-sim.local"}')
) AS x(name, contact)
WHERE NOT EXISTS (SELECT 1 FROM brokers b WHERE b.name = x.name);

INSERT INTO users (email, phone, password_hash, full_name, role)
VALUES
    ('ramesh@ncdex-sim.local', '+919999000011', 'seed-only-replace-before-use', 'Ramesh Patil', 'trader'),
    ('ananya@ncdex-sim.local', '+919999000012', 'seed-only-replace-before-use', 'Ananya Iyer', 'trader'),
    ('arjun@ncdex-sim.local', '+919999000013', 'seed-only-replace-before-use', 'Arjun Mehta', 'trader'),
    ('farhan@ncdex-sim.local', '+919999000014', 'seed-only-replace-before-use', 'Farhan Qureshi', 'trader'),
    ('meera@ncdex-sim.local', '+919999000015', 'seed-only-replace-before-use', 'Meera Joshi', 'trader'),
    ('liquidity@ncdex-sim.local', '+919999000016', 'seed-only-replace-before-use', 'NCDEX Liquidity Desk', 'trader')
ON CONFLICT (email) DO NOTHING;

INSERT INTO traders (user_id, broker_id, experience_level, trader_type, organisation, address_line, city, state, pincode,
                     risk_appetite, kyc_tier, strategy, avatar_color, is_persona, is_market_maker, cash_balance)
SELECT u.user_id, b.broker_id, x.experience, x.trader_type, x.organisation, x.address_line, x.city, x.state, x.pincode,
       x.risk, x.kyc, x.strategy, x.color, x.persona, x.mm, x.cash
FROM (VALUES
    ('ramesh@ncdex-sim.local', 'Kisan Commodity Brokers', '12 years farming', 'Farmer / FPO hedger', 'Vidarbha Cotton Growers FPO',
     'Plot 14, APMC Market Yard', 'Akola', 'Maharashtra', '444001', 'Conservative', 'Full KYC',
     'Sells cotton futures to lock in a price for the coming harvest', '#2f9e6e', true, false, 2500000::numeric),
    ('ananya@ncdex-sim.local', 'Malabar Futures Desk', 'Procurement head', 'Textile mill — hedger buyer', 'Kaveri Spinning Mills',
     '88 Avinashi Road, Peelamedu', 'Coimbatore', 'Tamil Nadu', '641004', 'Moderate', 'Full KYC',
     'Buys cotton futures to protect the mill against rising raw-material cost', '#7768df', true, false, 8000000),
    ('arjun@ncdex-sim.local', 'NCDEX Simulation Desk', '3 years trading', 'Speculator / day trader', 'Independent',
     'Flat 702, Bandra Kurla Complex', 'Mumbai', 'Maharashtra', '400051', 'Aggressive', 'Full KYC',
     'Chases momentum and books profit quickly; adds liquidity and risk', '#e07a3f', true, false, 3000000),
    ('farhan@ncdex-sim.local', 'Malabar Futures Desk', '8 years exports', 'Exporter / arbitrageur', 'Unjha Spice Exports',
     'Shop 5, Ganj Bazar', 'Unjha', 'Gujarat', '384170', 'Moderate', 'Full KYC',
     'Hedges jeera export contracts and arbitrages spot-futures gaps', '#5289da', true, false, 6000000),
    ('meera@ncdex-sim.local', 'Kisan Commodity Brokers', 'Plant manager', 'Processor — soybean crusher', 'Malwa Agro Processors',
     'Sector C, Sanwer Road Industrial Area', 'Indore', 'Madhya Pradesh', '452015', 'Moderate', 'Full KYC',
     'Buys soybean to secure crushing margin against soy-meal sales', '#c4568f', true, false, 5000000),
    ('liquidity@ncdex-sim.local', 'NCDEX Simulation Desk', 'Automated', 'Market maker', 'NCDEX Liquidity Desk (simulated)',
     'Exchange Plaza, BKC', 'Mumbai', 'Maharashtra', '400051', 'Neutral', 'Institutional',
     'Quotes two-sided prices so every order has a counterparty', '#8a9996', false, true, 1000000000)
) AS x(email, broker, experience, trader_type, organisation, address_line, city, state, pincode, risk, kyc, strategy, color, persona, mm, cash)
JOIN users u ON u.email = x.email
JOIN brokers b ON b.name = x.broker
WHERE NOT EXISTS (SELECT 1 FROM traders t WHERE t.user_id = u.user_id);

-- Complete the student profiles; the trigger records this as a second SCD2 version.
SELECT set_config('app.change_reason', 'Student completed KYC profile', true);
UPDATE traders t SET trader_type = 'Student trader', organisation = 'SPIT Mumbai — Group 100',
       address_line = x.address_line, city = 'Mumbai', state = 'Maharashtra', pincode = x.pincode,
       kyc_tier = 'Full KYC', risk_appetite = x.risk, cash_balance = 1000000
FROM users u, (VALUES
    ('yash@ncdex-sim.local', 'Andheri West', '400058', 'Aggressive'),
    ('soham@ncdex-sim.local', 'Bhavans Campus, Andheri', '400058', 'Moderate'),
    ('bhumit@ncdex-sim.local', 'Vile Parle East', '400057', 'Conservative')
) AS x(email, address_line, pincode, risk)
WHERE u.user_id = t.user_id AND u.email = x.email AND t.address_line IS NULL;

-- Close the gap between the rich seed and yesterday with the same synthetic generator.
INSERT INTO market_prices (commodity_id, price_date, open_price, high_price, low_price, close_price, volume, source)
SELECT c.commodity_id, d::date,
    ROUND((x.base + (((EXTRACT(DOY FROM d)::int * 7 + x.seed) % 31) - 15) * x.step)::numeric, 6),
    ROUND((x.base + (((EXTRACT(DOY FROM d)::int * 7 + x.seed) % 31) - 15) * x.step + x.range)::numeric, 6),
    ROUND((x.base + (((EXTRACT(DOY FROM d)::int * 7 + x.seed) % 31) - 15) * x.step - x.range * 0.65)::numeric, 6),
    ROUND((x.base + (((EXTRACT(DOY FROM d)::int * 7 + x.seed) % 31) - 15) * x.step + (((EXTRACT(DOY FROM d)::int + x.seed) % 5) - 2) * x.step)::numeric, 6),
    (1800 + ((EXTRACT(DOY FROM d)::int * 113 + x.seed * 97) % 4200))::numeric,
    'synthetic-demo'
FROM generate_series(date '2026-10-08', current_date - 1, interval '1 day') AS d
CROSS JOIN (VALUES
    ('COTTON', 7200::numeric, 6::numeric, 28::numeric, 11),
    ('JEERA', 24500::numeric, 18::numeric, 90::numeric, 23),
    ('SOYBEAN', 4600::numeric, 4::numeric, 20::numeric, 37)
) AS x(symbol, base, step, range, seed)
JOIN commodities c ON c.symbol = x.symbol
ON CONFLICT (commodity_id, price_date) DO NOTHING;

COMMIT;
