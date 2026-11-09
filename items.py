"""Builds the list of items the Black Market can buy, from the public ao-bin-dumps.

Downloads once to data/cache, then writes a compact data/items.json:
  {id, base, name, tier, ench, weight, cat, sub}
"""
import json
import os
import re

import http_util

ITEMS_TXT_URL = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/formatted/items.txt"
ITEMS_JSON_URL = "https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/items.json"

# Item groups / shop categories the Black Market buys (gear only, no resources, no tools).
GROUPS = ("equipmentitem", "weapon", "transformationweapon")
CATEGORIES = {"weapons", "armors", "head", "shoes", "offhands", "capes", "bags", "gathering"}
MIN_TIER, MAX_TIER = 4, 8

_LINE = re.compile(r"^\s*\d+:\s*(\S+)\s*(?::\s*(.*?))?\s*$")


def _download(url, path):
    http_util.get(url, timeout=300, out_path=path + ".part")
    os.replace(path + ".part", path)


def _base_meta(raw_path):
    with open(raw_path, encoding="utf-8") as f:
        items = json.load(f)["items"]
    meta = {}
    for group in GROUPS:
        entries = items.get(group) or []
        if isinstance(entries, dict):
            entries = [entries]
        for it in entries:
            uid = it.get("@uniquename", "")
            cat = it.get("@shopcategory")
            if cat not in CATEGORIES:
                continue
            # Gathering *tools* live in the "weapon" group; the BM does not buy them.
            if group == "weapon" and cat == "gathering":
                continue
            if it.get("@tradable") == "false" or uid.startswith("UNIQUE") or "_TEST" in uid:
                continue
            try:
                tier = int(it.get("@tier", 0))
            except ValueError:
                continue
            if not (MIN_TIER <= tier <= MAX_TIER):
                continue
            meta[uid] = {
                "tier": tier,
                "weight": float(it.get("@weight") or 0),
                "cat": cat,
                "sub": it.get("@shopsubcategory1") or "",
            }
    return meta


def build(data_dir, force=False):
    out_path = os.path.join(data_dir, "items.json")
    if os.path.exists(out_path) and not force:
        with open(out_path, encoding="utf-8") as f:
            return json.load(f)

    cache = os.path.join(data_dir, "cache")
    os.makedirs(cache, exist_ok=True)
    txt_path = os.path.join(cache, "items.txt")
    raw_path = os.path.join(cache, "items_raw.json")
    if force or not os.path.exists(txt_path):
        print("[items] downloading item names ...")
        _download(ITEMS_TXT_URL, txt_path)
    if force or not os.path.exists(raw_path):
        print("[items] downloading item data (~17 MB, one time only) ...")
        _download(ITEMS_JSON_URL, raw_path)

    meta = _base_meta(raw_path)
    result, seen = [], set()
    with open(txt_path, encoding="utf-8") as f:
        for line in f:
            m = _LINE.match(line)
            if not m:
                continue
            item_id, name = m.group(1), (m.group(2) or "").strip()
            base, _, ench = item_id.partition("@")
            if base not in meta or item_id in seen:
                continue
            seen.add(item_id)
            result.append({"id": item_id, "base": base, "name": name or base,
                           "ench": int(ench or 0), **meta[base]})
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"[items] {len(result)} Black Market items ready")
    return result
