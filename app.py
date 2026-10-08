"""RailMind - AI-powered railway booking (Flask REST backend). Run: python app.py"""
import os, re, secrets, threading, zlib
from datetime import datetime, timedelta, date as ddate
from flask import Flask, g, jsonify, request, session, render_template, Response
from werkzeug.security import generate_password_hash, check_password_hash
from db import DB
from seed import seed
from seats import CLASSES, locate
from ai_engine import AIEngine, MIN_TRANSFER
from ticket_pdf import build_ticket

app = Flask(__name__)
app.config.update(SECRET_KEY=os.getenv("SECRET_KEY") or secrets.token_hex(32), SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True)
LOCK = threading.Lock()   # serialises seat allocation inside one process (use SELECT ... FOR UPDATE for multi-process MySQL)
_boot = DB(); _boot.init_schema(); seed(_boot); _boot.close()
ai = AIEngine()
FMT = "%d %b %Y, %H:%M"

def db():
    if "db" not in g: g.db = DB()
    return g.db
@app.teardown_appcontext
def _close(_):
    d = g.pop("db", None)
    if d: d.close()
def err(msg, code=400): return jsonify(error=msg), code
def login_required(f):
    from functools import wraps
    @wraps(f)
    def w(*a, **k): return f(*a, **k) if session.get("uid") else err("Please log in first.", 401)
    return w

# ---------- helpers ----------
def parse_date(s):
    try: d = datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError): raise ValueError("Invalid date (use YYYY-MM-DD).")
    if d < ddate.today() or d > ddate.today() + timedelta(days=120): raise ValueError("Date must be within the next 120 days.")
    return d
def clock(train, d, mins):  # real datetime at a stop; d = date the train leaves its origin
    h, m = map(int, train["dep_time"].split(":"))
    return datetime(d.year, d.month, d.day, h, m) + timedelta(minutes=mins)
def leg(D, no, a, b):
    s = {r["code"]: r for r in D.q("SELECT * FROM stops WHERE train_no=? AND code IN (?,?)", (no, a, b))}
    return (s[a], s[b]) if a in s and b in s and s[a]["seq"] < s[b]["seq"] else (None, None)
def taken(D, inv, d):
    base = zlib.crc32(f"{inv['train_no']}{inv['cls']}{d}".encode()) % 1000 / 1000   # simulated pre-existing demand
    cap = inv["coaches"] * inv["per_coach"]
    sold = D.one("SELECT COUNT(*) AS n FROM passengers WHERE train_no=? AND journey_date=? AND cls=?", (inv["train_no"], str(d), inv["cls"]))["n"]
    return int(cap * (inv["demand"] * .6 + base * .55)) + sold
def is_peak(d): return int(d.month in (4, 5, 6, 10, 11, 12) or d.weekday() >= 4)
def base_fare(cls, km):
    _, _, rate, fee = CLASSES[cls]; return max(km * rate, 50) + fee
def new_pnr(D):
    while True:  # unique 10-digit number, first digit 1-9
        p = str(secrets.randbelow(9 * 10**9) + 10**9)
        if not D.one("SELECT 1 AS x FROM bookings WHERE pnr=?", (p,)): return p

def booking_detail(D, pnr):
    b = D.one("SELECT * FROM bookings WHERE pnr=?", (pnr,))
    if not b: return None
    t = D.one("SELECT * FROM trains WHERE number=?", (b["train_no"],)); fs, ts = leg(D, b["train_no"], b["from_code"], b["to_code"])
    d = datetime.strptime(b["journey_date"], "%Y-%m-%d").date()
    pax = D.q("SELECT name,age,gender,coach,seat_no,berth,status,wl_no FROM passengers WHERE booking_id=? ORDER BY id", (b["id"],))
    out = dict(pnr=b["pnr"], train_no=t["number"], train_name=t["name"], date=b["journey_date"], cls=b["cls"], fare=b["fare"],
               from_code=fs["code"], from_name=fs["name"], to_code=ts["code"], to_name=ts["name"],
               dep_time=clock(t, d, fs["dep_min"]).strftime(FMT), arr_time=clock(t, d, ts["arr_min"]).strftime(FMT),
               passengers=pax, status="CNF" if all(p["status"] == "CNF" for p in pax) else "WL", user_id=b["user_id"])
    wl = [p["wl_no"] for p in pax if p["status"] == "WL"]
    if wl:  # AI: confirmation chance for a waitlisted PNR (answers "Gap 1" in the PPT)
        days = max((d - ddate.today()).days, 0)
        out["ai"] = ai.advise(days, 1, b["cls"], t["popularity"], is_peak(d), wl=min(wl))
        out["ai"]["note"] = (f"{out['ai']['wl_prob']:.0%} chance of confirmation. " + ("Odds are forecast to improve - no need to cancel yet."
                             if out["ai"]["advice"] == "WAIT" else "Odds are not forecast to improve - consider a backup booking."))
    return out

# ---------- pages & auth ----------
@app.get("/")
def index(): return render_template("index.html")

@app.post("/api/register")
def register():
    j = request.get_json(silent=True) or {}
    name, email, pw = (j.get("name") or "").strip(), (j.get("email") or "").strip().lower(), j.get("password") or ""
    if not name or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or len(pw) < 8: return err("Enter a name, valid email and a password of 8+ characters.")
    D = db()
    if D.one("SELECT 1 AS x FROM users WHERE email=?", (email,)): return err("Email already registered.", 409)
    D.q("INSERT INTO users(name,email,pw_hash) VALUES(?,?,?)", (name, email, generate_password_hash(pw))); D.commit()
    session["uid"], session["name"] = D.lastrowid, name
    return jsonify(name=name)
@app.post("/api/login")
def login():
    j = request.get_json(silent=True) or {}
    u = db().one("SELECT * FROM users WHERE email=?", ((j.get("email") or "").strip().lower(),))
    if not u or not check_password_hash(u["pw_hash"], j.get("password") or ""): return err("Wrong email or password.", 401)
    session["uid"], session["name"] = u["id"], u["name"]; return jsonify(name=u["name"])
@app.post("/api/logout")
def logout(): session.clear(); return jsonify(ok=True)
@app.get("/api/me")
def me(): return jsonify(name=session.get("name"))
@app.get("/api/stations")
def stations(): return jsonify(db().q("SELECT code, MIN(name) AS name FROM stops GROUP BY code ORDER BY name"))
@app.get("/api/trains")
def trains(): return jsonify(db().q("SELECT number,name FROM trains ORDER BY number"))

# ---------- search + AI ranking ----------
@app.get("/api/search")
def search():
    D, a, b = db(), request.args.get("from", "").upper(), request.args.get("to", "").upper()
    try: d = parse_date(request.args.get("date"))
    except ValueError as e: return err(str(e))
    if not a or not b or a == b: return err("Choose two different stations.")
    days, peak, cands = (d - ddate.today()).days, is_peak(d), []
    on_route = D.q("SELECT t.* FROM trains t JOIN stops x ON x.train_no=t.number JOIN stops y ON y.train_no=t.number "
                   "WHERE x.code=? AND y.code=? AND x.seq<y.seq", (a, b))
    for t in on_route:
        fs, ts = leg(D, t["number"], a, b)
        classes = []
        for inv in D.q("SELECT * FROM inventory WHERE train_no=?", (t["number"],)):
            cap, tk = inv["coaches"] * inv["per_coach"], taken(D, inv, d)
            adv = ai.advise(days, min(tk / cap, 1), inv["cls"], t["popularity"], peak, wl=(tk - cap + 1) if tk >= cap else None)
            fare = round(base_fare(inv["cls"], ts["km"] - fs["km"]) * ai.fare_multiplier(days, min(tk / cap, 1)))
            classes.append(dict(cls=inv["cls"], fare=fare, status="AVL" if tk < cap else "WL", count=cap - tk if tk < cap else tk - cap + 1, **adv))
        dep, arr = clock(t, d, fs["dep_min"]), clock(t, d, ts["arr_min"])
        cands.append(dict(train_no=t["number"], name=t["name"], from_name=fs["name"], to_name=ts["name"], dep=dep.strftime(FMT), arr=arr.strftime(FMT),
                          duration_min=int((arr - dep).total_seconds() // 60), avg_delay=t["avg_delay"], classes=classes,
                          dep_hour=dep.hour, min_fare=min(c["fare"] for c in classes)))
    if not cands: return jsonify(results=[])
    hist = D.q("SELECT b.cls, t.dep_time FROM bookings b JOIN trains t ON t.number=b.train_no WHERE b.user_id=?", (session.get("uid", 0),))
    prof = dict(cls=[h["cls"] for h in hist], hours=[int(h["dep_time"][:2]) for h in hist])
    for c in cands: c["class_names"] = [x["cls"] for x in c["classes"]]
    scores = ai.recommend(prof, [dict(c, classes=c["class_names"]) for c in cands])
    for c in cands: c["score"], c["why"] = scores[c["train_no"]]; c.pop("class_names")
    cands.sort(key=lambda c: -c["score"]); cands[0]["best"] = True
    return jsonify(results=cands, date=str(d))

# ---------- booking ----------
@app.post("/api/book")
@login_required
def book():
    j, D = request.get_json(silent=True) or {}, db()
    try: d = parse_date(j.get("date"))
    except ValueError as e: return err(str(e))
    no, a, b, cls, pax = j.get("train_no"), (j.get("from") or "").upper(), (j.get("to") or "").upper(), j.get("cls"), j.get("passengers") or []
    if cls not in CLASSES or not (1 <= len(pax) <= 4): return err("Choose a class and 1-4 passengers.")
    clean = []
    for p in pax:
        n, ag, gd = str(p.get("name", "")).strip(), p.get("age"), str(p.get("gender", "")).upper()
        if not re.fullmatch(r"[A-Za-z .']{2,60}", n) or not isinstance(ag, int) or not 1 <= ag <= 120 or gd not in ("M", "F", "O"): return err("Check passenger name, age (1-120) and gender.")
        clean.append((n, ag, gd))
    t = D.one("SELECT * FROM trains WHERE number=?", (no,)); fs, ts = leg(D, no, a, b) if t else (None, None)
    if not fs: return err("This train does not run between the selected stations.")
    with LOCK:
        try:
            inv = D.one("SELECT * FROM inventory WHERE train_no=? AND cls=?", (no, cls)); cap = inv["coaches"] * inv["per_coach"]
            tk = taken(D, inv, d); days = (d - ddate.today()).days
            fare = round(base_fare(cls, ts["km"] - fs["km"]) * ai.fare_multiplier(days, min(tk / cap, 1))) * len(clean)
            pnr = new_pnr(D)
            D.q("INSERT INTO bookings(pnr,user_id,train_no,journey_date,from_code,to_code,cls,fare,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (pnr, session["uid"], no, str(d), a, b, cls, fare, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))); bid = D.lastrowid
            for n, ag, gd in clean:
                tk += 1
                if tk <= cap:
                    coach, seat, berth = locate(cls, tk, inv["per_coach"])
                    D.q("INSERT INTO passengers(booking_id,name,age,gender,train_no,journey_date,cls,seat_idx,coach,seat_no,berth,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,'CNF')",
                        (bid, n, ag, gd, no, str(d), cls, tk, coach, seat, berth))
                else:
                    D.q("INSERT INTO passengers(booking_id,name,age,gender,train_no,journey_date,cls,wl_no,status) VALUES(?,?,?,?,?,?,?,?,'WL')", (bid, n, ag, gd, no, str(d), cls, tk - cap))
            D.commit()
        except Exception:
            D.rollback(); raise
    r = booking_detail(D, pnr); r.pop("user_id"); return jsonify(r)

@app.get("/api/pnr/<pnr>")
def pnr_status(pnr):
    if not re.fullmatch(r"\d{10}", pnr): return err("PNR must be exactly 10 digits.")
    r = booking_detail(db(), pnr)
    if not r: return err("PNR not found.", 404)
    r.pop("user_id"); return jsonify(r)

@app.get("/api/my-bookings")
@login_required
def my_bookings():
    D = db(); rows = D.q("SELECT pnr FROM bookings WHERE user_id=? ORDER BY id DESC", (session["uid"],))
    out = []
    for r in rows:
        x = booking_detail(D, r["pnr"]); x.pop("user_id"); out.append(x)
    return jsonify(out)

@app.get("/api/ticket/<pnr>.pdf")
@login_required
def ticket(pnr):
    if not re.fullmatch(r"\d{10}", pnr): return err("Invalid PNR.")
    t = booking_detail(db(), pnr)
    if not t or t["user_id"] != session["uid"]: return err("Ticket not found.", 404)
    return Response(build_ticket(t), mimetype="application/pdf", headers={"Content-Disposition": f"attachment; filename=Ticket_{pnr}.pdf"})

# ---------- connecting-journey safety ----------
@app.post("/api/connection")
def connection():
    j, D = request.get_json(silent=True) or {}, db()
    try: d = parse_date(j.get("date"))
    except ValueError as e: return err(str(e))
    st, na, nb = (j.get("station") or "").upper(), j.get("train_a"), j.get("train_b")
    A, B = D.one("SELECT * FROM trains WHERE number=?", (na,)), D.one("SELECT * FROM trains WHERE number=?", (nb,))
    sa = D.one("SELECT * FROM stops WHERE train_no=? AND code=?", (na, st)); sb = D.one("SELECT * FROM stops WHERE train_no=? AND code=?", (nb, st))
    if not (A and B and sa and sb) or na == nb: return err("Both (different) trains must stop at the transfer station.")
    arr = clock(A, d, sa["arr_min"])
    def next_dep(train, stop):  # next departure of `train` from this stop at/after arrival
        h, m = map(int, train["dep_time"].split(":")); mod = (h * 60 + m + stop["dep_min"]) % 1440
        t = arr.replace(hour=mod // 60, minute=mod % 60)
        return t if t >= arr else t + timedelta(days=1)
    dep = next_dep(B, sb); buf = int((dep - arr).total_seconds() // 60)
    res = ai.connection_safety(min(buf, 300), A["avg_delay"], A["delay_sd"], arr.month, arr.hour)
    alts = []
    for t in D.q("SELECT * FROM trains WHERE number NOT IN (?,?)", (na, nb)):
        s = D.one("SELECT * FROM stops WHERE train_no=? AND code=?", (t["number"], st))
        if s:
            dp = next_dep(t, s); alts.append(((dp - arr).total_seconds(), t["number"], t["name"], dp))
    alts = [dict(train_no=n, name=nm, dep=dp.strftime(FMT), buffer=int(bs // 60)) for bs, n, nm, dp in sorted(alts) if bs // 60 >= res["recommended_buffer"]][:2]
    msg = f"Based on {A['name']}'s delay history: {res['safe_pct']}% safe connection."
    if res["risky"]: msg += f" Recommended minimum buffer: {res['recommended_buffer']} min."
    return jsonify(arrive=arr.strftime(FMT), depart=dep.strftime(FMT), buffer_min=buf, message=msg, alternatives=alts if res["risky"] else [], **res)

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1", port=int(os.getenv("PORT", 5000)))
