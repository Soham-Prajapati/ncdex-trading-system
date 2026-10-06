# Power BI connection

Power BI should read the direct, unpooled Neon connection for refreshes and analytics. The application itself will use the pooled `DATABASE_URL`.

1. In Power BI Desktop, choose **Get data → PostgreSQL database**.
2. Use the hostname, port, database, and username from `DATABASE_URL_UNPOOLED` in `.env.local`; do not commit that value.
3. Set **Data connectivity mode** to **Import** for the first dashboard. Use **DirectQuery** only after the report shape and refresh load are understood.
4. When Power BI asks for encryption, keep SSL enabled. Neon connections require TLS.
5. Select the `analytics` schema and import these views:
   - `v_market_prices` — OHLC, volume, category, and daily price change.
   - `v_trade_facts` — buyer/seller trade facts and notional value.
   - `v_daily_market_summary` — daily volume-weighted market summary.
   - `v_portfolio_snapshot` — current holdings and unrealized P&L.
   - `v_order_activity` — order status and fill-rate analysis.

Recommended first visuals:

- line chart: `price_date` by `close_price`, filtered by `symbol`;
- clustered columns: `trade_date` by `traded_notional`;
- cards: total trades, traded quantity, traded notional;
- table: trader name, symbol, quantity, unrealized P&L;
- stacked columns: order `side` by `status`.

This repository creates the database views and documents the connection; it does not automate Power BI Desktop sign-in or publish a workspace dataset.

