BEGIN;

-- Demonstrate SCD2 versioning with real historical rows. Each update closes
-- the prior version and the trigger inserts a new infinity/current version.
SELECT set_config('app.change_reason', 'Updated Cotton contract description', true);
UPDATE commodities
SET description = 'Cotton futures simulation contract with seasonal market metadata'
WHERE symbol = 'COTTON'
  AND description <> 'Cotton futures simulation contract with seasonal market metadata';

SELECT set_config('app.change_reason', 'Updated Jeera tick size', true);
UPDATE commodities
SET tick_size = 0.50
WHERE symbol = 'JEERA' AND tick_size = 0.25;

SELECT set_config('app.change_reason', 'Updated trader display name for SCD demonstration', true);
UPDATE users
SET full_name = 'Yash Patel — Lead Trader'
WHERE email = 'yash@ncdex-sim.local'
  AND full_name = 'Yash Patel';

COMMIT;

