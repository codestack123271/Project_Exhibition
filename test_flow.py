import os, re, json
os.environ["DB_PATH"] = "test.db"
from datetime import date, timedelta
from app import app
c = app.test_client(); d = str(date.today() + timedelta(days=20))
print("search unauth ok:", c.get(f"/api/search?from=BPL&to=NGP&date={d}").status_code)
print("book unauth:", c.post("/api/book", json={}).status_code)
print("register:", c.post("/api/register", json=dict(name="Test User", email="t@x.in", password="password1")).json)
r = c.get(f"/api/search?from=BPL&to=NGP&date={d}").json["results"]
for t in r: print(t["train_no"], t["name"], t["score"], t["why"], [(x["cls"], x["status"], x["count"], x["fare"], x["advice"]) for x in t["classes"]])
pnrs = set()
for i in range(30):
    b = c.post("/api/book", json=dict(train_no="12627", date=d, **{"from": "BPL", "to": "NGP"}, cls="1A",
        passengers=[dict(name="Ravi Kumar", age=30, gender="M"), dict(name="Sita Devi", age=28, gender="F")])).json
    assert re.fullmatch(r"[1-9]\d{9}", b["pnr"]); pnrs.add(b["pnr"])
    if i in (0, 29): print(json.dumps(b, indent=1)[:900])
print("unique pnrs:", len(pnrs), "of 30")
seats = [(p["coach"], p["seat_no"]) for pn in pnrs for p in c.get(f"/api/pnr/{pn}").json["passengers"] if p["status"] == "CNF"]
print("confirmed seats:", len(seats), "duplicates:", len(seats) - len(set(seats)))
pn = sorted(pnrs)[-1]; print("PNR status:", c.get(f"/api/pnr/{pn}").json)
print("bad pnr:", c.get("/api/pnr/123").status_code, c.get("/api/pnr/1234567890").status_code)
pdf = c.get(f"/api/ticket/{pn}.pdf"); print("pdf:", pdf.status_code, pdf.mimetype, pdf.data[:5], len(pdf.data)); open("/tmp/t.pdf", "wb").write(pdf.data)
c2 = app.test_client(); print("pdf other user:", c2.get(f"/api/ticket/{pn}.pdf").status_code)
print("conn:", c.post("/api/connection", json=dict(train_a="12001", train_b="12627", station="BPL", date=d)).json)
print("conn2:", c.post("/api/connection", json=dict(train_a="12001", train_b="12627", station="NGP", date=d)).status_code)
print("my:", len(c.get("/api/my-bookings").json), "bad book:", c.post("/api/book", json=dict(train_no="12627", date=d, **{"from": "NGP", "to": "BPL"}, cls="3A", passengers=[dict(name="A B", age=3, gender="M")])).json)
