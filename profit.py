"""All money math lives here, done with exact fractions (no float rounding errors).

Rules (Albion Online, current):
  * Selling instantly to the Black Market = filling a BM buy order -> only SALES TAX.
      no premium: 8%   premium: 4%   (no 2.5% setup fee on instant sells)
  * Buying instantly from a city sell order -> no fee at all.
  * Placing a buy order in a city -> 2.5% setup fee on top of the price.
  * A buy order accepts items of its quality OR BETTER, so an item of quality Q
    can fill any BM order whose quality <= Q.

Rounding is conservative: costs are rounded up, money received is rounded down,
so the profit shown is never higher than what you will really get.
"""
from fractions import Fraction
from math import ceil, floor

SALES_TAX = {False: Fraction(8, 100), True: Fraction(4, 100)}
SETUP_FEE = Fraction(25, 1000)


def unit_cost(price, mode="instant"):
    """Silver you pay for one item. mode: 'instant' (buy now) or 'order' (place buy order)."""
    p = Fraction(price)
    return p * (1 + SETUP_FEE) if mode == "order" else p


def unit_revenue(bm_price, premium=False):
    """Silver you receive for one item sold instantly to the Black Market."""
    return Fraction(bm_price) * (1 - SALES_TAX[premium])


def breakdown(buy_price, bm_price, premium=False, mode="instant"):
    cost = unit_cost(buy_price, mode)
    revenue = unit_revenue(bm_price, premium)
    profit = revenue - cost
    return {
        "buy_price": buy_price,
        "setup_fee": ceil(cost - buy_price),
        "cost": ceil(cost),
        "bm_price": bm_price,
        "tax": ceil(Fraction(bm_price) - revenue),
        "receive": floor(revenue),
        "profit": floor(profit),
        "margin": float(profit / cost) if cost else 0.0,
    }


def best_bm_order(bm_by_quality, item_quality):
    """Highest BM buy order an item of `item_quality` can fill.
    bm_by_quality: {quality: (price, extra)} -> returns (quality, price, extra) or None."""
    best = None
    for q, (price, extra) in bm_by_quality.items():
        if q <= item_quality and price > 0 and (best is None or price > best[1]):
            best = (q, price, extra)
    return best


def match_order_book(city_offers, bm_requests, premium=False, mode="instant"):
    """Exact multi-unit plan from real order books (only when we have amounts).

    city_offers: [(price, amount, quality)]  sell orders in the city
    bm_requests: [(price, amount, quality)]  BM buy orders
    Greedy: fill the best-paying BM orders with the cheapest eligible city items,
    stop as soon as a unit would no longer be profitable.
    """
    offers = sorted(([p, a, q] for p, a, q in city_offers if a > 0 and p > 0), key=lambda o: o[0])
    requests = sorted(([p, a, q] for p, a, q in bm_requests if a > 0 and p > 0), key=lambda r: -r[0])
    qty, cost, revenue = 0, Fraction(0), Fraction(0)
    lines = []
    for req in requests:
        rev_unit = unit_revenue(req[0], premium)
        for off in offers:
            if req[1] == 0:
                break
            if off[1] == 0 or off[2] < req[2]:
                continue
            c_unit = unit_cost(off[0], mode)
            if rev_unit <= c_unit:
                break  # offers are sorted, nothing cheaper left for this request
            n = min(off[1], req[1])
            off[1] -= n
            req[1] -= n
            qty += n
            cost += c_unit * n
            revenue += rev_unit * n
            lines.append({"n": n, "buy": off[0], "buy_q": off[2], "sell": req[0], "sell_q": req[2]})
    return {"qty": qty, "cost": ceil(cost), "receive": floor(revenue),
            "profit": floor(revenue - cost), "lines": lines}
