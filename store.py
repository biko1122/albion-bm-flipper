"""SQLite storage: prices from the public API, live orders (your client + everyone's live
feed), what you marked as gone, and Black Market sales history."""
import sqlite3
import threading
import time
from datetime import datetime, timezone

CITIES = ["Caerleon", "Bridgewatch", "Martlock", "Lymhurst", "Fort Sterling", "Thetford", "Brecilien"]
BLACK_MARKET = "Black Market"
MARKETS = [BLACK_MARKET] + CITIES

# Game location ids -> market name.
LOCATION_IDS = {
    "3003": BLACK_MARKET, "3005": "Caerleon", "2004": "Bridgewatch", "3008": "Martlock",
    "1002": "Lymhurst", "4002": "Fort Sterling", "7": "Thetford", "0007": "Thetford",
    "5003": "Brecilien",
}


def location_name(loc_id):
    s = str(loc_id if loc_id is not None else "").strip()
    if s in LOCATION_IDS:
        return LOCATION_IDS[s]
    head = s.split("-")[0].split("@")[0]
    return LOCATION_IDS.get(head) or LOCATION_IDS.get(head.lstrip("0")) or None


def parse_api_date(s):
    """API dates are UTC without 'Z'. Year 1 means 'no data'. Returns unix seconds or 0."""
    if not s or s.startswith("0001"):
        return 0
    try:
        return int(datetime.fromisoformat(s.replace("Z", "")).replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return 0


class Store:
    def __init__(self, path):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS api_prices(
            item_id TEXT, city TEXT, quality INT,
            sell_min INT, sell_min_at INT, buy_max INT, buy_max_at INT,
            PRIMARY KEY(item_id, city, quality));
        CREATE TABLE IF NOT EXISTS local_orders(
            id INTEGER PRIMARY KEY, item_id TEXT, city TEXT, quality INT,
            price INT, amount INT, type TEXT, expires TEXT, seen_at INT);
        CREATE INDEX IF NOT EXISTS lo_item ON local_orders(item_id, city);
        CREATE TABLE IF NOT EXISTS snapshots(
            item_id TEXT, city TEXT, type TEXT, at INT, PRIMARY KEY(item_id, city, type));
        CREATE TABLE IF NOT EXISTS dismissed(
            item_id TEXT, city TEXT, at INT, PRIMARY KEY(item_id, city));
        CREATE TABLE IF NOT EXISTS bm_history(
            item_id TEXT, quality INT, daily_avg REAL, avg_price INT, days INT, updated_at INT,
            PRIMARY KEY(item_id, quality));
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        """)
        cols = [r[1] for r in self.db.execute("PRAGMA table_info(local_orders)")]
        if "src" not in cols:  # older databases: everything in there came from your own client
            self.db.execute("ALTER TABLE local_orders ADD COLUMN src TEXT DEFAULT 'me'")
        self.db.execute("CREATE INDEX IF NOT EXISTS lo_seen ON local_orders(seen_at)")
        self.db.commit()
        if self.get_meta("snapshots_v2") is None:
            # data saved before page tracking: the last time you saw each item is its snapshot
            with self.lock:
                self.db.execute(
                    "INSERT OR REPLACE INTO snapshots SELECT item_id, city, type, MAX(seen_at) "
                    "FROM local_orders WHERE src='me' GROUP BY item_id, city, type")
                self.db.commit()
            self.set_meta("snapshots_v2", 1)

    # ---------- meta ----------
    def set_meta(self, key, value):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, str(value)))
            self.db.commit()

    def get_meta(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    # ---------- public API prices ----------
    def save_api_prices(self, rows):
        data = [(r["item_id"], r["city"], int(r["quality"]),
                 int(r.get("sell_price_min") or 0), parse_api_date(r.get("sell_price_min_date")),
                 int(r.get("buy_price_max") or 0), parse_api_date(r.get("buy_price_max_date")))
                for r in rows]
        with self.lock:
            self.db.executemany("INSERT OR REPLACE INTO api_prices VALUES(?,?,?,?,?,?,?)", data)
            self.db.commit()

    def api_prices(self, item_id=None):
        with self.lock:
            if item_id:
                return self.db.execute("SELECT * FROM api_prices WHERE item_id=?", (item_id,)).fetchall()
            return self.db.execute("SELECT * FROM api_prices").fetchall()

    # ---------- orders: your client (src 'me') and the live feed (src 'live') ----------
    def _upsert(self, orders, src, now):
        self.db.executemany(
            "INSERT INTO local_orders(id,item_id,city,quality,price,amount,type,expires,seen_at,src) "
            "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "price=excluded.price, amount=excluded.amount, seen_at=excluded.seen_at, "
            "expires=excluded.expires, src=CASE WHEN local_orders.src='me' THEN 'me' ELSE excluded.src END",
            [(o["id"], o["item_id"], o["city"], o["quality"], o["price"], o["amount"],
              o["type"], o["expires"], now, src) for o in orders])

    def save_my_page(self, orders):
        """One market page you just looked at. Remember when you looked at each item there:
        orders of that item not seen around this moment are treated as gone (sold/filled),
        and older public-API prices for it stop counting (see engine.SNAPSHOT_WINDOW)."""
        now = int(time.time())
        keys = {(o["item_id"], o["city"], o["type"]) for o in orders}
        with self.lock:
            self.db.executemany("INSERT OR REPLACE INTO snapshots VALUES(?,?,?,?)",
                                [(*k, now) for k in keys])
            self._upsert(orders, "me", now)
            self.db.commit()

    def save_live(self, orders):
        with self.lock:
            self._upsert(orders, "live", int(time.time()))
            self.db.commit()

    def local_orders(self, max_age_s, item_id=None, sources=("me", "live")):
        since = int(time.time()) - max_age_s
        marks = ",".join("?" * len(sources))
        sql = (f"SELECT item_id, city, quality, price, amount, type, seen_at, src FROM local_orders "
               f"WHERE seen_at>=? AND src IN ({marks})")
        args = [since, *sources]
        if item_id:
            sql += " AND item_id=?"
            args.append(item_id)
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def snapshots(self, item_id=None):
        with self.lock:
            q = "SELECT item_id, city, type, at FROM snapshots" + (" WHERE item_id=?" if item_id else "")
            return {(r[0], r[1], r[2]): r[3] for r in self.db.execute(q, (item_id,) if item_id else ())}

    def local_stats(self):
        with self.lock:
            me = self.db.execute("SELECT COUNT(*), MAX(seen_at) FROM local_orders WHERE src='me'").fetchone()
            live = self.db.execute("SELECT COUNT(*), MAX(seen_at) FROM local_orders WHERE src='live'").fetchone()
        return {"count": me[0] or 0, "last_at": me[1] or 0, "live_count": live[0] or 0, "live_last_at": live[1] or 0}

    def prune_local(self):
        now = int(time.time())
        with self.lock:
            self.db.execute("DELETE FROM local_orders WHERE src='live' AND seen_at < ?", (now - 2 * 86400,))
            self.db.execute("DELETE FROM local_orders WHERE seen_at < ?", (now - 7 * 86400,))
            self.db.execute("DELETE FROM dismissed WHERE at < ?", (now - 7 * 86400,))
            self.db.commit()

    # ---------- "this order is gone" ----------
    def dismiss(self, item_id, city):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO dismissed VALUES(?,?,?)", (item_id, city, int(time.time())))
            self.db.commit()

    def dismissed(self):
        with self.lock:
            return {(r[0], r[1]): r[2] for r in self.db.execute("SELECT item_id, city, at FROM dismissed")}

    # ---------- Black Market sales history ----------
    def save_history(self, rows):
        with self.lock:
            self.db.executemany("INSERT OR REPLACE INTO bm_history VALUES(?,?,?,?,?,?)", rows)
            self.db.commit()

    def all_history(self):
        with self.lock:
            return {(r[0], r[1]): (r[2], r[3], r[4]) for r in
                    self.db.execute("SELECT item_id, quality, daily_avg, avg_price, days FROM bm_history")}
