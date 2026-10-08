"""
Import REAL Indian Railways trains (NCR, NER, SER, SR, CR, WCR) into the RailMind database.
Uses ONLY the Python standard library + your existing db.py  ->  nothing new to pip install.

Data source: datameet/railways (CC0)  https://github.com/datameet/railways
  Download two files (open each on GitHub -> "Raw" -> Ctrl+S) into a folder named  data/  inside the project:
      data/trains.json      data/schedules.json

NO schedules.json?  The importer automatically falls back to "terminals-only" mode: each real train is added with its
real origin + destination station, departure time, journey duration, distance, zone and classes (no intermediate stops).
Run (from the railmind folder, venv active):
      python import_railways.py --dry-run          # preview counts, writes nothing
      python import_railways.py                    # import ~300 trains (balanced across the 6 zones)
      python import_railways.py --limit 0          # import EVERY valid train in those zones
      python import_railways.py --reset            # wipe trains/stops/bookings first (users are kept)
Edit the settings just below if you want different zones / limits.
"""
import argparse, json, os, sys, zlib
from collections import defaultdict
from db import DB

# ---------------- EDIT ME ----------------
ZONES = ["NCR", "NER", "SER", "SR", "CR", "WCR"]     # zone codes as written in trains.json
DEFAULT_LIMIT = 300                                   # total trains to import (0 = all)
MIN_STOPS = 3                                         # ignore trains with fewer stops
MIN_KM = 50                                           # ignore very short runs
DURATION_TOLERANCE_MIN = 90                           # reject trains whose schedule disagrees with trains.json duration (catches corrupt rows)
# Simulated (NOT in the open dataset): typical delay by zone, used by the connection-safety AI
ZONE_DELAY = {"NCR": 25, "NER": 30, "SER": 20, "SR": 12, "CR": 22, "WCR": 15}
TYPE_POP = {"Raj": .95, "Shtb": .90, "Drnt": .90, "SF": .80, "Exp": .65}
CLASS_FLAGS = {"sleeper": "SL", "third_ac": "3A", "second_ac": "2A", "first_ac": "1A"}
PER_COACH = {"SL": 72, "3A": 72, "2A": 54, "1A": 24}
# ------------------------------------------

def mins(t):
    """'15:35:00' -> 935; 'None'/''/None -> None"""
    if not t or str(t).strip().lower() in ("none", "null", ""): return None
    try: h, m = str(t).split(":")[:2]; return int(h) * 60 + int(m)
    except ValueError: return None

def h01(*parts):  # deterministic pseudo-random 0..1 (same train -> same value every run)
    return zlib.crc32("|".join(map(str, parts)).encode()) % 1000 / 1000

def load(path):
    if not os.path.exists(path): sys.exit(f"Missing {path}. See the instructions at the top of import_railways.py")
    with open(path, encoding="utf-8") as f: return json.load(f)

def build(trains_file, sched_file, force_terminals=False):
    feats = load(trains_file); feats = feats["features"] if isinstance(feats, dict) else feats
    terminals = force_terminals or not os.path.exists(sched_file)
    by_train = defaultdict(list)
    if terminals: print("MODE: terminals-only (origin + destination per train; add data/schedules.json for full stop-by-stop timings)")
    else:
        for s in load(sched_file): by_train[str(s.get("train_number"))].append(s)
    rejected = defaultdict(int); good = []
    for f in feats:
        p = f.get("properties", f)
        no, zone = str(p.get("number", "")).strip(), p.get("zone")
        if zone not in ZONES: continue
        classes = [c for k, c in CLASS_FLAGS.items() if p.get(k)]
        if not classes: rejected["no SL/3A/2A/1A class (local/MEMU/chair-car only)"] += 1; continue
        if terminals:
            dist = p.get("distance") or 0; dur = (p.get("duration_h") or 0) * 60 + (p.get("duration_m") or 0); d0, a0 = mins(p.get("departure")), mins(p.get("arrival"))
            fc, tc = str(p.get("from_station_code") or "").strip(), str(p.get("to_station_code") or "").strip()
            if d0 is None or not dur or dist < MIN_KM: rejected["missing time/duration or too short"] += 1; continue
            if not fc or not tc or fc == tc or len(fc) > 5 or len(tc) > 5: rejected["bad station codes"] += 1; continue
            x = (d0 + dur - a0) % 1440 if a0 is not None else 0
            if min(x, 1440 - x) > DURATION_TOLERANCE_MIN: rejected["departure/arrival/duration inconsistent"] += 1; continue
            stops = [dict(code=fc, name=str(p.get("from_station_name")).title().strip(), arr=0, dep=0, km=0),
                     dict(code=tc, name=str(p.get("to_station_name")).title().strip(), arr=dur, dep=dur, km=int(dist))]
            good.append(dict(no=no, name=str(p.get("name") or no).strip()[:80], zone=zone, type=p.get("type") or "Exp",
                             dep_time=f"{d0 // 60:02d}:{d0 % 60:02d}", classes=classes, stops=stops)); continue
        rows = sorted(by_train.get(no, []), key=lambda r: r.get("id", 0))
        if len(rows) < MIN_STOPS: rejected["too few stops / no schedule"] += 1; continue
        dist = p.get("distance") or 0
        if dist < MIN_KM: rejected["too short / no distance"] += 1; continue
        stops = []
        for r in rows:
            a, d = mins(r.get("arrival")), mins(r.get("departure"))
            if a is None and d is None: continue
            a = d if a is None else a; d = a if d is None else d
            base = (int(r.get("day") or 1) - 1) * 1440
            stops.append(dict(code=str(r["station_code"]).strip(), name=str(r["station_name"]).title().strip(), arr=base + a, dep=base + d))
        if len(stops) < MIN_STOPS: rejected["too few usable stops"] += 1; continue
        if any(len(s["code"]) > 5 or not s["code"] for s in stops): rejected["station code longer than 5 chars"] += 1; continue
        if len({s["code"] for s in stops}) != len(stops): rejected["route visits a station twice"] += 1; continue
        t0 = stops[0]["dep"]; clean = True
        prev = t0
        for s in stops:
            if s["arr"] < prev or s["dep"] < s["arr"]: clean = False; break
            prev = s["dep"]
        if not clean: rejected["times not in order (corrupt schedule)"] += 1; continue
        total = stops[-1]["arr"] - t0
        expect = (p.get("duration_h") or 0) * 60 + (p.get("duration_m") or 0)
        if expect and abs(total - expect) > DURATION_TOLERANCE_MIN: rejected["schedule disagrees with trains.json duration"] += 1; continue
        for s in stops:  # km is not in the dataset per-stop -> estimate from elapsed time share of the known total distance
            frac = (s["arr"] - t0) / total if total else 0
            s["km"] = int(round(dist * frac)); s["arr"] -= t0; s["dep"] -= t0
        dep_clock = t0 % 1440
        good.append(dict(no=no, name=str(p.get("name") or no).strip()[:80], zone=zone, type=p.get("type") or "Exp",
                         dep_time=f"{dep_clock // 60:02d}:{dep_clock % 60:02d}", classes=classes, stops=stops))
    return good, rejected

def pick(good, limit):
    if not limit or limit >= len(good): return good
    pools = {z: sorted([t for t in good if t["zone"] == z], key=lambda t: (-len(t["classes"]), -len(t["stops"]), t["no"])) for z in ZONES}
    out, i = [], 0
    while len(out) < limit and any(pools.values()):
        for z in ZONES:
            if pools[z] and len(out) < limit: out.append(pools[z].pop(0))
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trains", default="data/trains.json"); ap.add_argument("--schedules", default="data/schedules.json")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--terminals-only", action="store_true")
    ap.add_argument("--reset", action="store_true", help="delete ALL trains, stops, inventory, bookings, passengers first (users kept)")
    a = ap.parse_args()
    good, rejected = build(a.trains, a.schedules, a.terminals_only)
    chosen = pick(good, a.limit)
    print(f"Valid trains in {','.join(ZONES)}: {len(good)}   -> importing {len(chosen)}")
    for z in ZONES: print(f"  {z:4} valid {sum(t['zone']==z for t in good):4}   importing {sum(t['zone']==z for t in chosen):4}")
    if rejected: print("Skipped:", *[f"{n} x {why}" for why, n in rejected.items()], sep="\n  ")
    if a.dry_run: return
    D = DB(); D.init_schema()
    if a.reset:
        for tb in ("passengers", "bookings", "inventory", "stops", "trains"): D.q(f"DELETE FROM {tb}")
    else:  # drop the 6 fictional sample trains from seed.py if nobody booked them
        from seed import TRAINS
        for t in TRAINS:
            if not D.one("SELECT 1 AS x FROM bookings WHERE train_no=?", (t[0],)):
                for tb, col in (("stops", "train_no"), ("inventory", "train_no"), ("trains", "number")): D.q(f"DELETE FROM {tb} WHERE {col}=?", (t[0],))
    added = skipped = 0
    for t in chosen:
        if D.one("SELECT 1 AS x FROM trains WHERE number=?", (t["no"],)): skipped += 1; continue   # already present (e.g. has bookings)
        pop = max(.3, min(.98, TYPE_POP.get(t["type"], .55) + (h01(t["no"], "p") - .5) * .2))
        delay = ZONE_DELAY[t["zone"]] * (.5 + h01(t["no"], "d"))
        D.q("INSERT INTO trains VALUES(?,?,?,?,?,?)", (t["no"], t["name"], t["dep_time"], round(pop, 2), round(delay, 1), round(delay * .8 + 3, 1)))
        for i, s in enumerate(t["stops"], 1):
            D.q("INSERT INTO stops(train_no,seq,code,name,arr_min,dep_min,km) VALUES(?,?,?,?,?,?,?)", (t["no"], i, s["code"], s["name"], s["arr"], s["dep"], s["km"]))
        for c in t["classes"]:
            coaches = {"SL": 4 + int(pop * 6), "3A": 2 + int(pop * 4), "2A": 1 + int(pop * 2), "1A": 1}[c]
            D.q("INSERT INTO inventory(train_no,cls,coaches,per_coach,demand) VALUES(?,?,?,?,?)", (t["no"], c, coaches, PER_COACH[c], round(.35 + pop * .55, 2)))
        added += 1
    try: D.q("CREATE INDEX ix_stops_train_code ON stops(train_no, code)")   # speeds up search; error if it already exists is harmless
    except Exception: pass
    D.commit()
    print(f"\nDone: {added} trains added, {skipped} skipped (already in DB).")
    hubs = [r["code"] for r in D.q("SELECT code, COUNT(*) AS n FROM stops GROUP BY code ORDER BY n DESC LIMIT 6")]
    pairs = []
    for x in hubs:
        for y in hubs:
            if x != y:
                n = D.one("SELECT COUNT(*) AS n FROM stops a JOIN stops b ON a.train_no=b.train_no WHERE a.code=? AND b.code=? AND a.seq<b.seq", (x, y))["n"]
                if n: pairs.append((n, x, y))
    print("Try searching:", ", ".join(f"{x}->{y} ({n} trains)" for n, x, y in sorted(pairs, reverse=True)[:6]))
    D.close()

if __name__ == "__main__": main()
