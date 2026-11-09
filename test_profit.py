"""Run:  python test_profit.py"""
import unittest

import profit
from store import location_name, parse_api_date


class ProfitMath(unittest.TestCase):
    def test_no_premium_instant(self):
        b = profit.breakdown(100_000, 130_000, premium=False)
        self.assertEqual(b["tax"], 10_400)          # 8%
        self.assertEqual(b["receive"], 119_600)
        self.assertEqual(b["profit"], 19_600)
        self.assertEqual(b["setup_fee"], 0)

    def test_premium(self):
        b = profit.breakdown(100_000, 130_000, premium=True)
        self.assertEqual(b["tax"], 5_200)           # 4%
        self.assertEqual(b["profit"], 24_800)

    def test_buy_order_fee(self):
        b = profit.breakdown(100_000, 130_000, premium=False, mode="order")
        self.assertEqual(b["setup_fee"], 2_500)     # 2.5%
        self.assertEqual(b["cost"], 102_500)
        self.assertEqual(b["profit"], 17_100)

    def test_rounding_is_conservative(self):
        b = profit.breakdown(1, 4_203_888)          # tax = 336311.04
        self.assertEqual(b["tax"], 336_312)         # tax rounded up
        self.assertEqual(b["receive"], 3_867_576)   # money in rounded down
        self.assertEqual(b["profit"], 3_867_575)

    def test_quality_rule(self):
        bm = {1: (1000, None), 3: (5000, None), 5: (9000, None)}
        self.assertEqual(profit.best_bm_order(bm, 1)[1], 1000)
        self.assertEqual(profit.best_bm_order(bm, 4)[1], 5000)  # can't fill the q5 order
        self.assertEqual(profit.best_bm_order(bm, 5)[1], 9000)
        self.assertIsNone(profit.best_bm_order({3: (5000, None)}, 2))

    def test_order_book(self):
        offers = [(100, 2, 1), (110, 5, 1), (200, 5, 3)]
        reqs = [(150, 3, 1), (120, 10, 1)]
        r = profit.match_order_book(offers, reqs)
        # 2@100->150, 1@110->150, then 120*0.92=110.4 > 110 -> 4 more @110
        self.assertEqual(r["qty"], 7)
        self.assertEqual(r["cost"], 2 * 100 + 5 * 110)
        self.assertEqual(r["receive"], int(3 * 150 * 0.92 + 4 * 120 * 0.92))

    def test_order_book_quality(self):
        r = profit.match_order_book([(100, 5, 1)], [(500, 5, 2)])
        self.assertEqual(r["qty"], 0)                # normal item can't fill a 'good' order


class Parsing(unittest.TestCase):
    def test_locations(self):
        self.assertEqual(location_name("3003"), "Black Market")
        self.assertEqual(location_name("0007"), "Thetford")
        self.assertEqual(location_name("3005-Auction2"), "Caerleon")
        self.assertIsNone(location_name("9999"))

    def test_dates(self):
        self.assertEqual(parse_api_date("0001-01-01T00:00:00"), 0)
        self.assertEqual(parse_api_date("1970-01-01T00:01:00"), 60)


if __name__ == "__main__":
    unittest.main()
