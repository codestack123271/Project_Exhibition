"""Sample timetable (illustrative, NOT the official IRCTC schedule). Minutes are offsets from origin departure."""
S = {"NDLS": "New Delhi", "AGC": "Agra Cantt", "GWL": "Gwalior", "JHS": "Jhansi", "BPL": "Bhopal Jn", "ET": "Itarsi Jn",
     "NGP": "Nagpur", "SC": "Secunderabad", "BSL": "Bhusaval", "CSMT": "Mumbai CSMT", "UJN": "Ujjain", "INDB": "Indore"}
# train: (no, name, dep_time, popularity, avg_delay_min, delay_sd, demand, [(code, arr, dep, km)...])
TRAINS = [
 ("12001", "Delhi-Bhopal Superfast", "06:00", .9, 12, 10, .85, [("NDLS",0,0,0),("AGC",125,130,195),("GWL",220,225,320),("JHS",310,315,415),("BPL",510,520,705)]),
 ("12722", "Dakshin Express", "21:15", .8, 28, 22, .75, [("NDLS",0,0,0),("AGC",155,160,195),("JHS",345,350,415),("BPL",570,580,705),("ET",665,670,790),("NGP",930,940,1100),("SC",1375,1375,1660)]),
 ("11061", "Itarsi-Mumbai Express", "10:00", .6, 35, 25, .55, [("ET",0,0,0),("BSL",270,280,310),("CSMT",660,660,640)]),
 ("12627", "Bhopal-Nagpur Intercity", "16:30", .5, 15, 12, .6, [("BPL",0,0,0),("ET",95,100,85),("NGP",375,375,395)]),
 ("12185", "Bhopal-Indore Express", "07:10", .7, 8, 6, .8, [("BPL",0,0,0),("UJN",175,180,190),("INDB",245,245,260)]),
 ("12618", "Mumbai-Delhi Mail", "17:05", .85, 22, 18, .9, [("CSMT",0,0,0),("BSL",425,435,350),("ET",600,610,640),("BPL",705,715,730),("JHS",900,905,1020),("NDLS",1300,1300,1435)]),
]
INV = {"SL": 4, "3A": 3, "2A": 2, "1A": 1}  # coaches per class
PER = {"SL": 72, "3A": 72, "2A": 54, "1A": 24}
def seed(db):
    if db.one("SELECT 1 AS x FROM trains LIMIT 1"): return
    for no, name, dep, pop, dl, sd, dem, stops in TRAINS:
        db.q("INSERT INTO trains VALUES(?,?,?,?,?,?)", (no, name, dep, pop, dl, sd))
        for i, (c, a, d, km) in enumerate(stops, 1):
            db.q("INSERT INTO stops(train_no,seq,code,name,arr_min,dep_min,km) VALUES(?,?,?,?,?,?,?)", (no, i, c, S[c], a, d, km))
        for cls, n in INV.items():
            db.q("INSERT INTO inventory(train_no,cls,coaches,per_coach,demand) VALUES(?,?,?,?,?)", (no, cls, n, PER[cls], dem))
    db.commit()
