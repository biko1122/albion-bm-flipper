"""Albion Black Market helper - local server.

Run:  python server.py      then open http://127.0.0.1:8765
If the Albion Data Client is installed, it is started automatically in the background
and sends what you see in the in-game market to this tool (exact amounts per order).
Flags: --no-client  --no-browser  --rebuild-items
"""
import atexit
import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import aodp
import engine
import items as items_mod
import live_feed
from store import BLACK_MARKET, CITIES, Store, location_name

HOST, PORT = "127.0.0.1", 8765
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
STATIC = os.path.join(ROOT, "static")
os.makedirs(DATA, exist_ok=True)

store = Store(os.path.join(DATA, "albion.db"))
ITEMS = []
ITEM_IDS = set()


def start_live_feed():
    """Everyone's client scans (your friend's too) arrive here live, with amounts."""
    def on_orders(raw):
        orders = [n for n in (normalise_order(o, scale=1) for o in raw) if n]
        if orders:
            store.save_live(orders)

    def accept(o):
        return o.get("ItemTypeId") in ITEM_IDS or (
            o.get("EnchantmentLevel") and f"{o.get('ItemTypeId')}@{o.get('EnchantmentLevel')}" in ITEM_IDS)

    threading.Thread(target=live_feed.run, args=(on_orders, accept), daemon=True).start()

    def housekeeping():
        while True:
            time.sleep(3600)
            try:
                store.prune_local()
            except Exception:
                traceback.print_exc()
    threading.Thread(target=housekeeping, daemon=True).start()
job = {"running": False, "stage": "", "done": 0, "total": 0, "error": "", "started": 0}
job_lock = threading.Lock()


def run_refresh():
    try:
        ids = [i["id"] for i in ITEMS]
        job.update(stage="prices", done=0, total=len(ids), error="", started=time.time())

        def on_prices(rows, done, total):
            store.save_api_prices(rows)
            job.update(done=done, total=total)

        aodp.fetch_prices(ids, [BLACK_MARKET] + CITIES, on_prices)
        store.set_meta("last_refresh", int(time.time()))

        # Sales history only for items that look profitable (keeps it fast).
        rows = engine.opportunities(store, ITEMS, premium=False, max_age_h=24)
        hist_ids = sorted({r["id"] for r in rows})
        job.update(stage="history", done=0, total=len(hist_ids))
        if hist_ids:
            def on_hist(rows, done, total):
                store.save_history(rows)
                job.update(done=done, total=total)
            aodp.fetch_bm_history(hist_ids, on_hist)
        store.prune_local()
        job.update(stage="done")
    except Exception as e:  # keep the server alive, show the error in the page
        traceback.print_exc()
        job.update(stage="error", error=str(e))
    finally:
        job["running"] = False


def normalise_order(o, scale=10000):
    """scale: your own client sends silver x 10000; the live feed is already in silver."""
    city = location_name(o.get("LocationId"))
    item = o.get("ItemTypeId") or ""
    typ = (o.get("AuctionType") or "").lower()
    if not city or not item or typ not in ("offer", "request"):
        return None
    ench = int(o.get("EnchantmentLevel") or 0)
    if ench and "@" not in item:
        item = f"{item}@{ench}"
    if item not in ITEM_IDS:
        return None
    raw = int(o.get("UnitPriceSilver") or 0)
    price = round(raw / scale)
    if price <= 0:
        return None
    return {"id": int(o.get("Id")), "item_id": item, "city": city,
            "quality": int(o.get("QualityLevel") or 1), "price": price,
            "amount": int(o.get("Amount") or 0), "type": typ, "expires": o.get("Expires") or ""}


class Handler(BaseHTTPRequestHandler):
    server_version = "AlbionBM/1.0"

    def log_message(self, fmt, *args):
        if "/api/" not in self.path:  # keep console quiet
            pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[-1] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/api/status":
                return self._send(200, {
                    "items": len(ITEMS), "job": job,
                    "last_refresh": int(store.get_meta("last_refresh", 0) or 0),
                    "local": store.local_stats(), "now": int(time.time()),
                    "client": {"installed": os.path.exists(CLIENT_EXE), "running": client_running()},
                    "live": live_feed.state,
                    "cities": CITIES})
            if url.path == "/api/opportunities":
                sources = tuple(s for s in q.get("sources", "api,me,live").split(",")
                                if s in engine.ALL_SOURCES) or engine.ALL_SOURCES
                rows = engine.opportunities(
                    store, ITEMS, premium=q.get("premium") == "1",
                    mode=q.get("mode", "instant"), max_age_h=float(q.get("max_age", 6)),
                    sources=sources)
                return self._send(200, {"rows": rows, "now": int(time.time())})
            if url.path == "/api/scan":
                rows = engine.scan_targets(
                    store, ITEMS, premium=q.get("premium") == "1",
                    bm_age_h=float(q.get("bm_age", 3)), min_profit=int(q.get("min_profit", 1000)))
                return self._send(200, {"rows": rows, "now": int(time.time())})
            if url.path == "/api/item":
                return self._send(200, engine.item_detail(
                    store, ITEMS, q.get("id", ""), premium=q.get("premium") == "1",
                    max_age_h=float(q.get("max_age", 24))))
            return self._static(url.path)
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"error": str(e)})

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if url.path == "/api/refresh":
            with job_lock:
                if not job["running"]:
                    job["running"] = True
                    threading.Thread(target=run_refresh, daemon=True).start()
            return self._send(200, {"ok": True})
        if url.path == "/api/dismiss":
            d = json.loads(body or b"{}")
            if d.get("id") and d.get("city"):
                store.dismiss(d["id"], d["city"])
            return self._send(200, {"ok": True})
        # ----- Albion Data Client private ingest: POST <base>/<topic> -----
        if url.path == "/marketorders.ingest":
            try:
                data = json.loads(body or b"{}")
                orders = [n for n in (normalise_order(o) for o in data.get("Orders") or []) if n]
                if orders:
                    store.save_my_page(orders)
                    o = orders[0]
                    print(f"[client] {len(orders)} orders  {o['item_id']} q{o['quality']} "
                          f"@ {o['city']}  {o['type']} {o['price']:,} silver")
            except Exception:
                traceback.print_exc()
            return self._send(200, {"ok": True})
        if url.path.endswith(".ingest") or url.path.startswith("/market") or url.path in ("/skills",):
            return self._send(200, {"ok": True})  # other topics: accepted, not needed
        return self._send(404, {"error": "not found"})

    def _static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        full = os.path.normpath(os.path.join(STATIC, path.lstrip("/")))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            return self._send(404, "not found", "text/plain")
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            return self._send(200, f.read(), ctype)


def _find_client():
    """The copy bundled with this tool (client\\) first, then a normal installation."""
    for path in (os.path.join(ROOT, "client", "albiondata-client.exe"),
                 os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                              "Albion Data Client", "albiondata-client.exe")):
        if os.path.exists(path):
            return path
    return os.path.join(ROOT, "client", "albiondata-client.exe")


CLIENT_EXE = _find_client()
client_proc = None


def start_client(link):
    """Start the Albion Data Client in the background, sending its data to this tool."""
    global client_proc
    if not os.path.exists(CLIENT_EXE):
        print("  Albion Data Client is not installed: the tool works with public prices only.")
        return
    # Close any copy already running (e.g. the one the installer puts in the tray).
    subprocess.run(["taskkill", "/im", "albiondata-client.exe", "/f"],
                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    log = open(os.path.join(DATA, "client.log"), "w", encoding="utf-8", errors="replace")
    client_proc = subprocess.Popen([CLIENT_EXE, "-p", link], cwd=DATA,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
    _tie_to_this_process(client_proc)
    atexit.register(stop_client)
    print("  Albion Data Client started: open the market in the game and prices show up here.")


_job = None


def _tie_to_this_process(proc):
    """Windows Job Object: when this window closes (even with X), the client closes too."""
    global _job
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.OpenProcess.restype = wintypes.HANDLE

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in
                        ("r", "w", "o", "rt", "wt", "ot")]

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("Basic", Basic), ("Io", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        job = k32.CreateJobObjectW(None, None)
        info = Extended()
        info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
        handle = k32.OpenProcess(0x0101, False, proc.pid)  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        if not k32.AssignProcessToJobObject(job, handle):
            print("  (note: the client may stay open after you close this window)")
        k32.CloseHandle(handle)
        _job = job  # keep the handle open for as long as this process lives
    except Exception as e:
        print("  (note: could not tie the client to this window:", e, ")")


def stop_client():
    if client_proc and client_proc.poll() is None:
        client_proc.terminate()


def client_running():
    return bool(client_proc and client_proc.poll() is None)


def main():
    global ITEMS, ITEM_IDS, PORT
    for a in sys.argv:
        if a.startswith("--port="):
            PORT = int(a.split("=", 1)[1])
    ITEMS = items_mod.build(DATA, force="--rebuild-items" in sys.argv)
    ITEM_IDS = {i["id"] for i in ITEMS}
    if "--no-live" not in sys.argv:
        start_live_feed()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    link = f"http://{HOST}:{PORT}"
    print(f"\n  Albion Black Market helper is running:  {link}")
    if "--no-client" not in sys.argv:
        start_client(link)
    print("  Close this window to stop everything.\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(link)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_client()


if __name__ == "__main__":
    main()
