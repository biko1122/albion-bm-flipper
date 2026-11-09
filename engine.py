"""Combines public API prices + live orders (your client, your friend, everyone) and finds
Black Market flips."""
import time

import profit
from store import BLACK_MARKET, CITIES

ALL_SOURCES = ("api", "me", "live")
# When you look at an item in a market, any order of it that wasn't seen within this many
# seconds of that look is considered gone (bought / filled). Covers flipping through pages.
SNAPSHOT_WINDOW = 90


def _newer(a, b):
    """Pick the fresher of two (price, at, src, amount) tuples."""
    if not a:
        return b
    if not b:
        return a
    return a if a[1] >= b[1] else b


def price_board(store, max_age_s, item_id=None, sources=ALL_SOURCES):
    """board[item][market][quality] = {'sell': (price, at, src, amount), 'buy': (...)}
    sell = cheapest sell order (what you pay to buy now), buy = highest buy order.
    book[(item, market, 'offer'|'request')] = [(price, amount, quality)] real order books."""
    since = int(time.time()) - max_age_s
    dismissed = store.dismissed()
    snaps = store.snapshots(item_id)
    board = {}

    def slot(item, market, q):
        return board.setdefault(item, {}).setdefault(market, {}).setdefault(q, {})

    def gone(item, market, at):
        d = dismissed.get((item, market))
        return d is not None and at <= d

    if "api" in sources:
        for item, market, q, sell, sell_at, buy, buy_at in store.api_prices(item_id):
            # a page you looked at yourself after this API price replaces it
            if sell > 0 and sell_at >= since and not gone(item, market, sell_at) \
                    and snaps.get((item, market, "offer"), 0) <= sell_at:
                slot(item, market, q)["sell"] = (sell, sell_at, "api", None)
            if buy > 0 and buy_at >= since and not gone(item, market, buy_at) \
                    and snaps.get((item, market, "request"), 0) <= buy_at:
                slot(item, market, q)["buy"] = (buy, buy_at, "api", None)

    live_sources = tuple(s for s in sources if s in ("me", "live"))
    groups, book = {}, {}
    if live_sources:
        for item, market, q, price, amount, typ, seen, src in store.local_orders(max_age_s, item_id, live_sources):
            if gone(item, market, seen) or seen < snaps.get((item, market, typ), 0) - SNAPSHOT_WINDOW:
                continue
            groups.setdefault((item, market, q, typ), []).append((price, amount, seen, src))
            book.setdefault((item, market, typ), []).append((price, amount, q))
    for (item, market, q, typ), orders in groups.items():
        p = min(o[0] for o in orders) if typ == "offer" else max(o[0] for o in orders)
        at_p = [o for o in orders if o[0] == p]
        amt = sum(o[1] for o in at_p)
        seen = max(o[2] for o in at_p)
        src = "me" if any(o[3] == "me" for o in at_p) else "live"
        side = "sell" if typ == "offer" else "buy"
        s = slot(item, market, q)
        s[side] = _newer((p, seen, src, amt), s.get(side))
    return board, book


def _depth(book, item_id, city, premium, mode="instant", keep_lines=False):
    """Exact multi-unit plan when both order books (with amounts) are known."""
    if mode != "instant":
        return None
    offers = book.get((item_id, city, "offer"))
    reqs = book.get((item_id, BLACK_MARKET, "request"))
    if not offers or not reqs:
        return None
    r = profit.match_order_book(offers, reqs, premium, "instant")
    if not keep_lines:
        r.pop("lines", None)
    return r if r["qty"] else None


def opportunities(store, items, premium=False, mode="instant", max_age_h=6, min_profit=1,
                  sources=ALL_SOURCES):
    items_by_id = {i["id"]: i for i in items}
    board, book = price_board(store, int(max_age_h * 3600), sources=sources)
    history = store.all_history()
    rows = []
    for item_id, markets in board.items():
        meta = items_by_id.get(item_id)
        bm = markets.get(BLACK_MARKET)
        if not meta or not bm:
            continue
        bm_orders = {q: (v["buy"][0], v["buy"]) for q, v in bm.items() if "buy" in v}
        if not bm_orders:
            continue
        for city in CITIES:
            city_board = markets.get(city)
            if not city_board:
                continue
            depth, depth_done = None, False
            for q in range(1, 6):
                cell = city_board.get(q) or {}
                if mode == "order":
                    if "buy" not in cell:
                        continue
                    buy = cell["buy"]
                    buy_price = buy[0] + 1           # outbid the highest buy order by 1 silver
                    if "sell" in cell and buy_price >= cell["sell"][0]:
                        continue                     # buying instantly would be cheaper
                else:
                    if "sell" not in cell:
                        continue
                    buy = cell["sell"]
                    buy_price = buy[0]
                best = profit.best_bm_order(bm_orders, q)
                if not best:
                    continue
                bm_q, bm_price, bm_info = best
                b = profit.breakdown(buy_price, bm_price, premium, mode)
                if b["profit"] < min_profit:
                    continue
                if not depth_done:
                    depth, depth_done = _depth(book, item_id, city, premium, mode), True
                vol = history.get((item_id, bm_q))
                rows.append({
                    "id": item_id, "name": meta["name"], "tier": meta["tier"], "ench": meta["ench"],
                    "cat": meta["cat"], "sub": meta["sub"], "weight": meta["weight"],
                    "city": city, "q": q, "bm_q": bm_q,
                    "buy_at": buy[1], "buy_src": buy[2], "buy_amount": buy[3],
                    "bm_at": bm_info[1], "bm_src": bm_info[2], "bm_amount": bm_info[3],
                    "per_kg": round(b["profit"] / meta["weight"]) if meta["weight"] else None,
                    "sold_day": round(vol[0], 1) if vol else None,
                    "depth": depth,
                    # how much this item can make in total (all units you can really flip)
                    "qty": depth["qty"] if depth else 1,
                    "total": max(depth["profit"], b["profit"]) if depth else b["profit"],
                    "total_cost": depth["cost"] if depth else b["cost"],
                    **b,
                })
    return rows


def scan_targets(store, items, premium=False, bm_age_h=3, city_age_h=168, min_profit=1000):
    """Items the Black Market wants RIGHT NOW (fresh client/live data) whose last known city
    price - possibly old - says there's money in it. Go scan these to confirm."""
    items_by_id = {i["id"]: i for i in items}
    fresh, book = price_board(store, int(bm_age_h * 3600), sources=("me", "live"))
    old, _ = price_board(store, int(city_age_h * 3600))
    now = time.time()
    out = []
    for item_id, markets in fresh.items():
        meta = items_by_id.get(item_id)
        bm = markets.get(BLACK_MARKET)
        if not meta or not bm:
            continue
        bm_orders = {q: (v["buy"][0], v["buy"]) for q, v in bm.items() if "buy" in v}
        if not bm_orders:
            continue
        bm_reqs = book.get((item_id, BLACK_MARKET, "request"), [])
        for city in CITIES:
            best_row = None
            for q, cell in (old.get(item_id, {}).get(city) or {}).items():
                if "sell" not in cell:
                    continue
                price, at, src, _amt = cell["sell"]
                fresh_enough = src in ("me", "live") and now - at < bm_age_h * 3600
                if fresh_enough:
                    continue  # already confirmed -> it's in the main list, not a scan target
                best = profit.best_bm_order(bm_orders, q)
                if not best:
                    continue
                b = profit.breakdown(price, best[1], premium)
                if b["profit"] < min_profit:
                    continue
                # every BM unit this quality could fill at a profit, at that old city price
                cost = profit.unit_cost(price)
                pot_qty, pot = 0, 0
                for p, a, rq in bm_reqs:
                    if rq <= q and profit.unit_revenue(p, premium) > cost:
                        pot_qty += a
                        pot += int((profit.unit_revenue(p, premium) - cost) * a)
                row = {"id": item_id, "name": meta["name"], "tier": meta["tier"], "ench": meta["ench"],
                       "cat": meta["cat"], "weight": meta["weight"], "city": city, "q": q, "bm_q": best[0],
                       "city_price": price, "city_at": at, "city_src": src,
                       "bm_price": best[1], "bm_at": best[2][1], "bm_amount": best[2][3],
                       "profit": b["profit"], "margin": b["margin"],
                       "pot_qty": max(pot_qty, 1), "potential": max(pot, b["profit"])}
                if not best_row or row["potential"] > best_row["potential"]:
                    best_row = row
            if best_row:
                out.append(best_row)
    return out


def item_detail(store, items, item_id, premium=False, max_age_h=24):
    meta = next((i for i in items if i["id"] == item_id), None)
    board, book = price_board(store, int(max_age_h * 3600), item_id)
    out = {"item": meta, "markets": {}}
    for market, qs in board.get(item_id, {}).items():
        out["markets"][market] = {
            str(q): {side: {"price": v[0], "at": v[1], "src": v[2], "amount": v[3]}
                     for side, v in cell.items()}
            for q, cell in qs.items()}
    plans = {}
    for city in CITIES:
        plan = _depth(book, item_id, city, premium, keep_lines=True)
        if plan:
            plans[city] = plan
    out["plans"] = plans
    return out
