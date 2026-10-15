from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Commodity(ApiModel):
    commodity_id: UUID
    symbol: str
    name: str
    category_name: str
    unit: str
    current_price: Decimal | None = None
    daily_change_pct: Decimal | None = None


class MarketPrice(ApiModel):
    price_date: date
    symbol: str
    commodity_name: str
    category_name: str
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    daily_change_pct: Decimal | None = None


class OrderCreate(BaseModel):
    trader_email: str = Field(min_length=3)
    symbol: str = Field(min_length=2, max_length=30)
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit"] = "limit"
    price: Decimal | None = Field(default=None, gt=0)
    quantity: Decimal = Field(gt=0)


class Order(ApiModel):
    order_id: UUID
    trader_name: str
    symbol: str
    side: str
    order_type: str
    price: Decimal | None
    quantity: Decimal
    filled_quantity: Decimal
    status: str
    submitted_at: datetime


class Trade(ApiModel):
    trade_id: UUID
    trade_date: date
    trade_time: datetime
    symbol: str
    commodity_name: str
    buyer_name: str
    seller_name: str
    price: Decimal
    quantity: Decimal
    notional_value: Decimal
    status: str


class Overview(ApiModel):
    total_trades: int
    traded_quantity: Decimal
    traded_notional: Decimal
    active_traders: int
    listed_commodities: int
    market_change_pct: Decimal

