"""Live market orders from every player running the Albion Data Client (you, your friend,
and everyone else on Europe), via the Albion Data Project's public NATS stream.

Each order carries its exact amount, so scans from your friend's PC show up here within
seconds - no server or port forwarding needed. Plain stdlib socket NATS client.
"""
import json
import socket
import threading
import time

HOST, PORT = "nats.albion-online-data.com", 34222          # 34222 = Europe
USER, PASSWORD = "public", "thenewalbiondata"                # public read-only credentials
SUBJECT = "marketorders.deduped.bulk"

state = {"connected": False, "received": 0, "kept": 0, "last_at": 0, "error": ""}


def run(on_orders, accept, stop_event=None):
    """on_orders(list_of_raw_orders) is called in small batches; accept(raw) filters."""
    stop_event = stop_event or threading.Event()
    while not stop_event.is_set():
        try:
            _session(on_orders, accept, stop_event)
        except Exception as e:  # network hiccup: reconnect
            state.update(connected=False, error=str(e))
        if not stop_event.is_set():
            time.sleep(10)


def _session(on_orders, accept, stop_event):
    sock = socket.create_connection((HOST, PORT), timeout=30)
    sock.settimeout(90)
    f = sock.makefile("rb")
    if not f.readline().startswith(b"INFO"):
        raise ConnectionError("unexpected NATS greeting")
    connect = {"verbose": False, "pedantic": False, "user": USER, "pass": PASSWORD,
               "name": "albion-bm-helper", "lang": "python", "version": "1.0"}
    sock.sendall(b"CONNECT " + json.dumps(connect).encode() + b"\r\nPING\r\n")
    sock.sendall(f"SUB {SUBJECT} 1\r\n".encode())
    state.update(connected=True, error="")
    pending, flushed = [], time.time()
    while not stop_event.is_set():
        line = f.readline()
        if not line:
            raise ConnectionError("live feed closed")
        if line.startswith(b"PING"):
            sock.sendall(b"PONG\r\n")
        elif line.startswith(b"MSG"):
            size = int(line.split()[-1])
            body = f.read(size + 2)[:-2]
            try:
                data = json.loads(body)
            except ValueError:
                continue
            orders = data if isinstance(data, list) else [data]
            state["received"] += len(orders)
            kept = [o for o in orders if accept(o)]
            state["kept"] += len(kept)
            pending += kept
        elif line.startswith(b"-ERR"):
            raise ConnectionError(line.decode(errors="replace").strip())
        if pending and time.time() - flushed > 2:
            on_orders(pending)
            state["last_at"] = int(time.time())
            pending, flushed = [], time.time()
    sock.close()
