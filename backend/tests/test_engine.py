"""Isolated unit tests for matching engine core behavior and safeguards.

These tests run without requiring a live database connection or network access.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from app.engine import (
    EngineError,
    _same_val,
    mm_quotes,
    next_position,
    place_order,
    round_tick,
)


class TestCommodityRevisionComparison(unittest.TestCase):
    """Tests for the commodity revision value comparison helper (_same_val)."""

    def test_numeric_comparisons(self):
        """Numeric values should compare equally regardless of Decimal scale or type."""
        self.assertTrue(_same_val(D("5.000000"), 5))
        self.assertTrue(_same_val(D("5.000000"), D("5")))
        self.assertTrue(_same_val(D("0.050000"), 0.05))
        self.assertTrue(_same_val(D("0.050000"), D("0.05")))
        self.assertTrue(_same_val(0, D("0.000000")))

        # Inequalities
        self.assertFalse(_same_val(D("5.000000"), 1))
        self.assertFalse(_same_val(D("0.050000"), D("0.10")))

    def test_text_comparisons(self):
        """Non-numeric string values should compare safely as strings without InvalidOperation."""
        # Status
        self.assertTrue(_same_val("active", "active"))
        self.assertFalse(_same_val("active", "halted"))

        # Commodity names and units
        self.assertTrue(_same_val("Cotton 29mm", "Cotton 29mm"))
        self.assertFalse(_same_val("Cotton 29mm", "Soybean"))
        self.assertTrue(_same_val("Bales", "Bales"))
        self.assertFalse(_same_val("Bales", "MT"))

        # Descriptions
        self.assertTrue(_same_val("Standard contract", "Standard contract"))
        self.assertFalse(_same_val("Standard contract", "Revised contract terms"))

    def test_null_comparisons(self):
        """Null values should compare safely without stringifying None."""
        self.assertTrue(_same_val(None, None))
        self.assertFalse(_same_val(None, "active"))
        self.assertFalse(_same_val("active", None))
        self.assertFalse(_same_val(None, 5))
        self.assertFalse(_same_val(5, None))
        self.assertFalse(_same_val(None, "None"))

    def test_mixed_types(self):
        """Comparing numeric with non-numeric text should evaluate to False without error."""
        self.assertFalse(_same_val(5, "Cotton"))
        self.assertFalse(_same_val("Cotton", 5))
        self.assertFalse(_same_val(D("5.0"), "active"))

    def test_revision_selection_toggle(self):
        """Simulate how run_step toggles commodity revision options."""
        def select_option(current_row, step_definition):
            first = step_definition["options"][0]
            return (
                step_definition["options"][1]
                if all(_same_val(current_row.get(k), v) for k, v in first.items())
                else first
            )

        # 1. Numeric lot size toggle
        numeric_step = {
            "options": [{"minimum_order_quantity": 5}, {"minimum_order_quantity": 1}]
        }
        # Initial lot = 1 -> select option 0 (lot: 5)
        self.assertEqual(
            select_option({"minimum_order_quantity": D("1.000000")}, numeric_step),
            {"minimum_order_quantity": 5},
        )
        # Updated lot = 5 -> toggle to option 1 (lot: 1)
        self.assertEqual(
            select_option({"minimum_order_quantity": D("5.000000")}, numeric_step),
            {"minimum_order_quantity": 1},
        )

        # 2. Text status toggle
        text_step = {
            "options": [{"status": "halted"}, {"status": "active"}]
        }
        self.assertEqual(
            select_option({"status": "active"}, text_step),
            {"status": "halted"},
        )
        self.assertEqual(
            select_option({"status": "halted"}, text_step),
            {"status": "active"},
        )


class TestPositionMath(unittest.TestCase):
    """Tests for futures net position calculation, cost averaging, and P&L."""

    def test_open_long_position(self):
        pos = (D(0), D(0), D(0))
        q1, avg1, realized = next_position(pos, D(10), D(7000))
        self.assertEqual(q1, D(10))
        self.assertEqual(avg1, D(7000))
        self.assertEqual(realized, D(0))

    def test_add_to_long_position(self):
        # 10 @ 7000 + 10 @ 7200 = 20 @ 7100
        pos = (D(10), D(7000), D(0))
        q1, avg1, realized = next_position(pos, D(10), D(7200))
        self.assertEqual(q1, D(20))
        self.assertEqual(avg1, D(7100))
        self.assertEqual(realized, D(0))

    def test_partial_close_long(self):
        # Long 20 @ 7100, sell 5 @ 7300 -> 15 @ 7100, realized profit = 5 * (7300 - 7100) = 1000
        pos = (D(20), D(7100), D(0))
        q1, avg1, realized = next_position(pos, D(-5), D(7300))
        self.assertEqual(q1, D(15))
        self.assertEqual(avg1, D(7100))
        self.assertEqual(realized, D(1000))

    def test_full_close_long(self):
        # Long 15 @ 7100, sell 15 @ 7200 -> flat 0, realized profit = 15 * 100 = 1500
        pos = (D(15), D(7100), D(1000))
        q1, avg1, realized = next_position(pos, D(-15), D(7200))
        self.assertEqual(q1, D(0))
        self.assertEqual(avg1, D(0))
        self.assertEqual(realized, D(2500))

    def test_open_and_close_short(self):
        # Open short 10 @ 7000
        pos0 = (D(0), D(0), D(0))
        pos1 = next_position(pos0, D(-10), D(7000))
        self.assertEqual(pos1, (D(-10), D(7000), D(0)))

        # Close short 5 @ 6900 -> short profit = 5 * (7000 - 6900) = 500
        pos2 = next_position(pos1, D(5), D(6900))
        self.assertEqual(pos2, (D(-5), D(7000), D(500)))

    def test_flip_long_to_short(self):
        # Long 10 @ 7000, sell 15 @ 7100 -> closes 10 with +1000 profit, opens short 5 @ 7100
        pos = (D(10), D(7000), D(0))
        q1, avg1, realized = next_position(pos, D(-15), D(7100))
        self.assertEqual(q1, D(-5))
        self.assertEqual(avg1, D(7100))
        self.assertEqual(realized, D(1000))


class TestOrderMatchingSafeguards(unittest.TestCase):
    """Tests for order validation, matching safeguards, and wash-trading prevention."""

    def _setup_mock_connection(self, trader_row, comm_row, resting_book=None, positions=None):
        cur = MagicMock()
        conn = MagicMock()
        cur.connection = conn
        conn.pipeline.return_value.__enter__ = MagicMock()
        conn.pipeline.return_value.__exit__ = MagicMock()

        c_trader = MagicMock()
        c_comm = MagicMock()
        c_book = MagicMock()
        c_pos = MagicMock()
        c_mm = MagicMock()
        conn.cursor.side_effect = [c_trader, c_comm, c_book, c_pos, c_mm]

        c_trader.fetchone.return_value = trader_row
        c_comm.fetchone.return_value = comm_row
        c_book.fetchall.return_value = resting_book or []
        c_pos.fetchall.return_value = positions or []
        c_mm.fetchone.return_value = None
        return cur

    def test_minimum_order_quantity_safeguard(self):
        t_id = uuid4()
        trader = {
            "trader_id": t_id, "full_name": "Trader 1", "trader_type": "Student trader",
            "cash_balance": D("1000000"), "is_market_maker": False, "user_id": uuid4()
        }
        comm = {
            "commodity_id": uuid4(), "symbol": "COTTON", "name": "Cotton", "unit": "bale",
            "tick_size": D("0.05"), "minimum_order_quantity": D("5"), "ltp": D("7000")
        }
        cur = self._setup_mock_connection(trader, comm)

        with self.assertRaises(EngineError) as ctx:
            place_order(cur, t_id, "COTTON", "buy", "limit", 2, 7000)
        self.assertIn("minimum order is 5 bale", str(ctx.exception))

    def test_limit_order_requires_price(self):
        t_id = uuid4()
        trader = {
            "trader_id": t_id, "full_name": "Trader 1", "trader_type": "Student trader",
            "cash_balance": D("1000000"), "is_market_maker": False, "user_id": uuid4()
        }
        comm = {
            "commodity_id": uuid4(), "symbol": "COTTON", "name": "Cotton", "unit": "bale",
            "tick_size": D("0.05"), "minimum_order_quantity": D("1"), "ltp": D("7000")
        }
        cur = self._setup_mock_connection(trader, comm)

        with self.assertRaises(EngineError) as ctx:
            place_order(cur, t_id, "COTTON", "buy", "limit", 5, price=None)
        self.assertIn("Limit orders require a price", str(ctx.exception))

    def test_buyer_cash_balance_check(self):
        t_id = uuid4()
        trader = {
            "trader_id": t_id, "full_name": "Poor Trader", "trader_type": "Student trader",
            "cash_balance": D("1000"), "is_market_maker": False, "user_id": uuid4()
        }
        comm = {
            "commodity_id": uuid4(), "symbol": "COTTON", "name": "Cotton", "unit": "bale",
            "tick_size": D("0.05"), "minimum_order_quantity": D("1"), "ltp": D("7000")
        }
        cur = self._setup_mock_connection(trader, comm)

        # 5 * 7000 = 35000 > 1000
        with self.assertRaises(EngineError) as ctx:
            place_order(cur, t_id, "COTTON", "buy", "limit", 5, 7000)
        self.assertIn("needs about", str(ctx.exception))

    def test_wash_trading_prevention(self):
        """Orders from the same trader must not match against each other."""
        t_id = uuid4()
        trader = {
            "trader_id": t_id, "full_name": "Self Trader", "trader_type": "Student trader",
            "cash_balance": D("1000000"), "is_market_maker": False, "user_id": uuid4()
        }
        comm = {
            "commodity_id": uuid4(), "symbol": "COTTON", "name": "Cotton", "unit": "bale",
            "tick_size": D("0.05"), "minimum_order_quantity": D("1"), "ltp": D("7000")
        }
        resting_sell = [{
            "order_id": uuid4(), "trader_id": t_id, "side": "sell", "price": D("7000"),
            "quantity": D("10"), "filled_quantity": D("0"), "submitted_at": datetime.now(timezone.utc),
            "full_name": "Self Trader", "is_market_maker": False
        }]
        cur = self._setup_mock_connection(trader, comm, resting_book=resting_sell)

        res = place_order(cur, t_id, "COTTON", "buy", "limit", 5, 7000)
        # Self-match is rejected: order remains open with 0 fills
        self.assertEqual(res["status"], "open")
        self.assertEqual(res["filled"], D("0"))
        self.assertEqual(len(res["fills"]), 0)

    def test_price_time_priority(self):
        """Incoming aggressor must match best price first, then earliest submission."""
        buyer_id = uuid4()
        buyer = {
            "trader_id": buyer_id, "full_name": "Aggressive Buyer", "trader_type": "Student trader",
            "cash_balance": D("1000000"), "is_market_maker": False, "user_id": uuid4()
        }
        comm = {
            "commodity_id": uuid4(), "symbol": "COTTON", "name": "Cotton", "unit": "bale",
            "tick_size": D("0.05"), "minimum_order_quantity": D("1"), "ltp": D("7000")
        }
        t0 = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
        s_a, s_b, s_c = uuid4(), uuid4(), uuid4()
        resting_asks = [
            # Higher price (7020)
            {"order_id": uuid4(), "trader_id": s_a, "side": "sell", "price": D("7020"),
             "quantity": D("5"), "filled_quantity": D("0"), "submitted_at": t0,
             "full_name": "Seller A", "is_market_maker": False},
            # Lowest price (7010) submitted later (+5 min)
            {"order_id": uuid4(), "trader_id": s_b, "side": "sell", "price": D("7010"),
             "quantity": D("5"), "filled_quantity": D("0"), "submitted_at": t0 + timedelta(minutes=5),
             "full_name": "Seller B", "is_market_maker": False},
            # Lowest price (7010) submitted earlier (+2 min)
            {"order_id": uuid4(), "trader_id": s_c, "side": "sell", "price": D("7010"),
             "quantity": D("5"), "filled_quantity": D("0"), "submitted_at": t0 + timedelta(minutes=2),
             "full_name": "Seller C", "is_market_maker": False},
        ]
        cur = self._setup_mock_connection(buyer, comm, resting_book=resting_asks)

        # Buy 12 bales at limit 7050
        res = place_order(cur, buyer_id, "COTTON", "buy", "limit", 12, 7050)
        self.assertEqual(res["status"], "filled")
        self.assertEqual(res["filled"], D("12"))
        self.assertEqual(len(res["fills"]), 3)

        # Fill 1: Seller C (best price 7010, earliest time)
        self.assertEqual(res["fills"][0]["counterparty"], "Seller C")
        self.assertEqual(res["fills"][0]["price"], D("7010"))
        self.assertEqual(res["fills"][0]["quantity"], D("5"))

        # Fill 2: Seller B (best price 7010, next earliest time)
        self.assertEqual(res["fills"][1]["counterparty"], "Seller B")
        self.assertEqual(res["fills"][1]["price"], D("7010"))
        self.assertEqual(res["fills"][1]["quantity"], D("5"))

        # Fill 3: Seller A (higher price 7020, fills remaining 2)
        self.assertEqual(res["fills"][2]["counterparty"], "Seller A")
        self.assertEqual(res["fills"][2]["price"], D("7020"))
        self.assertEqual(res["fills"][2]["quantity"], D("2"))

    def test_market_order_unfilled_cancelled(self):
        """Market orders that only fill partially must have their unfilled balance cancelled (IOC)."""
        buyer_id = uuid4()
        buyer = {
            "trader_id": buyer_id, "full_name": "Buyer", "trader_type": "Student trader",
            "cash_balance": D("1000000"), "is_market_maker": False, "user_id": uuid4()
        }
        comm = {
            "commodity_id": uuid4(), "symbol": "COTTON", "name": "Cotton", "unit": "bale",
            "tick_size": D("0.05"), "minimum_order_quantity": D("1"), "ltp": D("7000")
        }
        # Only 5 bales available in book
        resting_asks = [
            {"order_id": uuid4(), "trader_id": uuid4(), "side": "sell", "price": D("7000"),
             "quantity": D("5"), "filled_quantity": D("0"), "submitted_at": datetime.now(timezone.utc),
             "full_name": "Seller", "is_market_maker": False}
        ]
        cur = self._setup_mock_connection(buyer, comm, resting_book=resting_asks)

        # Market order for 10 bales (only 5 can fill)
        res = place_order(cur, buyer_id, "COTTON", "buy", "market", 10)
        self.assertEqual(res["filled"], D("5"))
        self.assertEqual(res["status"], "cancelled")  # Immediate or cancel remainder

    def test_tick_rounding(self):
        """Tick rounding should round prices to valid increments."""
        self.assertEqual(round_tick(D("7000.03"), D("0.05")), D("7000.05"))
        self.assertEqual(round_tick(D("7000.02"), D("0.05")), D("7000.00"))


class TestMarketMakerQuotes(unittest.TestCase):
    """Tests for liquidity desk market maker quote calculations."""

    def test_mm_quotes_never_cross_resting_orders(self):
        comm = {"commodity_id": uuid4(), "tick_size": D("0.05")}
        ltp = D("7000.00")
        mm_id = uuid4()

        # Existing resting orders in the book
        resting = [
            ("buy", D("6980.00")),   # best bid
            ("sell", D("7020.00")),  # best ask
        ]
        quotes = mm_quotes(comm, ltp, mm_id, resting)
        self.assertTrue(len(quotes) > 0)

        for q_mm, q_cid, q_side, q_type, q_px, q_size in quotes:
            if q_side == "sell":
                # MM ask must never cross below or at resting bid
                self.assertGreater(q_px, D("6980.00"))
            elif q_side == "buy":
                # MM bid must never cross above or at resting ask
                self.assertLess(q_px, D("7020.00"))


if __name__ == "__main__":
    unittest.main()
