# NCDEX Power BI dashboard plan

The Power BI model should import the `analytics` views from Neon. Use Import mode for the faculty demo and schedule refresh after the dataset is created. A refresh reads the latest committed rows from Neon; it is not a continuously live link unless DirectQuery is selected.

## Persisted Power BI artifacts

The Neon connection has been used to create these saved artifacts in **My workspace**:

- Semantic model: `NCDEX Trading Analytics`
- Report: `NCDEX Trading Analytics Report`
- Report URL: `https://app.powerbi.com/groups/82cf6b9e-a1b0-401f-a341-40b1c99117c1/reports/455db239-d0fb-4ee2-836e-c094fd96d94e`

The report currently has the seven analytics views loaded as its model. The report canvas still needs the visual composition below to be laid out in Power BI's editor.

## Views added for the live simulation (migration 005)

Add these to the semantic model (Transform data / Get data → same Neon source → `analytics` schema):

- `v_scd_change_log` — one row per SCD2 version across trader profile, user account and commodity, with a readable `changed_fields` diff (`city: Akola → Amravati`), `from_date`, `to_date` (infinity for current), `current_flag`.
- `v_trader_history` — physical trader-profile SCD2 rows with `version_no`.
- `v_trader_profiles` — current profile, cash, position value, unrealised and realised P&L per trader.
- `v_price_ticks` — every live execution: aggressor, side, previous price, new price, change %, narrative.

Suggested measures:

```DAX
SCD Versions = COUNTROWS(v_scd_change_log)
Current Versions = CALCULATE(COUNTROWS(v_scd_change_log), v_scd_change_log[current_flag] = "Y")
Closed Versions = [SCD Versions] - [Current Versions]
Live Ticks = COUNTROWS(v_price_ticks)
Buyer-initiated Move = CALCULATE(SUM(v_price_ticks[price_change]), v_price_ticks[aggressor_side] = "buy")
Seller-initiated Move = CALCULATE(SUM(v_price_ticks[price_change]), v_price_ticks[aggressor_side] = "sell")
Total P&L = SUM(v_trader_profiles[unrealized_pnl]) + SUM(v_trader_profiles[realized_pnl])
```

Power BI cannot display `infinity`; in Power Query replace errors in `to_date` with `#datetime(9999,12,31,0,0,0)` (or keep `current_flag` as the filter).

Pages to add: **Live simulation** (tick line by `tick_time`, price change by `aggressor_name`, narrative table), **SCD2 audit** (cards: SCD Versions / Current / Closed; table of `v_scd_change_log`; slicer on `dimension`), **Participants** (P&L by trader from `v_trader_profiles`).

## Faculty overview

- KPI cards: traded notional, traded quantity, trade count, active traders.
- Line chart: close price by date and commodity.
- Column chart: daily traded notional.
- Slicers: date, commodity, category, order status.

## Market analytics

- OHLC trend from `v_market_prices`.
- Volume by commodity.
- Daily change percentage heatmap.
- Volume-weighted average price from `v_daily_market_summary`.

## Trading operations

- Order count by side and status from `v_order_activity`.
- Fill-rate distribution.
- Trade facts table with buyer, seller, price, quantity, and notional.
- Top commodities by traded value.

## Trader and portfolio analytics

- Holdings table from `v_portfolio_snapshot`.
- Unrealized P&L by trader and commodity.
- Average price versus current price.
- Trade activity by trader.

## Data-management / SCD audit

- Current versus historical commodity versions from `v_commodity_history`.
- User profile changes from `v_user_history`.
- Effective-date timeline using `from_date` and `to_date`.
- Current rows have `to_date = infinity` and `current_flag = 'Y'`; closed rows have a real closing `to_date` and `current_flag = 'N'`.
- A card showing current-version count versus total historical-version count.

## Important limitation

Power BI Web can create reports from supported connectors, but the PostgreSQL connection wizard may hand off to Power BI Desktop depending on the tenant/account experience. If the web flow returns to the workspace without a dataset, use Power BI Desktop with the same Neon direct connection, publish the resulting dataset/report to **My workspace**, and then configure scheduled refresh there.

For this project the web flow successfully created the semantic model and report. Refreshing the saved report updates imported data from Neon; configure scheduled refresh in the semantic model's settings when the faculty demo cadence is known.
