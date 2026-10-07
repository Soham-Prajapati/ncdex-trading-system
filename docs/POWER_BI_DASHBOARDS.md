# NCDEX Power BI dashboard plan

The Power BI model should import the `analytics` views from Neon. Use Import mode for the faculty demo and schedule refresh after the dataset is created. A refresh reads the latest committed rows from Neon; it is not a continuously live link unless DirectQuery is selected.

## Persisted Power BI artifacts

The Neon connection has been used to create these saved artifacts in **My workspace**:

- Semantic model: `NCDEX Trading Analytics`
- Report: `NCDEX Trading Analytics Report`
- Report URL: `https://app.powerbi.com/groups/82cf6b9e-a1b0-401f-a341-40b1c99117c1/reports/455db239-d0fb-4ee2-836e-c094fd96d94e`

The report currently has the seven analytics views loaded as its model. The report canvas still needs the visual composition below to be laid out in Power BI's editor.

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
