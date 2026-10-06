# NCDEX Power BI dashboard plan

The Power BI model should import the `analytics` views from Neon. Use Import mode for the faculty demo and schedule refresh after the dataset is created. A refresh reads the latest committed rows from Neon; it is not a continuously live link unless DirectQuery is selected.

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
- Effective-date timeline using `valid_from` and `valid_to`.
- A card showing current-version count versus total historical-version count.

## Important limitation

Power BI Web can create reports from supported connectors, but the PostgreSQL connection wizard may hand off to Power BI Desktop depending on the tenant/account experience. If the web flow returns to the workspace without a dataset, use Power BI Desktop with the same Neon direct connection, publish the resulting dataset/report to **My workspace**, and then configure scheduled refresh there.

