"""Albion Online Data Project public API client (Europe server)."""
import json
import time
import urllib.error
import urllib.parse

import http_util

HOST = "https://europe.albion-online-data.com"
MAX_URL = 3900          # API hard limit is 4096 characters
PAUSE = 0.4             # seconds between calls (API allows 180/min, 300/5min)
UA = "albion-bm-helper/1.0 (personal black market tool)"


def _get_json(url, tries=4):
    last = None
    for attempt in range(tries):
        try:
            return json.loads(http_util.get(url, timeout=60))
        except http_util.HTTPStatusError as e:
            last = e
            if e.code == 429 or e.code >= 500:
                time.sleep(10 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Albion Data API not reachable ({last})")


def _batches(ids, prefix, suffix):
    batch, length = [], len(prefix) + len(suffix)
    for i in ids:
        add = len(urllib.parse.quote(i, safe="@_")) + 1
        if batch and length + add > MAX_URL:
            yield batch
            batch, length = [], len(prefix) + len(suffix)
        batch.append(i)
        length += add
    if batch:
        yield batch


def _locs(names):
    return ",".join(urllib.parse.quote(n) for n in names)


def fetch_prices(ids, locations, on_batch, should_stop=lambda: False):
    """Current prices, all 5 qualities. on_batch(rows, done, total) is called per request."""
    prefix = HOST + "/api/v2/stats/prices/"
    suffix = ".json?locations=" + _locs(locations) + "&qualities=1,2,3,4,5"
    batches = list(_batches(ids, prefix, suffix))
    done = 0
    for b in batches:
        if should_stop():
            return
        rows = _get_json(prefix + ",".join(urllib.parse.quote(i, safe="@_") for i in b) + suffix)
        done += len(b)
        on_batch(rows, done, len(ids))
        time.sleep(PAUSE)


def fetch_bm_history(ids, on_batch, days=7):
    """Daily Black Market sales (how many items the BM actually bought) for the last `days`."""
    prefix = HOST + "/api/v2/stats/history/"
    suffix = ".json?locations=" + _locs(["Black Market"]) + "&time-scale=24&qualities=1,2,3,4,5"
    batches = list(_batches(ids, prefix, suffix))
    done = 0
    cutoff = time.time() - days * 86400
    for b in batches:
        rows = _get_json(prefix + ",".join(urllib.parse.quote(i, safe="@_") for i in b) + suffix)
        out = []
        for r in rows:
            pts = [p for p in r.get("data", [])
                   if _ts(p.get("timestamp")) >= cutoff]
            sold = sum(p.get("item_count", 0) for p in pts)
            avg = round(sum(p.get("avg_price", 0) * p.get("item_count", 0) for p in pts) / sold) if sold else 0
            out.append((r["item_id"], int(r["quality"]), sold / days, avg, len(pts), int(time.time())))
        # an item/quality the API returned nothing for = the BM bought none of it lately
        got = {(o[0], o[1]) for o in out}
        out += [(i, q, 0.0, 0, 0, int(time.time())) for i in b for q in range(1, 6) if (i, q) not in got]
        done += len(b)
        on_batch(out, done, len(ids))
        time.sleep(PAUSE)


def _ts(s):
    from store import parse_api_date
    return parse_api_date(s)
